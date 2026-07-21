from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Worker
from app.settings import get_settings
from app.state import WorkerStatus


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
        _check_worker_heartbeat(session),
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


def _check_worker_heartbeat(session: Session, *, now: datetime | None = None) -> SystemCheck:
    settings = get_settings()
    try:
        worker = session.scalar(
            select(Worker)
            .where(Worker.status == WorkerStatus.RUNNING.value)
            .order_by(Worker.heartbeat_at.desc())
            .limit(1)
        )
        if worker is None:
            worker = session.scalar(select(Worker).order_by(Worker.heartbeat_at.desc()).limit(1))
    except Exception as exc:
        return SystemCheck(
            name="Worker",
            status="error",
            detail=f"Worker heartbeat query failed: {exc}",
        )
    if worker is None:
        return SystemCheck(
            name="Worker",
            status="warning",
            detail="No worker heartbeat has been recorded yet.",
        )

    checked_at = now or datetime.now(UTC)
    heartbeat_at = worker.heartbeat_at
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    age_seconds = max(0, int((checked_at - heartbeat_at).total_seconds()))

    if worker.status != WorkerStatus.RUNNING.value:
        return SystemCheck(
            name="Worker",
            status="warning",
            detail=f"Latest worker {worker.id} reported {worker.status} {age_seconds}s ago.",
        )
    if age_seconds > settings.worker_stale_after_seconds:
        return SystemCheck(
            name="Worker",
            status="error",
            detail=f"Latest worker heartbeat is stale ({age_seconds}s old).",
        )

    activity = f"processing job {worker.current_job_id}" if worker.current_job_id else "idle"
    return SystemCheck(
        name="Worker",
        status="ok",
        detail=f"Worker {worker.id} is {activity}; heartbeat age is {age_seconds}s.",
    )


def _check_docker_stack() -> list[SystemCheck]:
    try:
        import docker

        client = docker.from_env()
        try:
            client.ping()
            return [
                SystemCheck(name="Docker", status="ok", detail="Docker Engine is reachable."),
                _check_compose_service(client, name="Traefik", service="traefik"),
            ]
        finally:
            client.close()
    except Exception as exc:
        detail = f"Docker Engine check failed: {exc}"
        return [
            SystemCheck(name="Docker", status="error", detail=detail),
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
