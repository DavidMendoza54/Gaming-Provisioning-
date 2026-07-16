from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Worker
from app.services.system_status import _check_worker_heartbeat


def test_system_status_requires_authentication(client: TestClient) -> None:
    response = client.get("/system/status")

    assert response.status_code == 401


def test_system_status_returns_learning_checks(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/system/status", headers=auth_headers)

    assert response.status_code == 200
    checks = response.json()
    names = {check["name"] for check in checks}

    assert {"API", "Database", "Redis", "Docker", "Worker", "Traefik"} <= names
    assert next(check for check in checks if check["name"] == "API")["status"] == "ok"
    assert next(check for check in checks if check["name"] == "Database")["status"] == "ok"


def test_worker_status_uses_database_heartbeat(session: Session) -> None:
    heartbeat_at = datetime.now(UTC)
    session.add(
        Worker(
            id="status-worker",
            hostname="test-host",
            process_id=123,
            heartbeat_at=heartbeat_at,
            started_at=heartbeat_at,
        )
    )
    session.commit()

    healthy = _check_worker_heartbeat(session, now=heartbeat_at + timedelta(seconds=5))
    stale = _check_worker_heartbeat(session, now=heartbeat_at + timedelta(minutes=2))

    assert healthy.status == "ok"
    assert "idle" in healthy.detail
    assert stale.status == "error"
    assert "stale" in stale.detail
