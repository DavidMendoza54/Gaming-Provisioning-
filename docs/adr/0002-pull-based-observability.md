# ADR 0002: Pull-Based Metrics and Version-Controlled Dashboards

- Status: Accepted
- Date: 2026-07-21

## Context

TinyProvisioner has two independent application processes: an HTTP API and a durable job worker. Operators need to distinguish request failures, queue problems, worker stalls, and complete process loss.

A dashboard alone cannot create observability. The application first needs a stable signal contract, and that contract must avoid unbounded Prometheus label cardinality.

## Decision

TinyProvisioner will:

1. Emit structured JSON application logs to stdout.
2. Correlate API requests with a validated or generated `X-Request-ID`.
3. Expose API RED metrics through `/metrics/`.
4. Expose worker metrics from a separate internal server on port `9101`.
5. Use Prometheus to pull metrics from both targets every five seconds.
6. Provision the Grafana datasource and dashboard from version-controlled files.
7. Evaluate symptom-based alert rules in Prometheus and group them in Alertmanager.
8. Keep high-cardinality identifiers in logs, never metric labels.

Allowed application metric labels are bounded dimensions such as route templates, HTTP status codes, job kinds, job results, and queue states.

## Why Pull Instead of Application Pushes

Prometheus's pull model produces the built-in `up` signal. If the API or worker disappears, Prometheus observes the failed scrape. A process that must push its own health could disappear before reporting that it is down.

The worker exposes metrics separately because it is a separate failure domain. Publishing worker values through the API would make a healthy API appear to prove worker health even when the worker process was gone.

## Why Dashboards as Files

Provisioned dashboard files are reviewable, reproducible, and recoverable. Manual UI configuration would create hidden state that cannot be reliably recreated in CI or a new environment.

## Consequences

Positive:

- API and worker failures can be distinguished.
- Request and queue behavior can be aggregated over time.
- Monitoring configuration follows the same pull-request workflow as code.
- Metric storage cost stays bounded by controlled label sets.
- Failure labs can prove that alerts respond to real symptoms.

Negative:

- Prometheus, Grafana, and Alertmanager add memory, storage, and operational complexity.
- Container stdout logs are not centrally searchable after removal or host loss.
- The current request ID is correlation metadata, not a distributed trace.
- A single local Prometheus instance is not highly available.

## Alternatives Considered

### Publish every identifier as a Prometheus label

Rejected because request, resource, job, and user identifiers create unbounded time-series cardinality.

### Let the API report worker metrics

Rejected because it hides the worker process boundary and weakens target-down detection.

### Configure Grafana manually

Rejected because click-created dashboards are difficult to review, reproduce, and recover.

### Add a full OpenTelemetry, Tempo, and Loki stack immediately

Deferred. Metrics and structured logs provide the most useful first operational slice. Traces and centralized log shipping can be added without invalidating this signal contract.
