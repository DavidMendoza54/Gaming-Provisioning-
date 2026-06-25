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

