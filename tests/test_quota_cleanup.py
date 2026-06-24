from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Job, Resource
from app.services.resources import queue_expired_resources_for_cleanup
from app.settings import get_settings


def test_created_resource_gets_default_expiration(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/resources",
        json={"template_id": 1, "name": "Expiring Demo"},
        headers=auth_headers,
    )

    resource = session.get(Resource, response.json()["id"])
    assert resource is not None
    assert resource.expires_at is not None


def test_resource_quota_blocks_excess_active_resources(
    monkeypatch,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    monkeypatch.setenv("MAX_ACTIVE_RESOURCES_PER_USER", "1")
    get_settings.cache_clear()

    first = client.post(
        "/resources",
        json={"template_id": 1, "name": "Allowed Demo"},
        headers=auth_headers,
    )
    second = client.post(
        "/resources",
        json={"template_id": 1, "name": "Blocked Demo"},
        headers=auth_headers,
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert "quota" in second.json()["detail"].lower()


def test_expired_cleanup_queues_delete_once(session: Session, client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/resources",
        json={"template_id": 1, "name": "Expired Demo"},
        headers=auth_headers,
    ).json()
    resource = session.get(Resource, created["id"])
    assert resource is not None
    resource.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.commit()

    first_count = queue_expired_resources_for_cleanup(session)
    second_count = queue_expired_resources_for_cleanup(session)
    session.refresh(resource)

    delete_jobs = session.query(Job).filter_by(resource_id=resource.id, kind="delete_resource").all()
    event_types = [
        event.event_type
        for event in session.query(Event).filter_by(resource_id=resource.id).order_by(Event.id).all()
    ]

    assert first_count == 1
    assert second_count == 0
    assert len(delete_jobs) == 1
    assert resource.desired_state == "deleted"
    assert resource.actual_state == "deleting"
    assert "resource.expired" in event_types
