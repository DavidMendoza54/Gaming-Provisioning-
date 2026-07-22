import io
import json
import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, Resource, Template, User
from app.observability import (
    JsonFormatter,
    WORKER_REGISTRY,
    record_worker_job_result,
    request_id_context,
)
from app.state import ActualState, DesiredState, JobStatus
from app.worker import observe_queue_depth


def metric_samples(metrics_text: str, sample_name: str):
    return [
        sample
        for family in text_string_to_metric_families(metrics_text)
        for sample in family.samples
        if sample.name == sample_name
    ]


def test_api_returns_request_id_and_exposes_red_metrics(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "lesson-request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "lesson-request-123"

    metrics_response = client.get("/metrics/")
    samples = metric_samples(
        metrics_response.text,
        "tinyprovisioner_http_requests_total",
    )

    assert metrics_response.status_code == 200
    assert any(
        sample.labels
        == {
            "method": "GET",
            "route": "/health",
            "status_code": "200",
        }
        and sample.value >= 1
        for sample in samples
    )
    assert "tinyprovisioner_http_request_duration_seconds_bucket" in metrics_response.text


def test_api_replaces_unsafe_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "unsafe request id"})

    generated_request_id = response.headers["X-Request-ID"]
    assert generated_request_id != "unsafe request id"
    assert re.fullmatch(r"[0-9a-f]{32}", generated_request_id)


def test_metrics_use_route_template_instead_of_resource_id(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/resources/987654", headers=auth_headers)
    metrics_text = client.get("/metrics/").text
    samples = metric_samples(metrics_text, "tinyprovisioner_http_requests_total")

    assert response.status_code == 404
    matching_samples = [
        sample
        for sample in samples
        if sample.labels.get("route") == "/resources/{resource_id}"
        and sample.labels.get("status_code") == "404"
    ]
    assert matching_samples
    assert all(sample.labels.get("route") != "/resources/987654" for sample in samples)


def test_json_formatter_includes_correlation_and_job_context() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(service="worker"))
    logger = logging.getLogger("test.observability.json")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    token = request_id_context.set("request-abc")
    try:
        logger.info(
            "worker.job.completed",
            extra={
                "job_id": 42,
                "job_kind": "provision_resource",
                "result": "succeeded",
            },
        )
    finally:
        request_id_context.reset(token)

    payload = json.loads(stream.getvalue())
    assert payload["service"] == "worker"
    assert payload["event"] == "worker.job.completed"
    assert payload["request_id"] == "request-abc"
    assert payload["job_id"] == 42
    assert payload["result"] == "succeeded"


def test_worker_queue_depth_and_result_metrics(session: Session) -> None:
    template = session.scalar(select(Template))
    assert template is not None
    user = User(email="metrics@example.local", role="user")
    session.add(user)
    session.flush()
    resource = Resource(
        user_id=user.id,
        template_id=template.id,
        slug="metrics-resource",
        desired_state=DesiredState.RUNNING.value,
        actual_state=ActualState.PENDING.value,
        cpu_limit=1,
        memory_mb=128,
    )
    session.add(resource)
    session.flush()
    session.add(
        Job(
            resource_id=resource.id,
            kind="provision_resource",
            status=JobStatus.QUEUED.value,
            max_attempts=3,
        )
    )
    session.commit()

    counts = observe_queue_depth(session)
    record_worker_job_result(
        kind="provision_resource",
        result="succeeded",
        duration_seconds=0.25,
    )
    metrics_text = generate_latest(WORKER_REGISTRY).decode()

    assert counts["queued"] == 1
    queue_samples = metric_samples(metrics_text, "tinyprovisioner_worker_queue_depth")
    assert any(
        sample.labels == {"status": "queued"} and sample.value == 1
        for sample in queue_samples
    )
    result_samples = metric_samples(
        metrics_text,
        "tinyprovisioner_worker_job_results_total",
    )
    assert any(
        sample.labels == {"kind": "provision_resource", "result": "succeeded"}
        and sample.value >= 1
        for sample in result_samples
    )


def test_observability_configuration_contract() -> None:
    prometheus = Path("observability/prometheus/prometheus.yml").read_text()
    alerts = Path("observability/prometheus/alerts.yml").read_text()
    datasource = Path(
        "observability/grafana/provisioning/datasources/prometheus.yml"
    ).read_text()
    dashboard = json.loads(
        Path("observability/grafana/dashboards/tinyprovisioner-overview.json").read_text()
    )

    assert "api:8000" in prometheus
    assert "worker:9101" in prometheus
    assert "alertmanager:9093" in prometheus
    assert "TinyProvisionerApiDown" in alerts
    assert "TinyProvisionerWorkerLoopStale" in alerts
    assert "TinyProvisionerHighApiErrorRatio" in alerts
    assert "clamp_min" not in alerts
    assert "TinyProvisionerQueueBacklog" in alerts
    assert "TinyProvisionerDeadLetterJob" in alerts
    assert "uid: tinyprovisioner-prometheus" in datasource
    assert dashboard["uid"] == "tinyprovisioner-overview"
    assert "clamp_min" not in json.dumps(dashboard)
    assert len(dashboard["panels"]) >= 8
    assert all(
        target["datasource"]["uid"] == "tinyprovisioner-prometheus"
        for target in dashboard["panels"]
    )
