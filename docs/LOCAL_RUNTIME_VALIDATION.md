# Local Runtime Validation

Use this after code-level tests pass. The goal is to prove the app, database, worker, and provisioner actually talk to each other.

## Quiz First

Answer before running commands:

- What is the difference between the fake backend and Docker backend?
- Why should the fake backend pass before Docker provisioning?
- Why should Traefik receive public traffic instead of user containers?

## Fake Backend Smoke Test

The fake backend proves the control plane:

- API accepts authenticated requests.
- Postgres stores resources, jobs, and events.
- Worker processes jobs.
- Lifecycle state changes happen.
- Logs/events endpoints respond.

Start from a clean local `.env`:

```powershell
Copy-Item .env.example .env
```

Keep these values for the first run:

```text
PROVISIONER_BACKEND=fake
APP_BASE_DOMAIN=apps.localhost
APP_PUBLIC_SCHEME=http
```

Start the stack:

```powershell
docker compose up --build
```

In another terminal:

```powershell
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
docker compose exec api python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

Expected result:

```text
smoke test passed
```

If it times out waiting for `running`, check the worker logs:

```powershell
docker compose logs --tail=100 worker
```

## Docker Backend Smoke Test

Only run this after the fake backend passes.

Build the app and template image:

```powershell
docker compose -f docker-compose.yml -f docker-compose.docker.yml --profile templates build
```

Start the Docker backend:

```powershell
docker compose -f docker-compose.yml -f docker-compose.docker.yml up
```

In another terminal:

```powershell
docker compose -f docker-compose.yml -f docker-compose.docker.yml exec api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.docker.yml exec api python -m app.seed
docker compose -f docker-compose.yml -f docker-compose.docker.yml exec api python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

Then inspect Docker:

```powershell
docker ps
docker network inspect tiny-provisioner-apps
```

You should see:

- Traefik published on host ports `80` and `443`.
- API on local development port `8000`.
- Postgres and Redis for local development.
- A provisioned container named like `tp-smoke-demo-...`.
- The provisioned container attached to `tiny-provisioner-apps`.
- No published random host port for the provisioned container.

## Manual Browser Check

For local Docker backend testing, `apps.localhost` should resolve to localhost on most modern systems.

Visit the provisioned resource URL printed by the smoke test:

```text
http://smoke-demo-xxxx.apps.localhost
```

If the browser cannot resolve it, add a temporary hosts entry for the exact hostname or test with curl using a Host header.

## Failure Triage

API fails:

```powershell
docker compose logs --tail=100 api
```

Worker fails:

```powershell
docker compose logs --tail=100 worker
```

Database migration missing:

```powershell
docker compose exec api alembic upgrade head
```

Template missing:

```powershell
docker compose exec api python -m app.seed
```

Docker backend cannot create containers:

- Confirm Docker is running.
- Confirm the worker has `/var/run/docker.sock` mounted.
- Confirm `tiny-python-http-app:local` exists with `docker images`.

