from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter, time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, make_asgi_app
from prometheus_client import start_http_server as prometheus_start_http_server


REQUEST_ID_HEADER = "X-Request-ID"
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

LOG_FIELDS = (
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "worker_id",
    "job_id",
    "job_kind",
    "resource_id",
    "attempt",
    "result",
    "retry_in_seconds",
    "recovered_jobs",
    "queued_cleanup",
    "processed_jobs",
    "metrics_port",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    """Turn application log records into one machine-readable JSON object per line."""

    def __init__(self, *, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "event": record.getMessage(),
        }
        context_request_id = request_id_context.get()
        if context_request_id is not None and not hasattr(record, "request_id"):
            payload["request_id"] = context_request_id

        for field in LOG_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(*, service: str, level: str) -> logging.Logger:
    """Configure the TinyProvisioner logger without changing third-party loggers."""

    logger = logging.getLogger("tinyprovisioner")
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    return logging.getLogger(f"tinyprovisioner.{service}")


API_REGISTRY = CollectorRegistry(auto_describe=True)
API_HTTP_REQUESTS_TOTAL = Counter(
    "tinyprovisioner_http_requests_total",
    "HTTP requests completed by the API.",
    labelnames=("method", "route", "status_code"),
    registry=API_REGISTRY,
)
API_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "tinyprovisioner_http_request_duration_seconds",
    "Time spent serving API requests in seconds.",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=API_REGISTRY,
)
API_HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "tinyprovisioner_http_requests_in_progress",
    "API requests currently being served.",
    labelnames=("method",),
    registry=API_REGISTRY,
)

WORKER_REGISTRY = CollectorRegistry(auto_describe=True)
WORKER_JOB_CLAIMS_TOTAL = Counter(
    "tinyprovisioner_worker_job_claims_total",
    "Jobs atomically claimed by this worker process.",
    labelnames=("kind",),
    registry=WORKER_REGISTRY,
)
WORKER_JOB_RESULTS_TOTAL = Counter(
    "tinyprovisioner_worker_job_results_total",
    "Final result of each job attempt observed by this worker process.",
    labelnames=("kind", "result"),
    registry=WORKER_REGISTRY,
)
WORKER_JOB_DURATION_SECONDS = Histogram(
    "tinyprovisioner_worker_job_duration_seconds",
    "Time spent processing one claimed job attempt in seconds.",
    labelnames=("kind", "result"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    registry=WORKER_REGISTRY,
)
WORKER_QUEUE_DEPTH = Gauge(
    "tinyprovisioner_worker_queue_depth",
    "Jobs currently stored in each durable queue state.",
    labelnames=("status",),
    registry=WORKER_REGISTRY,
)
WORKER_LAST_SUCCESSFUL_LOOP_TIMESTAMP_SECONDS = Gauge(
    "tinyprovisioner_worker_last_successful_loop_timestamp_seconds",
    "Unix timestamp of the worker's last successful polling loop.",
    registry=WORKER_REGISTRY,
)
WORKER_LOOP_DURATION_SECONDS = Histogram(
    "tinyprovisioner_worker_loop_duration_seconds",
    "Time spent in one worker polling loop in seconds.",
    labelnames=("result",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=WORKER_REGISTRY,
)
WORKER_RECOVERED_JOBS_TOTAL = Counter(
    "tinyprovisioner_worker_recovered_jobs_total",
    "Expired job leases recovered by outcome.",
    labelnames=("outcome",),
    registry=WORKER_REGISTRY,
)

for queue_status in ("queued", "running", "succeeded", "cancelled", "dead"):
    WORKER_QUEUE_DEPTH.labels(status=queue_status).set(0)


def _select_request_id(candidate: str | None) -> str:
    if candidate is not None and SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid4().hex


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def install_api_observability(app: FastAPI, *, logger: logging.Logger) -> None:
    """Install request correlation, RED metrics, and the Prometheus scrape endpoint."""

    metrics_app = make_asgi_app(registry=API_REGISTRY)
    app.mount("/metrics", metrics_app)

    @app.middleware("http")
    async def observe_request(request: Request, call_next: Any) -> Response:
        if request.url.path.startswith("/metrics"):
            return await call_next(request)

        method = request.method
        request_id = _select_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_context.set(request_id)
        status_code = 500
        started_at = perf_counter()
        raised_exception = False
        API_HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception as exc:
            raised_exception = True
            logger.exception(
                "http.request.failed",
                extra={
                    "method": method,
                    "route": _route_template(request),
                    "status_code": status_code,
                    "error_type": type(exc).__name__,
                },
            )
            raise
        finally:
            duration_seconds = perf_counter() - started_at
            route = _route_template(request)
            API_HTTP_REQUESTS_TOTAL.labels(
                method=method,
                route=route,
                status_code=str(status_code),
            ).inc()
            API_HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(
                duration_seconds
            )
            API_HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
            if not raised_exception:
                log_method = logger.error if status_code >= 500 else logger.info
                log_method(
                    "http.request.completed",
                    extra={
                        "method": method,
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": round(duration_seconds * 1000, 3),
                    },
                )
            request_id_context.reset(token)


def start_worker_metrics_server(*, port: int) -> Any:
    """Expose the worker registry on an internal HTTP server for Prometheus."""

    return prometheus_start_http_server(port, addr="0.0.0.0", registry=WORKER_REGISTRY)


def record_worker_job_claim(*, kind: str) -> None:
    WORKER_JOB_CLAIMS_TOTAL.labels(kind=kind).inc()


def record_worker_job_result(*, kind: str, result: str, duration_seconds: float | None) -> None:
    WORKER_JOB_RESULTS_TOTAL.labels(kind=kind, result=result).inc()
    if duration_seconds is not None:
        WORKER_JOB_DURATION_SECONDS.labels(kind=kind, result=result).observe(duration_seconds)


def record_worker_recovery(*, outcome: str) -> None:
    WORKER_RECOVERED_JOBS_TOTAL.labels(outcome=outcome).inc()


def set_worker_queue_depth(counts: dict[str, int]) -> None:
    for status in ("queued", "running", "succeeded", "cancelled", "dead"):
        WORKER_QUEUE_DEPTH.labels(status=status).set(counts.get(status, 0))


def record_worker_loop(*, result: str, duration_seconds: float) -> None:
    WORKER_LOOP_DURATION_SECONDS.labels(result=result).observe(duration_seconds)
    if result == "success":
        WORKER_LAST_SUCCESSFUL_LOOP_TIMESTAMP_SECONDS.set(time())
