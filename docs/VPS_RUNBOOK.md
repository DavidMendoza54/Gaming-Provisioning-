# VPS Runbook

This runbook is for the first public demo: one Ubuntu VPS, Docker Compose, Postgres, Redis, Traefik, and Docker-based app provisioning.

Traefik reads worker-generated route config from a shared volume. The API and worker remain trusted control-plane services with Docker socket access; user workload containers do not receive the Docker socket.

## Before You Deploy

Quiz yourself:

- What data must survive a container restart?
- Which ports should be public?
- Why are Redis and Postgres private?
- How do you destroy a provisioned resource safely?

## Public Ports

Only these should be reachable from the internet:

- `22/tcp` for SSH, preferably restricted to your IP and key-only login.
- `80/tcp` for HTTP redirect and ACME certificate challenge.
- `443/tcp` for HTTPS traffic.

Do not expose:

- `5432/tcp` Postgres.
- `6379/tcp` Redis.
- `8000/tcp` API direct port.
- `8080/tcp` Traefik dashboard.
- Docker daemon ports.

## Persistent Data

Must survive restarts:

- `postgres-data`: users, tokens, resources, jobs, events, external IDs.
- `redis-data`: queued work if Redis append-only mode is enabled.
- `letsencrypt`: TLS certificates.
- `.env.production`: secrets and deployment settings.
- Database backups.

## First VPS Setup

Install Docker and Compose using the official Docker instructions for your distro.

Create the production env file:

```bash
cp .env.production.example .env.production
```

Edit these values:

```text
APP_BASE_DOMAIN=apps.yourdomain.com
POSTGRES_PASSWORD=<long random password>
DATABASE_URL=postgresql+psycopg://provisioner:<same password>@postgres:5432/provisioner
SECRET_KEY=<long random secret>
ACME_EMAIL=<your email>
```

Point DNS at the VPS:

```text
api.apps.yourdomain.com -> VPS public IP
*.apps.yourdomain.com -> VPS public IP
```

Build the template image and app services:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml --profile templates build
```

Start the platform:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Run migrations and seed the first template:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec api alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml exec api python -m app.seed
```

## Firewall Checklist

With `ufw`, the shape is:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

After setup, consider restricting SSH to your IP:

```bash
sudo ufw delete allow 22/tcp
sudo ufw allow from YOUR_PUBLIC_IP to any port 22 proto tcp
```

## Backups

Create a backup directory:

```bash
mkdir -p backups
```

Create a Postgres backup:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres pg_dump -U provisioner provisioner > backups/provisioner-$(date +%Y%m%d-%H%M%S).sql
```

Restore a backup:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres psql -U provisioner provisioner < backups/YOUR_BACKUP.sql
```

Test restore on a throwaway environment before trusting backups.

## Deployment Update

Pull or copy the new code, then:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build api worker
docker compose --env-file .env.production -f docker-compose.prod.yml up -d api worker
docker compose --env-file .env.production -f docker-compose.prod.yml exec api alembic upgrade head
```

Verify:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 api worker traefik
```

## Rollback

For this learning project, rollback is manual:

1. Keep the previous Git commit SHA.
2. Keep a database backup before migrations.
3. If a deployment breaks, checkout the previous SHA.
4. Rebuild and restart `api` and `worker`.
5. Restore the database only if the migration/data changed and you understand the data loss risk.

## Cleanup Drills

Practice these before inviting friends:

- Delete one running resource.
- Delete one already-deleted resource.
- Let one resource expire and verify cleanup.
- Restart the VPS and verify Postgres state remains.
- Confirm Redis/Postgres are not reachable from the public internet.
