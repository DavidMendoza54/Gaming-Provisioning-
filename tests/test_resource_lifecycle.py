import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Job, Resource
from app.worker import process_queued_jobs


def create_running_resource(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> Resource:
    created = client.post(
        "/resources",
        json={"template_id": 1, "name": "Lifecycle Demo"},
        headers=auth_headers,
    ).json()
    asyncio.run(process_queued_jobs(session))
    resource = session.get(Resource, created["id"])
    assert resource is not None
    assert resource.actual_state == "running"
    return resource


def test_stop_then_start_resource_lifecycle(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> None:
    resource = create_running_resource(client, session, auth_headers)

    stop_response = client.post(f"/resources/{resource.id}/stop", headers=auth_headers)
    session.refresh(resource)

    assert stop_response.status_code == 202
    assert stop_response.json()["actual_state"] == "stopping"
    assert resource.desired_state == "stopped"
    assert resource.actual_state == "stopping"

    asyncio.run(process_queued_jobs(session))
    session.refresh(resource)
    stop_job = session.query(Job).filter_by(resource_id=resource.id, kind="stop_resource").one()

    assert resource.desired_state == "stopped"
    assert resource.actual_state == "stopped"
    assert stop_job.status == "succeeded"

    start_response = client.post(f"/resources/{resource.id}/start", headers=auth_headers)
    session.refresh(resource)

    assert start_response.status_code == 202
    assert start_response.json()["actual_state"] == "starting"
    assert resource.desired_state == "running"
    assert resource.actual_state == "starting"

    asyncio.run(process_queued_jobs(session))
    session.refresh(resource)
    event_types = [
        event.event_type
        for event in session.query(Event).filter_by(resource_id=resource.id).order_by(Event.id).all()
    ]

    assert resource.desired_state == "running"
    assert resource.actual_state == "running"
    assert "resource.stop_queued" in event_types
    assert "resource.stopped" in event_types
    assert "resource.start_queued" in event_types
    assert event_types[-1] == "resource.running"


def test_delete_is_idempotent_and_finishes_deleted(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> None:
    resource = create_running_resource(client, session, auth_headers)

    first = client.delete(f"/resources/{resource.id}", headers=auth_headers)
    second = client.delete(f"/resources/{resource.id}", headers=auth_headers)
    session.refresh(resource)

    delete_jobs = session.query(Job).filter_by(resource_id=resource.id, kind="delete_resource").all()

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["actual_state"] == "deleting"
    assert second.json()["actual_state"] == "deleting"
    assert len(delete_jobs) == 1
    assert resource.desired_state == "deleted"
    assert resource.actual_state == "deleting"

    asyncio.run(process_queued_jobs(session))
    session.refresh(resource)

    assert resource.desired_state == "deleted"
    assert resource.actual_state == "deleted"
    assert resource.deleted_at is not None
    assert resource.url is None


def test_delete_cancels_pending_provision_job(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        "/resources",
        json={"template_id": 1, "name": "Pending Delete"},
        headers=auth_headers,
    ).json()

    response = client.delete(f"/resources/{created['id']}", headers=auth_headers)
    resource = session.get(Resource, created["id"])
    jobs = session.query(Job).filter_by(resource_id=created["id"]).order_by(Job.id).all()

    assert resource is not None
    assert response.status_code == 202
    assert resource.actual_state == "deleting"
    assert [(job.kind, job.status) for job in jobs] == [
        ("provision_resource", "cancelled"),
        ("delete_resource", "queued"),
    ]

    asyncio.run(process_queued_jobs(session))
    session.refresh(resource)

    assert resource.actual_state == "deleted"
    assert resource.external_id is None


def test_start_pending_resource_returns_conflict(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        "/resources",
        json={"template_id": 1, "name": "Too Soon"},
        headers=auth_headers,
    ).json()

    response = client.post(f"/resources/{created['id']}/start", headers=auth_headers)

    assert response.status_code == 409


def test_logs_endpoint_returns_resource_logs(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> None:
    resource = create_running_resource(client, session, auth_headers)

    response = client.get(f"/resources/{resource.id}/logs", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["resource_id"] == resource.id
    assert response.json()["external_id"] == resource.external_id
    assert "logs" in response.json()
