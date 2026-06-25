# TinyProvisioner

TinyProvisioner is a learning-first compute provisioning service. The first version models a real provider's shape without the dangerous parts: a FastAPI control plane stores desired state, a worker processes provisioning jobs, and a fake provisioner lets us practice lifecycle logic before touching Docker.

## Current Slice

- FastAPI app skeleton.
- PostgreSQL data model for users, templates, resources, jobs, and events.
- Alembic migration for the first schema.
- Database-backed worker loop.
- Fake provisioner for safe practice.
- Register/login flow with hashed passwords and bearer tokens.
- Fake provisioner by default, with a Docker provisioner ready behind `PROVISIONER_BACKEND=docker`.
- Resource quotas and default expiration for cost/capacity safety.
- Local Docker Compose for API, worker, Postgres, and Redis.
- Tiny Python HTTP app template for the first real Docker milestone.

## Learning Checkpoint

Before changing this code, answer these out loud:

- What is the control plane responsible for?
- What is the data plane responsible for?
- Why does provisioning run in a worker?
- What should happen if the worker crashes halfway through a job?

For a structured study path, start with:

- [Study Guide](docs/STUDY_GUIDE.md)
- [Guided Code Walkthrough](docs/CODE_WALKTHROUGH.md)
- [Glossary](docs/GLOSSARY.md)
- [Flashcards And Labs](docs/FLASHCARDS_AND_LABS.md)

## Local Setup

Copy the environment file:

```powershell
Copy-Item .env.example .env
```

Start the local services with the safe fake provisioner:

```powershell
docker compose up --build
```

In another terminal, run migrations and seed the first template:

```powershell
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
```

Open the API docs:

```text
http://localhost:8000/docs
```

## First Manual Flow

1. `GET /health` should return `ok`.
2. `POST /auth/register` creates a user and returns a bearer token.
3. Use `Authorization: Bearer <token>` for protected endpoints.
4. `GET /templates` should show the tiny Python HTTP app template.
5. `POST /resources` with `template_id` creates a pending resource and queued job.
6. The worker processes the job with the fake provisioner.
7. `GET /resources` shows the resource as running with a fake URL.
8. `GET /resources/{id}/events` shows lifecycle events.
9. `POST /resources/{id}/stop` queues a stop job.
10. `POST /resources/{id}/start` queues a start job for a stopped resource.
11. `POST /resources/{id}/restart` queues a restart job for a running resource.
12. `DELETE /resources/{id}` moves through `deleting` before `deleted`.
13. `GET /resources/{id}/logs` returns workload logs once a resource has an external ID.

## Provisioner Backends

The default backend is safe:

```text
PROVISIONER_BACKEND=fake
```

The Docker backend creates containers on a private Docker bridge network and does not publish workload ports directly to the host:

```text
PROVISIONER_BACKEND=docker
DOCKER_NETWORK_NAME=tiny-provisioner-apps
```

The Docker backend applies CPU/memory limits, labels containers for ownership/debugging, and adds Traefik labels for later hostname routing.

To try the Docker backend on a machine with Docker installed:

```powershell
docker compose -f docker-compose.yml -f docker-compose.docker.yml --profile templates build
docker compose -f docker-compose.yml -f docker-compose.docker.yml up
```

In this mode, Traefik listens on host ports `80` and `443`, watches a dynamic route file, and joins the `tiny-provisioner-apps` network. The worker receives the Docker socket so it can create containers and write Traefik routes; user containers do not receive the Docker socket.

Traefik does not inspect Docker directly in this project. The worker writes route entries like `demo.apps.localhost -> http://tp-demo:8000` into a shared Traefik dynamic config file.

The API also receives the Docker socket in Docker backend mode so `/resources/{id}/logs` can read real container logs. Treat the API and worker as trusted control-plane services; never pass the Docker socket to user-created containers.

For local testing, `APP_BASE_DOMAIN=apps.localhost` and `APP_PUBLIC_SCHEME=http` are enough for routes like `demo.apps.localhost`. On a VPS, point wildcard DNS such as `*.apps.example.com` at the server IP and switch `APP_PUBLIC_SCHEME=https` after TLS is configured.

## Guardrails

The MVP has two basic safety controls:

```text
MAX_ACTIVE_RESOURCES_PER_USER=3
DEFAULT_RESOURCE_TTL_HOURS=24
```

The quota protects host capacity and cost. The expiration time makes forgotten resources eligible for cleanup. The worker checks for expired resources before processing queued jobs and queues an idempotent delete job.

## Next Lessons

- Run local runtime validation in `docs/LOCAL_RUNTIME_VALIDATION.md`.
- Follow the VPS deployment runbook in `docs/VPS_RUNBOOK.md`.
- Review the security checklist in `docs/SECURITY_CHECKLIST.md`.
- Add host security hardening.
