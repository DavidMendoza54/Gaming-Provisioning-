from fastapi.testclient import TestClient

from app.main import create_app


def test_control_panel_is_served_at_root() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "TinyProvisioner Control Panel" in response.text
    assert "/auth/login" in response.text
    assert "/resources" in response.text
