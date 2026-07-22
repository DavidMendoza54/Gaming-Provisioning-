from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter, sleep
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.database import SessionLocal
from app.models import Event, Job, Resource, Worker
from app.observability import (
    configure_logging,
    record_worker_job_claim,
    record_worker_job_result,
    record_worker_loop,
    record_worker_recovery,
    set_worker_queue_depth,
    start_worker_metrics_server,
)
from app.provisioners.factory import make_provisioner
from app.services.resources import queue_expired_resources_for_cleanup
from app.settings import get_settings
from app.state import ActualState, DesiredState, JobStatus, WorkerStatus


SessionFactory = Callable[[], Session]
ONE_RUNNING_JOB_INDEX = "uq_jobs_one_running_per_resource"
logger = logging.getLogger("tinyprovisioner.worker")


class PermanentJobError(RuntimeError):
    """A data or job-definition error that will not improve after a retry."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"


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


def claimable_jobs_statement(*, now: datetime, limit: int = 1):
    """Build the short transaction that distributes queue rows across workers."""

    other_job = aliased(Job)
    resource_has_running_job = (
        select(other_job.id)
        .where(
            other_job.resource_id == Job.resource_id,
            other_job.status == JobStatus.RUNNING.value,
        )
        .exists()
    )
    return (
        select(Job)
        .join(Resource, Resource.id == Job.resource_id)
        .where(
            Job.status == JobStatus.QUEUED.value,
            Job.available_at <= now,
            ~resource_has_running_job,
        )
        .order_by(Job.available_at.asc(), Job.created_at.asc(), Job.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True, of=(Job, Resource))
    )


def touch_worker(
    session: Session,
    *,
    worker_id: str,
    now: datetime,
    current_job_id: int | None,
) -> Worker:
    worker = session.get(Worker, worker_id)
    if worker is None:
        worker = Worker(
            id=worker_id,
            hostname=socket.gethostname(),
            process_id=os.getpid(),
            status=WorkerStatus.RUNNING.value,
            started_at=now,
            heartbeat_at=now,
            current_job_id=current_job_id,
        )
        session.add(worker)
        return worker

    worker.status = WorkerStatus.RUNNING.value
    worker.heartbeat_at = now
    worker.current_job_id = current_job_id
    return worker


def claim_jobs(
    session: Session,
    *,
    worker_id: str,
    limit: int = 1,
    now: datetime | None = None,
) -> list[Job]:
    """Atomically lease ready jobs to one worker and release the row locks."""

    claimed_at = now or utc_now()
    jobs = list(session.scalars(claimable_jobs_statement(now=claimed_at, limit=limit)).all())

    for job in jobs:
        job.status = JobStatus.RUNNING.value
        job.attempts += 1
        job.claimed_by = worker_id
        job.claimed_at = claimed_at
        job.heartbeat_at = claimed_at
        job.started_at = claimed_at
        job.finished_at = None

    current_job_id = jobs[0].id if len(jobs) == 1 else None
    touch_worker(
        session,
        worker_id=worker_id,
        now=claimed_at,
        current_job_id=current_job_id,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint_name != ONE_RUNNING_JOB_INDEX:
            raise
        session.rollback()
        touch_worker(
            session,
            worker_id=worker_id,
            now=claimed_at,
            current_job_id=None,
        )
        session.commit()
        return []
    for job in jobs:
        record_worker_job_claim(kind=job.kind)
        logger.info(
            "worker.job.claimed",
            extra={
                "worker_id": worker_id,
                "job_id": job.id,
                "job_kind": job.kind,
                "resource_id": job.resource_id,
                "attempt": job.attempts,
            },
        )
    return jobs


def retry_delay_seconds(
    *,
    job_id: int,
    attempts: int,
    base_seconds: int,
    max_seconds: int,
) -> int:
    """Return capped exponential backoff with stable per-job jitter."""

    exponent = max(attempts - 1, 0)
    exponential = min(max_seconds, base_seconds * (2**exponent))
    if exponential >= max_seconds:
        return max_seconds

    jitter_window = min(max_seconds - exponential, max(1, exponential // 4))
    digest = hashlib.sha256(f"{job_id}:{attempts}".encode()).digest()
    jitter = int.from_bytes(digest[:4], "big") % (jitter_window + 1)
    return exponential + jitter


def mark_job_succeeded(
    session: Session,
    job: Job,
    *,
    worker_id: str,
    now: datetime,
) -> bool:
    with session.no_autoflush:
        session.refresh(job, with_for_update=True)
    if job.status != JobStatus.RUNNING.value or job.claimed_by != worker_id:
        session.rollback()
        return False

    job.status = JobStatus.SUCCEEDED.value
    job.finished_at = now
    _clear_current_job(session, worker_id=job.claimed_by, job_id=job.id, now=now)
    session.commit()
    return True


async def provision_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()
    template = resource.template
    request = {
        "resource_id": resource.id,
        "slug": resource.slug,
        "image": template.image,
        "exposed_port": template.exposed_port,
        "cpu_limit": resource.cpu_limit,
        "memory_mb": resource.memory_mb,
    }

    resource.actual_state = ActualState.PROVISIONING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.provisioning",
        message="Worker started provisioning.",
        metadata={"job_id": job.id, "attempt": job.attempts},
    )
    session.commit()

    result = await provisioner.provision(**request)

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


async def start_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()
    external_id = resource.external_id
    if external_id is None:
        raise PermanentJobError("Cannot start resource without an external ID")

    resource.actual_state = ActualState.STARTING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.starting",
        message="Worker started the resource.",
        metadata={"job_id": job.id, "attempt": job.attempts},
    )
    session.commit()

    await provisioner.start(external_id=external_id)
    resource.actual_state = ActualState.RUNNING.value
    resource.desired_state = DesiredState.RUNNING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.running",
        message="Resource is running.",
        metadata={"external_id": external_id},
    )


async def stop_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()
    external_id = resource.external_id
    if external_id is None:
        raise PermanentJobError("Cannot stop resource without an external ID")

    resource.actual_state = ActualState.STOPPING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.stopping",
        message="Worker stopped the resource.",
        metadata={"job_id": job.id, "attempt": job.attempts},
    )
    session.commit()

    await provisioner.stop(external_id=external_id)
    resource.actual_state = ActualState.STOPPED.value
    resource.desired_state = DesiredState.STOPPED.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.stopped",
        message="Resource is stopped.",
        metadata={"external_id": external_id},
    )


async def restart_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()
    external_id = resource.external_id
    if external_id is None:
        raise PermanentJobError("Cannot restart resource without an external ID")

    resource.actual_state = ActualState.STOPPING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.stopping",
        message="Worker stopped the resource for restart.",
        metadata={"job_id": job.id, "attempt": job.attempts},
    )
    session.commit()

    await provisioner.stop(external_id=external_id)
    resource.actual_state = ActualState.STARTING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.starting",
        message="Worker started the resource after restart.",
        metadata={"job_id": job.id, "attempt": job.attempts},
    )
    session.commit()

    await provisioner.start(external_id=external_id)
    resource.actual_state = ActualState.RUNNING.value
    resource.desired_state = DesiredState.RUNNING.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.running",
        message="Resource is running after restart.",
        metadata={"external_id": external_id},
    )


async def delete_resource(session: Session, job: Job, resource: Resource) -> None:
    provisioner = make_provisioner()
    external_id = resource.external_id

    resource.actual_state = ActualState.DELETING.value
    resource.desired_state = DesiredState.DELETED.value
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.deleting",
        message="Worker started cleanup.",
        metadata={"job_id": job.id, "attempt": job.attempts},
    )
    session.commit()

    if external_id is not None:
        await provisioner.delete(external_id=external_id)

    resource.actual_state = ActualState.DELETED.value
    resource.desired_state = DesiredState.DELETED.value
    resource.deleted_at = utc_now()
    resource.url = None
    add_event(
        session,
        resource_id=resource.id,
        event_type="resource.deleted",
        message="Resource cleanup finished.",
        metadata={"external_id": external_id},
    )


async def dispatch_job(session: Session, job: Job, resource: Resource) -> None:
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
        raise PermanentJobError(f"Unknown job kind: {job.kind}")


def heartbeat_job_lease(
    session: Session,
    *,
    worker_id: str,
    job_id: int,
    now: datetime | None = None,
) -> bool:
    heartbeat_at = now or utc_now()
    job = session.get(Job, job_id)
    if (
        job is None
        or job.status != JobStatus.RUNNING.value
        or job.claimed_by != worker_id
    ):
        session.rollback()
        return False

    job.heartbeat_at = heartbeat_at
    touch_worker(
        session,
        worker_id=worker_id,
        now=heartbeat_at,
        current_job_id=job_id,
    )
    session.commit()
    return True


async def maintain_job_lease(
    *,
    session_factory: SessionFactory,
    worker_id: str,
    job_id: int,
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            with session_factory() as heartbeat_session:
                if not heartbeat_job_lease(
                    heartbeat_session,
                    worker_id=worker_id,
                    job_id=job_id,
                ):
                    return
        except SQLAlchemyError as exc:
            logger.warning(
                "worker.heartbeat.failed",
                extra={
                    "worker_id": worker_id,
                    "job_id": job_id,
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(1, interval_seconds))
        except TimeoutError:
            continue


async def _stop_heartbeat(task: asyncio.Task | None, stop_event: asyncio.Event) -> None:
    if task is None:
        return
    stop_event.set()
    await task


def handle_job_failure(
    session: Session,
    *,
    job_id: int,
    resource_id: int,
    error: Exception,
    retryable: bool,
    worker_id: str,
    now: datetime,
) -> str:
    settings = get_settings()
    job = session.get(Job, job_id, with_for_update=True)
    resource = session.get(Resource, resource_id)
    if (
        job is None
        or job.status != JobStatus.RUNNING.value
        or job.claimed_by != worker_id
    ):
        session.rollback()
        logger.warning(
            "worker.job.claim_lost",
            extra={
                "worker_id": worker_id,
                "job_id": job_id,
                "resource_id": resource_id,
                "result": "lost_claim",
            },
        )
        return "lost_claim"

    job.last_error = str(error)
    if retryable and job.attempts < job.max_attempts:
        delay = retry_delay_seconds(
            job_id=job.id,
            attempts=job.attempts,
            base_seconds=settings.job_retry_base_seconds,
            max_seconds=settings.job_retry_max_seconds,
        )
        _clear_current_job(session, worker_id=job.claimed_by, job_id=job.id, now=now)
        job.status = JobStatus.QUEUED.value
        job.available_at = now + timedelta(seconds=delay)
        job.claimed_by = None
        job.claimed_at = None
        job.heartbeat_at = None
        job.finished_at = None
        if resource is not None:
            add_event(
                session,
                resource_id=resource.id,
                event_type="job.retry_scheduled",
                message="Worker scheduled another attempt after a transient failure.",
                metadata={
                    "job_id": job.id,
                    "attempt": job.attempts,
                    "max_attempts": job.max_attempts,
                    "retry_in_seconds": delay,
                    "error": str(error),
                },
            )
        session.commit()
        logger.warning(
            "worker.job.retry_scheduled",
            extra={
                "worker_id": worker_id,
                "job_id": job.id,
                "job_kind": job.kind,
                "resource_id": resource_id,
                "attempt": job.attempts,
                "result": "retry",
                "retry_in_seconds": delay,
                "error_type": type(error).__name__,
            },
        )
        return "retry"

    job.status = JobStatus.DEAD.value
    job.finished_at = now
    _clear_current_job(session, worker_id=job.claimed_by, job_id=job.id, now=now)
    if resource is not None:
        resource.actual_state = ActualState.FAILED.value
        add_event(
            session,
            resource_id=resource.id,
            event_type="job.dead",
            message="Job exhausted its retry policy and entered the dead-letter state.",
            metadata={
                "job_id": job.id,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "retryable": retryable,
                "error": str(error),
            },
        )
        add_event(
            session,
            resource_id=resource.id,
            event_type="resource.failed",
            message="Provisioning failed after the job retry policy ended.",
            metadata={"job_id": job.id, "error": str(error)},
        )
    session.commit()
    logger.error(
        "worker.job.dead",
        extra={
            "worker_id": worker_id,
            "job_id": job.id,
            "job_kind": job.kind,
            "resource_id": resource_id,
            "attempt": job.attempts,
            "result": "dead",
            "error_type": type(error).__name__,
        },
    )
    return "dead"


async def process_claimed_job(
    session: Session,
    job: Job,
    *,
    worker_id: str,
    now: datetime | None = None,
    heartbeat_session_factory: SessionFactory | None = None,
) -> None:
    started_at = perf_counter()
    job_kind = job.kind
    resource = session.get(Resource, job.resource_id)
    if resource is None:
        result = handle_job_failure(
            session,
            job_id=job.id,
            resource_id=job.resource_id,
            error=PermanentJobError("Resource no longer exists"),
            retryable=False,
            worker_id=worker_id,
            now=now or utc_now(),
        )
        record_worker_job_result(
            kind=job_kind,
            result=result,
            duration_seconds=perf_counter() - started_at,
        )
        return

    stop_event = asyncio.Event()
    heartbeat_task = None
    if heartbeat_session_factory is not None:
        heartbeat_task = asyncio.create_task(
            maintain_job_lease(
                session_factory=heartbeat_session_factory,
                worker_id=worker_id,
                job_id=job.id,
                interval_seconds=get_settings().worker_heartbeat_interval_seconds,
                stop_event=stop_event,
            )
        )

    try:
        await dispatch_job(session, job, resource)
    except Exception as exc:
        await _stop_heartbeat(heartbeat_task, stop_event)
        session.rollback()
        result = handle_job_failure(
            session,
            job_id=job.id,
            resource_id=resource.id,
            error=exc,
            retryable=not isinstance(exc, PermanentJobError),
            worker_id=worker_id,
            now=now or utc_now(),
        )
        record_worker_job_result(
            kind=job_kind,
            result=result,
            duration_seconds=perf_counter() - started_at,
        )
        return

    await _stop_heartbeat(heartbeat_task, stop_event)
    succeeded = mark_job_succeeded(
        session,
        job,
        worker_id=worker_id,
        now=now or utc_now(),
    )
    result = "succeeded" if succeeded else "lost_claim"
    duration_seconds = perf_counter() - started_at
    record_worker_job_result(
        kind=job_kind,
        result=result,
        duration_seconds=duration_seconds,
    )
    log_method = logger.info if succeeded else logger.warning
    log_method(
        "worker.job.completed" if succeeded else "worker.job.claim_lost",
        extra={
            "worker_id": worker_id,
            "job_id": job.id,
            "job_kind": job_kind,
            "resource_id": job.resource_id,
            "attempt": job.attempts,
            "result": result,
            "duration_ms": round(duration_seconds * 1000, 3),
        },
    )


async def process_queued_jobs(
    session: Session,
    limit: int = 10,
    *,
    worker_id: str = "test-worker",
    now: datetime | None = None,
    heartbeat_session_factory: SessionFactory | None = None,
) -> int:
    processed = 0
    for _ in range(limit):
        jobs = claim_jobs(session, worker_id=worker_id, limit=1, now=now)
        if not jobs:
            break
        await process_claimed_job(
            session,
            jobs[0],
            worker_id=worker_id,
            now=now,
            heartbeat_session_factory=heartbeat_session_factory,
        )
        processed += 1
    return processed


def recover_abandoned_jobs(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    settings = get_settings()
    recovered_at = now or utc_now()
    stale_before = recovered_at - timedelta(seconds=settings.job_lease_seconds)
    stale_lease = or_(
        Job.heartbeat_at < stale_before,
        and_(
            Job.heartbeat_at.is_(None),
            or_(Job.claimed_at.is_(None), Job.claimed_at < stale_before),
        ),
    )
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.status == JobStatus.RUNNING.value, stale_lease)
            .order_by(Job.claimed_at.asc(), Job.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True, of=Job)
        ).all()
    )

    recovery_results: list[dict[str, object]] = []
    for job in jobs:
        worker_id = job.claimed_by
        resource = session.get(Resource, job.resource_id)
        error = f"Worker lease expired after {settings.job_lease_seconds} seconds"
        job.last_error = error
        _mark_worker_stale(session, worker_id=worker_id, job_id=job.id)

        if job.attempts < job.max_attempts:
            delay = retry_delay_seconds(
                job_id=job.id,
                attempts=job.attempts,
                base_seconds=settings.job_retry_base_seconds,
                max_seconds=settings.job_retry_max_seconds,
            )
            job.status = JobStatus.QUEUED.value
            job.available_at = recovered_at + timedelta(seconds=delay)
            job.claimed_by = None
            job.claimed_at = None
            job.heartbeat_at = None
            job.finished_at = None
            if resource is not None:
                add_event(
                    session,
                    resource_id=resource.id,
                    event_type="job.recovered",
                    message="An abandoned job lease was recovered and scheduled for retry.",
                    metadata={
                        "job_id": job.id,
                        "previous_worker": worker_id,
                        "retry_in_seconds": delay,
                    },
                )
            recovery_results.append(
                {
                    "worker_id": worker_id,
                    "job_id": job.id,
                    "job_kind": job.kind,
                    "resource_id": job.resource_id,
                    "attempt": job.attempts,
                    "result": "retry",
                }
            )
            continue

        job.status = JobStatus.DEAD.value
        job.finished_at = recovered_at
        if resource is not None:
            resource.actual_state = ActualState.FAILED.value
            add_event(
                session,
                resource_id=resource.id,
                event_type="job.dead",
                message="An abandoned job exhausted its retry policy.",
                metadata={"job_id": job.id, "previous_worker": worker_id, "error": error},
            )
            add_event(
                session,
                resource_id=resource.id,
                event_type="resource.failed",
                message="The resource failed after its worker lease expired.",
                metadata={"job_id": job.id, "error": error},
            )
        recovery_results.append(
            {
                "worker_id": worker_id,
                "job_id": job.id,
                "job_kind": job.kind,
                "resource_id": job.resource_id,
                "attempt": job.attempts,
                "result": "dead",
            }
        )

    session.commit()
    for recovery in recovery_results:
        outcome = str(recovery["result"])
        record_worker_recovery(outcome=outcome)
        record_worker_job_result(
            kind=str(recovery["job_kind"]),
            result=f"recovered_{outcome}",
            duration_seconds=None,
        )
        logger.warning("worker.job.recovered", extra=recovery)
    return len(jobs)


def observe_queue_depth(session: Session) -> dict[str, int]:
    rows = session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
    counts = {str(status): int(count) for status, count in rows}
    set_worker_queue_depth(counts)
    return counts


def _clear_current_job(
    session: Session,
    *,
    worker_id: str | None,
    job_id: int,
    now: datetime,
) -> None:
    if worker_id is None:
        return
    worker = session.get(Worker, worker_id)
    if worker is not None and worker.current_job_id == job_id:
        worker.current_job_id = None
        worker.heartbeat_at = now


def _mark_worker_stale(
    session: Session,
    *,
    worker_id: str | None,
    job_id: int,
) -> None:
    if worker_id is None:
        return
    worker = session.get(Worker, worker_id)
    if worker is not None and worker.current_job_id == job_id:
        worker.current_job_id = None
        worker.status = WorkerStatus.STOPPED.value


async def run_once(
    *,
    worker_id: str | None = None,
    heartbeat_session_factory: SessionFactory | None = SessionLocal,
) -> int:
    started_at = perf_counter()
    selected_worker_id = worker_id or make_worker_id()
    try:
        with SessionLocal() as session:
            recovered = recover_abandoned_jobs(session)
            queued_cleanup = queue_expired_resources_for_cleanup(session)
            processed = await process_queued_jobs(
                session,
                worker_id=selected_worker_id,
                heartbeat_session_factory=heartbeat_session_factory,
            )
            observe_queue_depth(session)
    except Exception:
        record_worker_loop(result="error", duration_seconds=perf_counter() - started_at)
        raise

    duration_seconds = perf_counter() - started_at
    record_worker_loop(result="success", duration_seconds=duration_seconds)
    total = recovered + queued_cleanup + processed
    if total:
        logger.info(
            "worker.loop.completed",
            extra={
                "worker_id": selected_worker_id,
                "recovered_jobs": recovered,
                "queued_cleanup": queued_cleanup,
                "processed_jobs": processed,
                "duration_ms": round(duration_seconds * 1000, 3),
            },
        )
    return total


def mark_worker_stopped(worker_id: str) -> None:
    with SessionLocal() as session:
        worker = session.get(Worker, worker_id)
        if worker is None:
            return
        worker.status = WorkerStatus.STOPPED.value
        worker.current_job_id = None
        worker.heartbeat_at = utc_now()
        session.commit()


def run_forever(*, idle_sleep_seconds: int = 3) -> None:
    worker_id = make_worker_id()
    logger.info("worker.started", extra={"worker_id": worker_id})
    try:
        while True:
            try:
                processed = asyncio.run(
                    run_once(
                        worker_id=worker_id,
                        heartbeat_session_factory=SessionLocal,
                    )
                )
            except SQLAlchemyError as exc:
                logger.warning(
                    "worker.database_unavailable",
                    extra={
                        "worker_id": worker_id,
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                sleep(idle_sleep_seconds)
                continue

            if processed == 0:
                sleep(idle_sleep_seconds)
    except KeyboardInterrupt:
        logger.info("worker.shutdown_requested", extra={"worker_id": worker_id})
    finally:
        try:
            mark_worker_stopped(worker_id)
        except SQLAlchemyError as exc:
            logger.error(
                "worker.shutdown_record_failed",
                extra={
                    "worker_id": worker_id,
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )


def _request_shutdown(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    settings = get_settings()
    configure_logging(service="worker", level=settings.log_level)
    start_worker_metrics_server(port=settings.worker_metrics_port)
    logger.info(
        "worker.metrics_started",
        extra={"metrics_port": settings.worker_metrics_port},
    )
    signal.signal(signal.SIGTERM, _request_shutdown)
    run_forever()


if __name__ == "__main__":
    main()
