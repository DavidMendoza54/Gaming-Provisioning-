from fastapi.testclient import TestClient


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
