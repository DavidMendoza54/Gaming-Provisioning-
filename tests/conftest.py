from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import create_app
from app.models import Template, User
from app.schemas import RegisterRequest
from app.services.auth import issue_token, register_user
from app.settings import get_settings


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with TestingSessionLocal() as test_session:
        template = Template(
            name="Tiny Python HTTP App",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            default_cpu=1,
            default_memory_mb=128,
            description="A safe starter app that returns a small HTTP response.",
            enabled=True,
        )
        test_session.add(template)
        test_session.commit()
        yield test_session


@pytest.fixture()
def client(session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None, None, None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def user(session: Session) -> User:
    return register_user(
        session,
        RegisterRequest(email="dev@example.local", password="correct-horse-battery"),
    )


@pytest.fixture()
def auth_headers(session: Session, user: User) -> dict[str, str]:
    issued = issue_token(session, user, name="test")
    return {"Authorization": f"Bearer {issued.raw_token}"}


@pytest.fixture()
def other_user(session: Session) -> User:
    return register_user(
        session,
        RegisterRequest(email="friend@example.local", password="correct-horse-battery"),
    )


@pytest.fixture()
def other_auth_headers(session: Session, other_user: User) -> dict[str, str]:
    issued = issue_token(session, other_user, name="test")
    return {"Authorization": f"Bearer {issued.raw_token}"}
