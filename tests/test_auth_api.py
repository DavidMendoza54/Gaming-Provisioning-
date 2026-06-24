from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ApiToken, User
from app.services.auth import verify_password


def test_register_creates_user_and_returns_bearer_token(
    client: TestClient,
    session: Session,
) -> None:
    response = client.post(
        "/auth/register",
        json={"email": "Learner@Example.Local", "password": "correct-horse-battery"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "learner@example.local"

    user = session.query(User).filter_by(email="learner@example.local").one()
    token = session.query(ApiToken).filter_by(user_id=user.id).one()

    assert user.password_hash != "correct-horse-battery"
    assert verify_password("correct-horse-battery", user.password_hash)
    assert token.token_hash != body["access_token"]


def test_login_rejects_wrong_password(client: TestClient, user: User) -> None:
    response = client.post(
        "/auth/login",
        json={"email": user.email, "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_me_requires_valid_bearer_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    missing = client.get("/me")
    valid = client.get("/me", headers=auth_headers)

    assert missing.status_code == 401
    assert valid.status_code == 200
    assert valid.json()["email"] == "dev@example.local"
