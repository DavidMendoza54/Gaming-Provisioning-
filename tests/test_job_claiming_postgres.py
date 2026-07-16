from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Job, Resource, Template, User
from app.state import JobStatus
from app.worker import claim_jobs


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL concurrency tests",
)


@pytest.mark.parametrize("jobs_for_resource", [1, 2])
def test_two_postgres_workers_claim_at_most_one_job_per_resource(
    jobs_for_resource: int,
) -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_size=4)
    session_factory = sessionmaker(bind=engine)

    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())

    with Session(engine) as session:
        user = User(email="postgres-worker@example.local", role="user")
        template = Template(
            name="Postgres Claim Test",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            default_cpu=1,
            default_memory_mb=128,
            description="Concurrency test template",
            enabled=True,
        )
        session.add_all([user, template])
        session.flush()
        resource = Resource(user_id=user.id, template_id=template.id, slug="postgres-claim-test")
        session.add(resource)
        session.flush()
        jobs = [
            Job(resource_id=resource.id, kind=f"test_job_{number}")
            for number in range(jobs_for_resource)
        ]
        session.add_all(jobs)
        session.commit()
        job_ids = [job.id for job in jobs]

    barrier = Barrier(2)

    def claim(worker_id: str) -> list[int]:
        with session_factory() as session:
            barrier.wait()
            return [job.id for job in claim_jobs(session, worker_id=worker_id, limit=1)]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["postgres-worker-a", "postgres-worker-b"]))

    claimed_ids = [claimed_id for result in results for claimed_id in result]
    assert len(claimed_ids) == 1
    assert claimed_ids[0] in job_ids

    with Session(engine) as session:
        claimed_job = session.get(Job, claimed_ids[0])
        assert claimed_job is not None
        assert claimed_job.status == JobStatus.RUNNING.value
        assert claimed_job.attempts == 1
        assert claimed_job.claimed_by in {"postgres-worker-a", "postgres-worker-b"}
        statuses = session.query(Job.status).filter(Job.id.in_(job_ids)).all()
        assert sum(status == JobStatus.RUNNING.value for (status,) in statuses) == 1

    engine.dispose()
