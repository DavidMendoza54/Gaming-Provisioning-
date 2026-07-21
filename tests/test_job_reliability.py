import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import Event, Job, Resource, User, Worker
from app.schemas import ResourceCreate
from app.services.resources import create_resource
from app.settings import Settings, get_settings
from app.state import JobStatus, WorkerStatus
from app.worker import (
    claim_jobs,
    claimable_jobs_statement,
    heartbeat_job_lease,
    mark_job_succeeded,
    process_queued_jobs,
    recover_abandoned_jobs,
    retry_delay_seconds,
)


class AlwaysFailProvisioner:
    async def provision(self, **_kwargs):
        raise RuntimeError("temporary infrastructure failure")


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_pending_resource(session: Session, *, email: str = "reliability@example.local") -> Resource:
    user = User(email=email, role="user")
    session.add(user)
    session.commit()
    session.refresh(user)
    return create_resource(
        session,
        user,
        ResourceCreate(template_id=1, name="Reliable Worker Demo"),
    )


def test_claim_statement_uses_postgres_skip_locked() -> None:
    statement = claimable_jobs_statement(now=datetime.now(UTC), limit=1)
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE OF jobs, resources SKIP LOCKED" in sql


def test_only_one_worker_can_claim_a_job(session: Session) -> None:
    resource = create_pending_resource(session)
    claim_time = datetime.now(UTC) + timedelta(seconds=1)

    first = claim_jobs(session, worker_id="worker-a", now=claim_time)
    second = claim_jobs(session, worker_id="worker-b", now=claim_time)

    assert [job.resource_id for job in first] == [resource.id]
    assert second == []

    job = session.get(Job, first[0].id)
    worker_a = session.get(Worker, "worker-a")
    worker_b = session.get(Worker, "worker-b")
    assert job is not None
    assert job.status == JobStatus.RUNNING.value
    assert job.attempts == 1
    assert job.claimed_by == "worker-a"
    assert job.heartbeat_at is not None and as_utc(job.heartbeat_at) == claim_time
    assert worker_a is not None and worker_a.current_job_id == job.id
    assert worker_b is not None and worker_b.current_job_id is None


def test_workers_do_not_run_two_jobs_for_one_resource(session: Session) -> None:
    resource = create_pending_resource(session)
    session.add(Job(resource_id=resource.id, kind="delete_resource"))
    session.commit()
    claim_time = datetime.now(UTC) + timedelta(seconds=1)

    first = claim_jobs(session, worker_id="resource-worker-a", now=claim_time)
    second = claim_jobs(session, worker_id="resource-worker-b", now=claim_time)

    assert len(first) == 1
    assert second == []
    jobs = session.query(Job).filter_by(resource_id=resource.id).order_by(Job.id).all()
    assert [job.status for job in jobs] == [JobStatus.RUNNING.value, JobStatus.QUEUED.value]


def test_job_heartbeat_extends_the_worker_lease(session: Session) -> None:
    create_pending_resource(session)
    claim_time = datetime.now(UTC) + timedelta(seconds=1)
    job = claim_jobs(session, worker_id="worker-heartbeat", now=claim_time)[0]
    heartbeat_time = claim_time + timedelta(seconds=10)

    updated = heartbeat_job_lease(
        session,
        worker_id="worker-heartbeat",
        job_id=job.id,
        now=heartbeat_time,
    )

    session.refresh(job)
    worker = session.get(Worker, "worker-heartbeat")
    assert updated is True
    assert job.heartbeat_at is not None and as_utc(job.heartbeat_at) == heartbeat_time
    assert worker is not None and as_utc(worker.heartbeat_at) == heartbeat_time


def test_stale_worker_cannot_commit_after_losing_its_lease(session: Session) -> None:
    create_pending_resource(session)
    claim_time = datetime.now(UTC) + timedelta(seconds=1)
    job = claim_jobs(session, worker_id="original-worker", now=claim_time)[0]
    job.claimed_by = "replacement-worker"
    session.commit()

    committed = mark_job_succeeded(
        session,
        job,
        worker_id="original-worker",
        now=claim_time + timedelta(seconds=10),
    )

    session.refresh(job)
    assert committed is False
    assert job.status == JobStatus.RUNNING.value
    assert job.claimed_by == "replacement-worker"


def test_transient_failures_retry_then_enter_dead_letter_state(session: Session) -> None:
    resource = create_pending_resource(session)
    first_attempt_at = datetime.now(UTC) + timedelta(seconds=1)

    with patch("app.worker.make_provisioner", return_value=AlwaysFailProvisioner()):
        assert asyncio.run(
            process_queued_jobs(session, limit=1, worker_id="retry-worker", now=first_attempt_at)
        ) == 1

        job = session.query(Job).filter_by(resource_id=resource.id).one()
        assert job.status == JobStatus.QUEUED.value
        assert job.attempts == 1
        assert as_utc(job.available_at) > first_attempt_at
        assert job.claimed_by is None

        second_attempt_at = as_utc(job.available_at) + timedelta(seconds=1)
        assert asyncio.run(
            process_queued_jobs(session, limit=1, worker_id="retry-worker", now=second_attempt_at)
        ) == 1
        session.refresh(job)
        assert job.status == JobStatus.QUEUED.value
        assert job.attempts == 2

        third_attempt_at = as_utc(job.available_at) + timedelta(seconds=1)
        assert asyncio.run(
            process_queued_jobs(session, limit=1, worker_id="retry-worker", now=third_attempt_at)
        ) == 1

    session.refresh(job)
    session.refresh(resource)
    event_types = [
        event.event_type
        for event in session.query(Event).filter_by(resource_id=resource.id).order_by(Event.id)
    ]

    assert job.status == JobStatus.DEAD.value
    assert job.attempts == job.max_attempts == 3
    assert job.finished_at is not None and as_utc(job.finished_at) == third_attempt_at
    assert resource.actual_state == "failed"
    assert event_types.count("job.retry_scheduled") == 2
    assert event_types[-2:] == ["job.dead", "resource.failed"]


def test_permanent_job_error_skips_retries(session: Session) -> None:
    resource = create_pending_resource(session)
    job = session.query(Job).filter_by(resource_id=resource.id).one()
    job.kind = "unknown_job_kind"
    session.commit()
    attempted_at = datetime.now(UTC) + timedelta(seconds=1)

    asyncio.run(
        process_queued_jobs(session, limit=1, worker_id="permanent-worker", now=attempted_at)
    )

    session.refresh(job)
    session.refresh(resource)
    assert job.status == JobStatus.DEAD.value
    assert job.attempts == 1
    assert "Unknown job kind" in (job.last_error or "")
    assert resource.actual_state == "failed"


def test_abandoned_job_is_recovered_after_lease_expiration(session: Session) -> None:
    resource = create_pending_resource(session)
    claim_time = datetime.now(UTC) + timedelta(seconds=1)
    job = claim_jobs(session, worker_id="crashed-worker", now=claim_time)[0]
    settings = get_settings()
    recovery_time = claim_time + timedelta(seconds=settings.job_lease_seconds + 1)

    recovered = recover_abandoned_jobs(session, now=recovery_time)

    session.refresh(job)
    crashed_worker = session.get(Worker, "crashed-worker")
    event_types = [
        event.event_type
        for event in session.query(Event).filter_by(resource_id=resource.id).order_by(Event.id)
    ]
    assert recovered == 1
    assert job.status == JobStatus.QUEUED.value
    assert job.claimed_by is None
    assert as_utc(job.available_at) > recovery_time
    assert crashed_worker is not None
    assert crashed_worker.status == WorkerStatus.STOPPED.value
    assert crashed_worker.current_job_id is None
    assert event_types[-1] == "job.recovered"


def test_retry_delay_is_exponential_capped_and_jittered() -> None:
    delays = [
        retry_delay_seconds(
            job_id=42,
            attempts=attempt,
            base_seconds=5,
            max_seconds=20,
        )
        for attempt in range(1, 6)
    ]

    assert 5 <= delays[0] <= 6
    assert 10 <= delays[1] <= 12
    assert delays[2:] == [20, 20, 20]


def test_settings_reject_a_lease_shorter_than_heartbeat_interval() -> None:
    with pytest.raises(ValueError, match="JOB_LEASE_SECONDS"):
        Settings(job_lease_seconds=10, worker_heartbeat_interval_seconds=10)
