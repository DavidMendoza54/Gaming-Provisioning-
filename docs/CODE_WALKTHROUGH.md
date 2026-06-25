# Guided Code Walkthrough

This walkthrough explains the important files and functions. It is not a substitute for reading the code. Keep the code open beside this document.

## Project Entry Points

### [app/main.py](../app/main.py)

Purpose: creates the FastAPI application and attaches routes.

Key ideas:

- `create_app()` builds the app object.
- `app.include_router(router)` connects all HTTP endpoints.
- Keeping app creation in a function makes tests easier.

Questions:

- Why do tests call `create_app()` instead of importing only a global app?
- What would happen if routes were never included?

### [app/api/routes.py](../app/api/routes.py)

Purpose: defines the HTTP API.

Important sections:

- `bearer_scheme = HTTPBearer(auto_error=False)` configures bearer token parsing.
- `get_current_user()` turns a token into a user.
- `/auth/register` creates a user and returns a token.
- `/auth/login` verifies a password and returns a token.
- `/resources` creates resource intent, not the actual compute.
- `/resources/{id}/start`, `/stop`, `/restart`, and `DELETE` queue lifecycle jobs.
- `/resources/{id}/events` returns audit history.
- `/resources/{id}/logs` asks the active provisioner for logs.

Line-level reading prompts:

- At each endpoint, identify the request model, dependencies, service call, and response model.
- For each `HTTPException`, ask what user behavior or security rule causes it.
- For each `Depends(...)`, ask what dependency FastAPI injects.

Questions:

- Why does `get_current_user()` return `401` for missing/invalid tokens?
- Why does accessing another user's resource return `404`?
- Why does `POST /resources` return `202 Accepted` instead of `201 Created`?

## Database Layer

### [app/database.py](../app/database.py)

Purpose: configures SQLAlchemy.

Key ideas:

- `Base` is the parent class for models.
- `engine` knows how to connect to the database.
- `SessionLocal` creates sessions.
- `get_session()` gives each request a database session and closes it afterward.

Questions:

- Why should every request get a bounded database session?
- What could happen if sessions were never closed?

### [app/models.py](../app/models.py)

Purpose: defines database tables.

Important models:

- `User`: account identity.
- `ApiToken`: bearer token hash, expiration, revocation fields.
- `Template`: approved workload template.
- `Resource`: user-owned desired/actual workload state.
- `Job`: queued worker action.
- `Event`: audit/debug history.

Line-level reading prompts:

- For each foreign key, identify the relationship it represents.
- For each nullable field, ask why it might be missing.
- For each indexed field, ask how the app searches by it.

Questions:

- Why is `token_hash` stored instead of the raw token?
- Why does `Resource` have both `desired_state` and `actual_state`?
- Why does `Event` use JSON metadata?

### [migrations/versions/202606240001_initial_schema.py](../migrations/versions/202606240001_initial_schema.py)

Purpose: creates the database tables in a real database.

Questions:

- Why do we need migrations instead of only SQLAlchemy models?
- What happens if the app starts before migrations run?

## Auth

### [app/services/auth.py](../app/services/auth.py)

Purpose: handles registration, login, password hashing, and bearer tokens.

Important functions:

- `normalize_email()`: prevents duplicate case variants.
- `hash_password()`: stores a password hash, not the password.
- `verify_password()`: checks login password against hash.
- `hash_token()`: stores only a SHA-256 hash of the bearer token.
- `register_user()`: creates a new user.
- `authenticate_user()`: returns a user only if credentials are valid.
- `issue_token()`: creates one raw token for the client and stores only its hash.
- `get_user_by_token()`: maps incoming bearer token to user.

Questions:

- Why is a bearer token dangerous if logged?
- Why does token expiration matter?
- What is the difference between password hashing and token hashing here?

## Resource Service Layer

### [app/services/resources.py](../app/services/resources.py)

Purpose: owns resource lifecycle rules before the worker acts.

Important functions:

- `slugify()`: turns a user-provided name into URL-safe text.
- `create_resource()`: validates template, checks quota, sets expiration, creates resource/job/event.
- `count_active_resources()`: enforces per-user quota.
- `get_owned_resource()`: ensures resource ownership.
- `queue_stop_resource()`: moves running resource to stopping and queues stop.
- `queue_start_resource()`: moves stopped resource to starting and queues start.
- `queue_restart_resource()`: queues restart only for running resources.
- `queue_delete_resource()`: idempotent delete queueing.
- `queue_expired_resources_for_cleanup()`: finds expired resources and queues cleanup.

Line-level reading prompts:

- In `create_resource()`, find the exact moment the resource ID becomes available.
- In `queue_delete_resource()`, find where non-delete queued jobs are cancelled.
- In cleanup, find the guard that prevents duplicate delete jobs.

Questions:

- Why should quota be checked before creating a resource row?
- Why does delete cancel pending non-delete jobs?
- Why should expired cleanup create an event?

## Worker

### [app/worker.py](../app/worker.py)

Purpose: turns queued jobs into provisioner actions.

Important functions:

- `add_event()`: records worker-side events.
- `mark_job_running()`: sets attempts and start time.
- `mark_job_succeeded()`: records successful completion.
- `provision_resource()`: calls provisioner and marks resource running.
- `start_resource()`: starts an existing external resource.
- `stop_resource()`: stops an existing external resource.
- `restart_resource()`: stop then start.
- `delete_resource()`: calls provisioner delete and marks resource deleted.
- `process_queued_jobs()`: dispatches queued jobs by kind.
- `run_once()`: queues expired cleanup, then processes jobs.
- `main()`: forever loop for the worker container.

Line-level reading prompts:

- In each worker action, find the first database state change.
- Find where failures become `resource.failed` events.
- Find where the provisioner interface is used instead of hardcoding Docker.

Questions:

- Why does the worker commit state before calling the provisioner?
- What happens if a provisioner call raises an exception?
- Why is `resource_id` saved before the `try` block?

## Provisioners

### [app/provisioners/base.py](../app/provisioners/base.py)

Purpose: defines what every provisioner must know how to do.

The worker expects:

- `provision`
- `start`
- `stop`
- `delete`
- `logs`

Questions:

- Why is this interface useful?
- How did it make fake and Docker backends interchangeable?

### [app/provisioners/fake.py](../app/provisioners/fake.py)

Purpose: safe backend for learning control-plane behavior.

It does not create real containers. It returns fake external IDs and deterministic logs.

Questions:

- What does fake provisioning prove?
- What does fake provisioning not prove?

### [app/provisioners/docker.py](../app/provisioners/docker.py)

Purpose: real Docker backend.

Important behavior:

- Creates or reuses a container.
- Uses a private Docker network.
- Does not publish host ports.
- Applies memory/CPU limits.
- Adds ownership labels.
- Adds Traefik routing labels.
- Drops capabilities and uses `no-new-privileges`.
- Handles missing containers during delete as success.

Questions:

- Why should user containers not receive `/var/run/docker.sock`?
- Why does Docker delete tolerate missing containers?
- Why are Traefik labels generated here?

## Smoke Test

### [scripts/smoke_test.py](../scripts/smoke_test.py)

Purpose: simulates a real user lifecycle over HTTP.

It proves:

- API is reachable.
- Auth works.
- Template exists.
- Resource create works.
- Worker processes jobs.
- Logs/events work.
- Stop/start/delete work.

Questions:

- Why is a smoke test different from a unit test?
- Why does it poll resource state instead of assuming immediate success?

## Tests

Test files are your executable study guide.

- [tests/test_auth_api.py](../tests/test_auth_api.py): auth and token behavior.
- [tests/test_resources_api.py](../tests/test_resources_api.py): resource create and ownership.
- [tests/test_resource_lifecycle.py](../tests/test_resource_lifecycle.py): start/stop/delete lifecycle.
- [tests/test_quota_cleanup.py](../tests/test_quota_cleanup.py): quotas and expiration cleanup.
- [tests/test_docker_provisioner.py](../tests/test_docker_provisioner.py): Docker calls without Docker installed.
- [tests/test_compose_config.py](../tests/test_compose_config.py): deployment config safety.

Questions:

- Which test proves user A cannot view user B's resource?
- Which test proves delete is idempotent?
- Which test proves Docker containers do not publish host ports?

