from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import sleep

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Event, Job, Resource
from app.provisioners.factory import make_provisioner
from app.services.resources import queue_expired_resources_for_cleanup
from app.state import ActualState, DesiredState


def add_event(
    session: Session,
    *,
    resource_id: int,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    session.add(
        Event(
            resource_id=resource_id,
            actor_user_id=None,
            event_type=event_type,
            message=message,
            event_metadata=metadata or {},
        )
    )


def mark_job_running(session: Session, job: Job) -> None:
    job.status = "running"
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    session.commit()


def mark_job_succeeded(session: Session, job: Job) -> None:
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    session.commit()


async def provision_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()

    mark_job_running(session, job)
    resource.actual_state = ActualState.PROVISIONING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.provisioning",
        message="Worker started provisioning.",
        metadata={"job_id": job.id},
    )
    session.commit()

    result = await provisioner.provision(
        resource_id=resource.id,
        slug=resource.slug,
        image=resource.template.image,
        exposed_port=resource.template.exposed_port,
        cpu_limit=resource.cpu_limit,
        memory_mb=resource.memory_mb,
    )

    resource.external_id = result.external_id
    resource.url = result.url
    resource.actual_state = result.status
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.running",
        message="Provisioner marked the resource running.",
        metadata={"external_id": result.external_id, "url": result.url},
    )
    mark_job_succeeded(session, job)


async def start_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()

    mark_job_running(session, job)
    resource.actual_state = ActualState.STARTING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.starting",
        message="Worker started the resource.",
        metadata={"job_id": job.id},
    )
    session.commit()

    if resource.external_id is None:
        raise ValueError("Cannot start resource without an external ID")

    await provisioner.start(external_id=resource.external_id)
    resource.actual_state = ActualState.RUNNING.value
    resource.desired_state = DesiredState.RUNNING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.running",
        message="Resource is running.",
        metadata={"external_id": resource.external_id},
    )
    mark_job_succeeded(session, job)


async def stop_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()

    mark_job_running(session, job)
    resource.actual_state = ActualState.STOPPING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.stopping",
        message="Worker stopped the resource.",
        metadata={"job_id": job.id},
    )
    session.commit()

    if resource.external_id is None:
        raise ValueError("Cannot stop resource without an external ID")

    await provisioner.stop(external_id=resource.external_id)
    resource.actual_state = ActualState.STOPPED.value
    resource.desired_state = DesiredState.STOPPED.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.stopped",
        message="Resource is stopped.",
        metadata={"external_id": resource.external_id},
    )
    mark_job_succeeded(session, job)


async def restart_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()

    mark_job_running(session, job)
    resource.actual_state = ActualState.STOPPING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.stopping",
        message="Worker stopped the resource for restart.",
        metadata={"job_id": job.id},
    )
    session.commit()

    if resource.external_id is None:
        raise ValueError("Cannot restart resource without an external ID")

    await provisioner.stop(external_id=resource.external_id)
    resource.actual_state = ActualState.STARTING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.starting",
        message="Worker started the resource after restart.",
        metadata={"job_id": job.id},
    )
    session.commit()

    await provisioner.start(external_id=resource.external_id)
    resource.actual_state = ActualState.RUNNING.value
    resource.desired_state = DesiredState.RUNNING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.running",
        message="Resource is running after restart.",
        metadata={"external_id": resource.external_id},
    )
    mark_job_succeeded(session, job)


async def delete_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()

    mark_job_running(session, job)
    resource.actual_state = ActualState.DELETING.value
    resource.desired_state = DesiredState.DELETED.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.deleting",
        message="Worker started cleanup.",
        metadata={"job_id": job.id},
    )
    session.commit()

    if resource.external_id is not None:
        await provisioner.delete(external_id=resource.external_id)

    resource.actual_state = ActualState.DELETED.value
    resource.desired_state = DesiredState.DELETED.value
    resource.deleted_at = datetime.now(UTC)
    resource.url = None
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.deleted",
        message="Resource cleanup finished.",
        metadata={"external_id": resource.external_id},
    )
    mark_job_succeeded(session, job)


async def process_queued_jobs(session: Session, limit: int = 10) -> int:
    jobs = list(
        session.scalars(
            select(Job).where(Job.status == "queued").order_by(Job.created_at.asc()).limit(limit)
        ).all()
    )

    processed = 0
    for job in jobs:
        resource = session.get(Resource, job.resource_id)
        if resource is None:
            job.status = "failed"
            job.last_error = "Resource no longer exists"
            job.finished_at = datetime.now(UTC)
            session.commit()
            processed += 1
            continue

        resource_id = resource.id
        try:
            if job.kind == "provision_resource":
                await provision_resource(session, job, resource)
            elif job.kind == "start_resource":
                await start_resource(session, job, resource)
            elif job.kind == "stop_resource":
                await stop_resource(session, job, resource)
            elif job.kind == "restart_resource":
                await restart_resource(session, job, resource)
            elif job.kind == "delete_resource":
                await delete_resource(session, job, resource)
            else:
                raise ValueError(f"Unknown job kind: {job.kind}")
        except Exception as exc:
            session.rollback()
            job = session.get(Job, job.id)
            resource = session.get(Resource, resource_id)
            if job is not None:
                job.status = "failed"
                job.last_error = str(exc)
                job.finished_at = datetime.now(UTC)
            if resource is not None:
                resource.actual_state = ActualState.FAILED.value
                add_event(
                    session,
                    resource_id=resource.id,
                    event_type="resource.failed",
                    message="Provisioning failed.",
                    metadata={"error": str(exc)},
                )
            session.commit()
        processed += 1

    return processed


async def run_once() -> int:
    with SessionLocal() as session:
        queued_cleanup = queue_expired_resources_for_cleanup(session)
        processed = await process_queued_jobs(session)
        return queued_cleanup + processed


def main() -> None:
    print("TinyProvisioner worker started")
    while True:
        processed = asyncio.run(run_once())
        if processed == 0:
            sleep(3)


if __name__ == "__main__":
    main()
