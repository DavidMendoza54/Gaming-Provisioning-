# Glossary

## API

The HTTP interface users or tools call. In this project, FastAPI serves the API.

## AuthN

Authentication. Proving who someone is.

Example: login with email and password.

## AuthZ

Authorization. Deciding what someone can access.

Example: user A cannot read user B's resource.

## Bearer Token

A secret string sent with requests.

```text
Authorization: Bearer <token>
```

Whoever has the token can act as that user until it expires or is revoked.

## Control Plane

The decision-making layer. It records desired state and schedules work.

In this project: API plus Postgres.

## Data Plane

The workload-running layer.

In this project: fake resources first, Docker containers later.

## Desired State

What the platform wants.

Example: `desired_state = running`.

## Actual State

What is currently true or currently happening.

Example: `actual_state = provisioning`.

## Event

An audit/debug record explaining something that happened.

## External ID

The identifier assigned by the real backend.

For Docker, this is the container ID.

## Idempotency

The property that repeating an operation is safe.

Example: deleting a resource twice should not create duplicate delete jobs.

## Image

A static Docker template used to create containers.

## Container

A running or stopped instance created from a Docker image.

## Expose Port

Document that an app listens on a port inside the container.

## Publish Port

Bind a container port to a public or host port.

This project avoids publishing user container ports directly.

## Reverse Proxy

A server that receives public traffic and forwards it to the correct internal service.

In this project: Traefik.

## Wildcard DNS

A DNS rule where many subdomains point to the same server.

Example:

```text
*.apps.example.com -> VPS IP
```

## Migration

A versioned database schema change.

In this project: Alembic migrations create tables.

## Seed

Initial data required for the app to work.

In this project: the tiny Python HTTP app template.

## Queue

A place to store work that should happen later.

In this project, jobs are currently database rows.

## Worker

A background process that processes queued jobs.

## Lease

A time-limited claim on a job. The owning worker renews the lease with heartbeats so another worker can recover the job if the owner disappears.

## Exponential Backoff

A retry policy that increases the wait after each failure. It prevents a dependency outage from causing a tight retry loop.

## Dead-Letter Job

A job that exhausted its allowed attempts or hit a permanent error. It remains stored for inspection instead of being silently discarded.

## Fencing

A final ownership check that prevents an old worker from committing after its lease was transferred to another worker.

## Provisioning

Creating or preparing a resource.

Example: creating a Docker container for a user.

## Quota

A limit that prevents one user from consuming too many resources.

## TTL

Time to live. How long something should exist before it expires.

## Smoke Test

An end-to-end test that proves the main system flow works.

It does not test every detail. It proves the system is alive and wired together.

## Observability

The ability to understand a system's internal behavior from the signals it produces, especially logs, metrics, and traces.

## Structured Log

A log event represented as predictable fields instead of an unstructured sentence. TinyProvisioner emits one JSON object per application log line.

## Metric

A numeric measurement collected over time. Counters increase, gauges move up and down, and histograms group observations into buckets.

## Trace

A representation of one operation as it crosses services and nested spans. Request IDs provide correlation but are not a complete distributed trace.

## Prometheus

A monitoring system that periodically scrapes metric endpoints, stores time series, evaluates PromQL queries, and runs alert rules.

## Scrape

One Prometheus request to a target's metrics endpoint. The built-in `up` metric records whether the scrape succeeded.

## Label Cardinality

The number of unique label combinations stored for a metric. IDs, emails, and raw URLs create unbounded cardinality and should remain log fields rather than metric labels.

## RED Metrics

Rate, errors, and duration. These signals summarize the user-visible behavior of a request-serving service.

## SLI

Service-level indicator. A measured reliability signal, such as the ratio of successful requests.

## SLO

Service-level objective. A target for an SLI over a time window, such as 99.5% API availability over 30 days.

## Alertmanager

The Prometheus component that groups, deduplicates, routes, and silences alerts after Prometheus decides that an alert condition is active.
