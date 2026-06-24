from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Job, Resource


def test_post_resource_creates_resource_job_and_event(
    client: TestClient,
    session: Session,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/resources",
        json={"template_id": 1, "name": "Demo App"},
        headers=auth_headers,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["actual_state"] == "pending"
    assert body["desired_state"] == "running"
    assert body["slug"].startswith("demo-app-")

    resources = session.query(Resource).all()
    jobs = session.query(Job).all()
    events = session.query(Event).all()

    assert len(resources) == 1
    assert len(jobs) == 1
    assert len(events) == 1
    assert jobs[0].kind == "provision_resource"
    assert jobs[0].status == "queued"
    assert events[0].event_type == "resource.created"


def test_list_resource_events_returns_lifecycle_events(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        "/resources",
        json={"template_id": 1, "name": "Demo App"},
        headers=auth_headers,
    ).json()

    response = client.get(f"/resources/{created['id']}/events", headers=auth_headers)

    assert response.status_code == 200
    events = response.json()
    assert [event["event_type"] for event in events] == ["resource.created"]


def test_user_cannot_view_another_users_resource(
    client: TestClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    created = client.post(
        "/resources",
        json={"template_id": 1, "name": "Private Demo"},
        headers=auth_headers,
    ).json()

    response = client.get(f"/resources/{created['id']}", headers=other_auth_headers)

    assert response.status_code == 404


def test_resources_require_authentication(client: TestClient) -> None:
    response = client.post("/resources", json={"template_id": 1, "name": "Demo App"})

    assert response.status_code == 401
