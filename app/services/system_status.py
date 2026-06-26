from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.settings import get_settings


@dataclass(frozen=True)
class SystemCheck:
    name: str
    status: str
    detail: str


def collect_system_status(session: Session) -> list[dict[str, str]]:
    checks = [
        SystemCheck(name="API", status="ok", detail="FastAPI is answering requests."),
        _check_database(session),
        _check_redis(),
    ]
    checks.extend(_check_docker_stack())
    return [asdict(check) for check in checks]


def _check_database(session: Session) -> SystemCheck:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        return SystemCheck(name="Database", status="error", detail=f"Database query failed: {exc}")
    return SystemCheck(name="Database", status="ok", detail="Database answered a test query.")


def _check_redis() -> SystemCheck:
    settings = get_settings()
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:
        return SystemCheck(name="Redis", status="error", detail=f"Redis ping failed: {exc}")
    return SystemCheck(name="Redis", status="ok", detail="Redis answered a ping.")


def _check_docker_stack() -> list[SystemCheck]:
    try:
        import docker

        client = docker.from_env()
        try:
            client.ping()
            return [
                SystemCheck(name="Docker", status="ok", detail="Docker Engine is reachable."),
                _check_compose_service(client, name="Worker", service="worker"),
                _check_compose_service(client, name="Traefik", service="traefik"),
            ]
        finally:
            client.close()
    except Exception as exc:
        detail = f"Docker Engine check failed: {exc}"
        return [
            SystemCheck(name="Docker", status="error", detail=detail),
            SystemCheck(name="Worker", status="warning", detail="Worker status needs Docker access."),
            SystemCheck(name="Traefik", status="warning", detail="Traefik status needs Docker access."),
        ]


def _check_compose_service(client: Any, *, name: str, service: str) -> SystemCheck:
    containers = client.containers.list(
        all=True,
        filters={"label": f"com.docker.compose.service={service}"},
    )
    if not containers:
        return SystemCheck(name=name, status="warning", detail="No Compose container was found.")

    if any(getattr(container, "status", None) == "running" for container in containers):
        return SystemCheck(name=name, status="ok", detail="Compose container is running.")

    statuses = ", ".join(str(getattr(container, "status", "unknown")) for container in containers)
    return SystemCheck(name=name, status="error", detail=f"Container exists but is not running: {statuses}.")
