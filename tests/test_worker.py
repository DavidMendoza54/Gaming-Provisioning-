import asyncio

from sqlalchemy.orm import Session

from app.models import Event, Job, User
from app.schemas import ResourceCreate
from app.services.resources import create_resource
from app.worker import process_queued_jobs


def test_worker_moves_resource_from_pending_to_running(session: Session) -> None:
    user = User(email="worker@example.local", role="user")
    session.add(user)
    session.commit()
    session.refresh(user)

    resource = create_resource(
        session,
        user,
        ResourceCreate(template_id=1, name="Demo Worker App"),
    )

    processed = asyncio.run(process_queued_jobs(session))

    session.refresh(resource)
    job = session.query(Job).filter_by(resource_id=resource.id).one()
    event_types = [
        event.event_type
        for event in session.query(Event).filter_by(resource_id=resource.id).order_by(Event.id).all()
    ]

    assert processed == 1
    assert resource.actual_state == "running"
    assert resource.external_id == f"fake-{resource.id}"
    assert resource.url == f"http://{resource.slug}.apps.localhost"
    assert job.status == "succeeded"
    assert job.attempts == 1
    assert event_types == [
        "resource.created",
        "resource.provisioning",
        "resource.running",
    ]
