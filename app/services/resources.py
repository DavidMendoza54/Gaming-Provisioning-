from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, Job, Resource, Template, User
from app.schemas import ResourceCreate
from app.settings import get_settings
from app.state import ActualState, DesiredState


SLUG_SAFE = re.compile(r"[^a-z0-9-]+")


class ResourceActionError(ValueError):
    pass


def slugify(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    normalized = SLUG_SAFE.sub("", normalized)
    normalized = normalized.strip("-")
    return normalized or "resource"


def create_resource(session: Session, user: User, payload: ResourceCreate) -> Resource:
    settings = get_settings()
    template = session.get(Template, payload.template_id)
    if template is None or not template.enabled:
        raise ValueError("Template does not exist or is disabled")

    active_count = count_active_resources(session, user)
    if active_count >= settings.max_active_resources_per_user:
        raise ResourceActionError(
            f"Resource quota exceeded: max {settings.max_active_resources_per_user} active resources"
        )

    expires_at = datetime.now(UTC) + timedelta(hours=settings.default_resource_ttl_hours)
    slug = f"{slugify(payload.name)}-{uuid4().hex[:8]}"
    resource = Resource(
        user_id=user.id,
        template_id=template.id,
        slug=slug,
        desired_state=DesiredState.RUNNING.value,
        actual_state=ActualState.PENDING.value,
        cpu_limit=template.default_cpu,
        memory_mb=template.default_memory_mb,
        expires_at=expires_at,
    )
    session.add(resource)
    session.flush()

    job = Job(resource_id=resource.id, kind="provision_resource", status="queued")
    event = Event(
        resource_id=resource.id,
        actor_user_id=user.id,
        event_type="resource.created",
        message="Resource requested and provisioning job queued.",
        event_metadata={"job_kind": job.kind},
    )
    session.add_all([job, event])
    session.commit()
    session.refresh(resource)
    return resource


def count_active_resources(session: Session, user: User) -> int:
    return session.scalar(
        select(func.count(Resource.id)).where(
            Resource.user_id == user.id,
            Resource.actual_state.notin_([ActualState.DELETING.value, ActualState.DELETED.value]),
        )
    ) or 0


def get_owned_resource(session: Session, user: User, resource_id: int) -> Resource | None:
    return session.scalar(
        select(Resource).where(Resource.id == resource_id, Resource.user_id == user.id)
    )


def queue_stop_resource(session: Session, resource: Resource, actor: User) -> Resource:
    if resource.actual_state == ActualState.STOPPED.value:
        return resource
    if resource.actual_state != ActualState.RUNNING.value:
        raise ResourceActionError(f"Cannot stop resource from state {resource.actual_state}")

    resource.desired_state = DesiredState.STOPPED.value
    resource.actual_state = ActualState.STOPPING.value
    _add_job_and_event(
        session,
        resource=resource,
        actor=actor,
        job_kind="stop_resource",
        event_type="resource.stop_queued",
        message="Stop requested and job queued.",
    )
    session.commit()
    session.refresh(resource)
    return resource


def queue_start_resource(session: Session, resource: Resource, actor: User) -> Resource:
    if resource.actual_state == ActualState.RUNNING.value:
        return resource
    if resource.actual_state != ActualState.STOPPED.value:
        raise ResourceActionError(f"Cannot start resource from state {resource.actual_state}")

    resource.desired_state = DesiredState.RUNNING.value
    resource.actual_state = ActualState.STARTING.value
    _add_job_and_event(
        session,
        resource=resource,
        actor=actor,
        job_kind="start_resource",
        event_type="resource.start_queued",
        message="Start requested and job queued.",
    )
    session.commit()
    session.refresh(resource)
    return resource


def queue_restart_resource(session: Session, resource: Resource, actor: User) -> Resource:
    if resource.actual_state != ActualState.RUNNING.value:
        raise ResourceActionError(f"Cannot restart resource from state {resource.actual_state}")

    resource.desired_state = DesiredState.RUNNING.value
    resource.actual_state = ActualState.STOPPING.value
    _add_job_and_event(
        session,
        resource=resource,
        actor=actor,
        job_kind="restart_resource",
        event_type="resource.restart_queued",
        message="Restart requested and job queued.",
    )
    session.commit()
    session.refresh(resource)
    return resource


def queue_delete_resource(session: Session, resource: Resource, actor: User) -> Resource:
    if resource.actual_state in {ActualState.DELETING.value, ActualState.DELETED.value}:
        return resource

    for job in resource.jobs:
        if job.status == "queued" and job.kind != "delete_resource":
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)

    resource.desired_state = DesiredState.DELETED.value
    resource.actual_state = ActualState.DELETING.value
    _add_job_and_event(
        session,
        resource=resource,
        actor=actor,
        job_kind="delete_resource",
        event_type="resource.delete_queued",
        message="Delete requested and cleanup job queued.",
    )
    session.commit()
    session.refresh(resource)
    return resource


def _add_job_and_event(
    session: Session,
    *,
    resource: Resource,
    actor: User,
    job_kind: str,
    event_type: str,
    message: str,
) -> None:
    job = Job(resource_id=resource.id, kind=job_kind, status="queued")
    event = Event(
        resource_id=resource.id,
        actor_user_id=actor.id,
        event_type=event_type,
        message=message,
        event_metadata={"job_kind": job.kind},
    )
    session.add_all([job, event])


def queue_expired_resources_for_cleanup(session: Session, *, now: datetime | None = None) -> int:
    cutoff = now or datetime.now(UTC)
    expired_resources = list(
        session.scalars(
            select(Resource).where(
                Resource.expires_at.is_not(None),
                Resource.expires_at <= cutoff,
                Resource.actual_state.notin_([ActualState.DELETING.value, ActualState.DELETED.value]),
            )
        ).all()
    )

    queued = 0
    for resource in expired_resources:
        if any(job.status == "queued" and job.kind == "delete_resource" for job in resource.jobs):
            continue

        for job in resource.jobs:
            if job.status == "queued" and job.kind != "delete_resource":
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC)

        resource.desired_state = DesiredState.DELETED.value
        resource.actual_state = ActualState.DELETING.value
        job = Job(resource_id=resource.id, kind="delete_resource", status="queued")
        event = Event(
            resource_id=resource.id,
            actor_user_id=None,
            event_type="resource.expired",
            message="Resource expired and cleanup job was queued.",
            event_metadata={"job_kind": job.kind, "expires_at": resource.expires_at.isoformat()},
        )
        session.add_all([job, event])
        queued += 1

    session.commit()
    return queued
