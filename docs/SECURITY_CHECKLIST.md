# Security Checklist

Use this before deploying or inviting friends.

## Host

- SSH key login only.
- Password SSH login disabled.
- Firewall allows only `22`, `80`, and `443`.
- Docker daemon is not exposed over TCP.
- System packages are updated.

## App

- `SECRET_KEY` is changed from the example value.
- `POSTGRES_PASSWORD` is long and random.
- `.env.production` is not committed.
- Users cannot read other users' resources.
- Resource quota is enabled.
- Resource expiration is enabled.
- Delete jobs are idempotent.

## Network

- Postgres has no public port mapping.
- Redis has no public port mapping.
- API port `8000` is not public in production.
- Traefik dashboard is not public in production.
- User containers join a private app network.
- User containers do not receive `/var/run/docker.sock`.
- Only trusted control-plane services, such as `api` and `worker`, receive `/var/run/docker.sock`.
- Traefik does not receive `/var/run/docker.sock`; it reads worker-generated route config.

## Operations

- Backup command has been run once.
- Restore has been tested somewhere safe.
- Expired-resource cleanup has been tested.
- Logs do not contain bearer tokens or passwords.
