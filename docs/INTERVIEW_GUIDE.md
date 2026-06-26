# TinyProvisioner Interview Readiness Guide

This guide is a printable study companion for TinyProvisioner. Use it to understand the project deeply enough to talk about it in interviews, explain design tradeoffs, and answer follow-up questions without memorizing scripts.

## How To Use This Guide

Read this in three passes:

1. Big picture: understand the architecture and request flow.
2. Code map: connect each idea to the files that implement it.
3. Interview practice: answer the questions out loud, then compare your answer to the model answer.

When you study, keep the code open beside this guide. Your goal is not to memorize every line. Your goal is to explain why the system is shaped this way.

## One-Minute Project Pitch

TinyProvisioner is a small compute provisioning control plane. A user logs in, requests a resource, and the API records that desired state in Postgres. A background worker processes queued jobs and calls a provisioner backend. In Docker mode, that backend creates a container on a private Docker network, applies basic resource and security limits, and updates Traefik routing so the workload can be reached through a hostname. The control panel shows resources, lifecycle events, logs, and system health checks.

Shorter version:

TinyProvisioner is a FastAPI, Postgres, Docker, and Traefik project that models how a small hosting platform provisions and manages workloads.

## What This Project Demonstrates

- API design with FastAPI
- Authentication with password hashes and bearer tokens
- Authorization through resource ownership checks
- Postgres-backed control plane state
- Background job processing
- Desired state vs actual state
- Docker container provisioning
- Private container networking
- Reverse proxy routing with Traefik
- System health checks
- Defensive cleanup and idempotent delete behavior
- Tests for auth, lifecycle, Docker behavior, and config safety

## Architecture At A Glance

```text
Browser / Control Panel
  -> FastAPI API
  -> Postgres stores users, resources, jobs, events
  -> Worker reads queued jobs
  -> Docker creates or changes containers
  -> Traefik routes hostnames to containers
  -> Browser opens the provisioned app
```

The most important separation:

- API: accepts requests and records intent
- Worker: performs slow infrastructure work
- Docker: runs the actual workload
- Traefik: routes traffic to the workload
- Postgres: remembers what happened and what should happen

## Control Plane vs Data Plane

The control plane is the decision-making and memory layer. In this project, the API, database, jobs, events, and worker are part of the control plane.

The data plane is where the workload actually runs. In this project, Docker containers are the data plane.

Interview answer:

The control plane decides and records what should exist. The data plane is the actual running infrastructure. In TinyProvisioner, the API records desired state and queues jobs. The worker turns those jobs into Docker actions. Docker then runs the workload.

## Component Breakdown

### Browser Control Panel

Role:

The control panel is the human interface. It lets a user log in, create resources, inspect state, read events, view logs, and check system health.

Important file:

- `app/ui/control_panel.html`

Interview talking point:

The UI is intentionally simple. It is not the main product; it exists to help demonstrate and debug the provisioning flow.

### API

Role:

The API is the front door. It receives HTTP requests, authenticates users, checks ownership, validates input, creates resource records, and queues jobs.

Important files:

- `app/main.py`
- `app/api/routes.py`
- `app/schemas.py`

Key design choice:

The API does not create containers directly. It responds quickly and lets the worker handle slow infrastructure actions.

Interview talking point:

Provisioning can take seconds, fail, or need retries. Keeping that work out of the request path makes the API more reliable and easier to reason about.

### Postgres Database

Role:

Postgres is the control plane memory. It stores users, tokens, templates, resources, jobs, and events.

Important files:

- `app/database.py`
- `app/models.py`
- `migrations/versions/202606240001_initial_schema.py`

Key design choice:

The database keeps resource history even after the Docker container is deleted.

Interview talking point:

Deleting infrastructure and deleting history are different. The container should be removed to free resources, but the database row can remain as an audit trail.

### Worker

Role:

The worker processes queued jobs. It moves resources from waiting to provisioning to running, and handles stop, start, restart, and delete actions.

Important file:

- `app/worker.py`

Key design choice:

The worker commits state changes and records events as it performs each step.

Interview talking point:

The worker is where desired state becomes real infrastructure. If a resource is stuck at waiting, the worker is the first thing I would check.

### Docker Provisioner

Role:

The Docker provisioner creates and manages containers for requested workloads.

Important files:

- `app/provisioners/base.py`
- `app/provisioners/fake.py`
- `app/provisioners/docker.py`

Key design choice:

The worker talks to a provisioner interface instead of hardcoding every action directly into the worker.

Interview talking point:

The provisioner interface made it possible to start with a fake backend for safe learning, then swap to a Docker backend for real provisioning.

### Traefik

Role:

Traefik is the reverse proxy. It receives HTTP traffic and forwards it to the correct internal container based on hostname.

Important files:

- `docker-compose.docker.yml`
- `app/provisioners/docker.py`

Key design choice:

User containers do not publish random host ports. Traefik is the controlled public entrypoint.

Interview talking point:

This is cleaner and safer than exposing every container directly. It also models how platforms route many apps through one edge proxy.

### Redis

Role:

Redis is included as stack infrastructure and future queue/cache support. The current worker mainly uses database-backed jobs.

Important file:

- `docker-compose.yml`

Interview talking point:

Redis is not heavily used yet, but it is a realistic next step for job queues, locks, rate limiting, and short-lived state.

### System Status

Role:

The System Status panel helps debug the stack. It checks whether API, database, Redis, Docker, worker, and Traefik are healthy.

Important files:

- `app/services/system_status.py`
- `app/api/routes.py`
- `app/ui/control_panel.html`
- `tests/test_system_status.py`

Interview talking point:

This is operational visibility. When a resource is stuck, I can quickly tell whether the issue is the API, worker, Docker, database, Redis, or Traefik.

## Core Data Models

### User

Represents an account. Users own resources and authenticate through tokens.

### ApiToken

Stores token hashes, not raw bearer tokens. This protects users if the database is leaked.

### Template

Defines an approved workload type. In this project, the first template is a tiny Python HTTP app.

### Resource

Represents a requested workload. It stores desired state, actual state, owner, resource limits, external ID, URL, timestamps, and deletion history.

### Job

Represents background work the worker should perform, such as provision, stop, start, restart, or delete.

### Event

Records what happened to a resource over time. Events are the audit trail and debugging history.

## Lifecycle States

The key resource states are:

- waiting: request exists, worker has not finished yet
- provisioning: worker is creating infrastructure
- running: workload is live
- stopping: worker is stopping the workload
- stopped: workload exists but is not running
- starting: worker is starting a stopped workload
- deleting: worker is cleaning up
- deleted: cleanup finished
- failed: worker hit an error

Interview answer:

Desired state is what the user or platform wants. Actual state is what is currently true. They can differ because infrastructure work takes time. For example, desired state can be running while actual state is provisioning.

## Main Flow: Create A Resource

1. User clicks Create in the control panel.
2. Browser sends `POST /resources` with a bearer token.
3. API authenticates the token.
4. API validates the template and quota.
5. API creates a Resource row.
6. API creates a Job row.
7. API creates an Event row.
8. Worker finds the queued job.
9. Worker marks the resource provisioning.
10. Docker provisioner creates the container.
11. Worker stores the Docker container ID and URL.
12. Worker marks the resource running.
13. Traefik routes traffic to the container.

What to say in an interview:

The API records intent and queues work. The worker performs the provisioning asynchronously. This prevents long-running Docker operations from blocking HTTP requests and gives the system a place to track retries, failures, and events.

## Main Flow: Delete A Resource

1. User clicks Delete.
2. API verifies ownership.
3. API queues a delete job.
4. Worker marks the resource deleting.
5. Worker tells Docker to remove the container.
6. Worker refreshes Traefik routing.
7. Worker marks the resource deleted.
8. Database row remains as history.

Important distinction:

Deleting the container removes the live workload. Keeping the database row preserves control plane memory.

Interview answer:

I keep the database record after deletion because it is useful for audit history, debugging, ownership tracking, and proving cleanup finished.

## Authentication And Authorization

Authentication means proving who someone is.

Authorization means deciding what that person is allowed to access.

In this project:

- Authentication happens through login and bearer tokens.
- Authorization happens by checking resource ownership.

Security choices:

- Passwords are hashed.
- Bearer tokens are hashed before storing.
- Missing or invalid tokens return `401`.
- Accessing another user's resource returns `404` so the API does not reveal whether the resource exists.

Interview answer:

I separated authentication from authorization. Login proves identity. Ownership checks decide whether that identity can access a resource.

## Docker And Networking

### Image vs Container

An image is the static template. A container is a running or stopped instance created from that image.

### Expose vs Publish

Expose documents that the app listens on a port inside the container.

Publish binds a container port to the host machine.

In this project, user containers do not publish host ports directly. Traefik routes traffic to them over a private Docker network.

### Private Network

The provisioned containers run on a Docker bridge network. Traefik can reach them, but they do not need to expose random host ports.

### Docker Socket Risk

The Docker socket is powerful. A container with access to `/var/run/docker.sock` can effectively control the Docker host.

Interview answer:

The API and worker are trusted control-plane services, so they can access Docker. User-created workload containers should never receive the Docker socket.

## Reverse Proxy And Routing

Traefik acts as the public entrypoint. It receives requests for hostnames like:

```text
demo-app.apps.localhost
```

Then it forwards traffic to the right internal container:

```text
Traefik -> http://tp-demo-app:8000
```

Why this matters:

- One public entrypoint can serve many apps.
- Workload containers stay private.
- Hostname routing is easier than random port routing.
- It is closer to how real platforms route customer apps.

## System Status Debugging

Use this mental checklist:

- API unhealthy: login, create, refresh, and API calls fail.
- Database unhealthy: most state reads/writes fail.
- Redis unhealthy: future queue/cache features would fail.
- Docker unhealthy: worker cannot create or manage containers.
- Worker unhealthy: resources get stuck at waiting.
- Traefik unhealthy: containers may run, but URLs do not route.

Interview answer:

If a resource is stuck at waiting, I check the worker first. If it is running but the URL fails, I check Traefik and routing next. If Docker actions fail, I check Docker access and worker logs.

## Code Map

### `app/main.py`

Creates the FastAPI app, includes routes, and serves the control panel.

What to say:

This is the app entrypoint. Keeping `create_app()` separate makes tests easier because tests can create fresh app instances.

### `app/api/routes.py`

Defines HTTP endpoints for health, auth, resources, lifecycle actions, logs, events, and system status.

What to say:

Routes are intentionally thin. They handle HTTP concerns and delegate business rules to services.

### `app/services/auth.py`

Handles registration, login, password hashing, token issuing, and token lookup.

What to say:

Auth code is separated from route code so it can be tested and reused.

### `app/services/resources.py`

Owns resource lifecycle rules, quota checks, expiration cleanup, ownership lookup, and job queueing.

What to say:

This is where control plane rules live before the worker touches infrastructure.

### `app/worker.py`

Processes queued jobs and calls the active provisioner.

What to say:

The worker is the bridge between database intent and actual infrastructure.

### `app/provisioners/docker.py`

Creates Docker containers, applies limits and labels, writes Traefik route config, starts/stops/deletes resources, and fetches logs.

What to say:

This is the real infrastructure adapter. It is intentionally separate from the worker so other backends could be added later.

### `app/services/system_status.py`

Checks database, Redis, Docker, worker, and Traefik status.

What to say:

This gives operational visibility and helps debug stuck resources.

### `tests/`

Executable proof that important behavior works.

What to say:

The tests cover auth, ownership, lifecycle transitions, Docker provisioning behavior, quota cleanup, compose config, and UI serving.

## Interview Questions And Model Answers

### 1. What did you build?

I built a small compute provisioning control plane. It lets a user request a resource, stores desired state in Postgres, queues a job, and has a worker provision a Docker container. Traefik routes traffic to the container, and the UI shows lifecycle state, events, logs, and system health.

### 2. Why did you use a worker?

Provisioning is slow and can fail. If the API created containers directly, the request could time out or leave the system in a confusing state. The worker lets the API respond quickly while background jobs track progress, retries, and failures.

### 3. What is desired state vs actual state?

Desired state is what the platform wants. Actual state is what is currently true. They can differ while work is in progress. For example, the desired state can be running while the actual state is provisioning.

### 4. Why keep events?

Events explain what happened over time. They help users and operators debug lifecycle problems, and they create an audit trail.

### 5. Why is delete idempotent?

Delete may be retried after timeouts or worker restarts. If the container is already gone, delete should still be considered successful. Repeating delete should not create duplicate cleanup jobs or crash.

### 6. Why not delete the database row immediately?

The database row is control plane memory. Keeping it lets us know who owned the resource, when it was created, when deletion happened, and whether cleanup finished.

### 7. What is the most dangerous security risk in this design?

Docker socket access is powerful. Any service with Docker socket access can control containers on the host. That is why only trusted control-plane services should have it, and user containers should not.

### 8. Why use Traefik?

Traefik gives one controlled public entrypoint and routes hostnames to private containers. That avoids publishing random host ports and models how real platforms route many customer workloads.

### 9. What happens if the worker is down?

The API can still accept requests and create jobs, but resources stay waiting because no process is handling the queued jobs.

### 10. What happens if Traefik is down?

Containers may still be running, but users cannot reach them through their hostnames.

### 11. What happens if Docker is down?

The worker cannot create, stop, start, or delete containers. Jobs would fail or resources would move to failed state.

### 12. What happens if Postgres is down?

The API and worker lose access to control plane state, so authentication, resources, jobs, events, and status checks mostly fail.

### 13. What is the difference between a smoke test and a unit test?

A unit test checks one small piece of behavior. A smoke test checks that the main end-to-end system flow is wired together and alive.

### 14. How would you scale this project?

I would move job processing to a real queue like Redis/RQ, add worker heartbeats, add structured logs and metrics, add stronger image allowlists, add per-resource storage limits, and eventually separate workloads across multiple hosts.

### 15. Is this production-ready?

No. It is a learning project that models production concepts. It still needs stronger queueing, observability, RBAC, TLS automation, image policy, host hardening, and multi-host scheduling before production use.

### 16. Why did you start with a fake provisioner?

The fake provisioner let me test the control plane safely before creating real containers. It helped prove auth, resource state, jobs, events, and lifecycle transitions first.

### 17. How do you prevent one user from accessing another user's resource?

Protected endpoints get the current user from the bearer token and then check resource ownership before returning or modifying a resource.

### 18. Why hash bearer tokens?

If the database leaks, raw bearer tokens would let an attacker immediately act as users. Hashing tokens reduces that risk.

### 19. What is the role of templates?

Templates define approved workload types. Instead of letting users run any image, the API creates resources from known templates.

### 20. What would you improve next?

I would add a real Redis-backed job queue, worker heartbeats, GitHub Actions, structured logging, metrics, TLS for VPS deployment, and stronger container/image policy.

## Debugging Scenarios

### Resource stuck at waiting

Likely cause:

Worker is down or not processing jobs.

Check:

- System Status -> Worker
- Worker logs
- Jobs table

### Resource failed during provisioning

Likely cause:

Docker error, missing image, network problem, or route config problem.

Check:

- Worker logs
- Resource events
- Docker status
- Template image name

### Resource says running but URL gives 404

Likely cause:

Traefik route has not loaded, hostname is wrong, or Traefik cannot reach the container.

Check:

- System Status -> Traefik
- Generated route config
- Docker network membership
- Hostname used in browser

### Logs say container no longer exists

Likely cause:

The resource was deleted and the Docker container was removed. The database record remains as history.

Check:

- Resource state
- Events
- Docker containers

### API says Internal Server Error

Likely cause:

Unhandled backend exception.

Check:

- API logs
- Endpoint that failed
- Recent code changes
- Whether the response was JSON or plain text

## Definitions

API: The HTTP interface clients call.

Authentication: Proving who someone is.

Authorization: Deciding what someone can access.

Bearer token: A secret sent with requests to prove an authenticated session.

Control plane: The decision and state layer.

Data plane: The actual workload-running layer.

Desired state: What the platform wants.

Actual state: What is currently true.

External ID: The backend-specific identifier, such as a Docker container ID.

Job: A saved unit of background work.

Event: An audit/debug record.

Provisioning: Creating or preparing a resource.

Docker image: A static template for containers.

Docker container: A running or stopped instance of an image.

Reverse proxy: A server that receives traffic and forwards it to internal services.

Traefik: The reverse proxy used in this project.

Quota: A limit that protects capacity and cost.

TTL: Time to live. The amount of time a resource should exist before cleanup.

Idempotency: The property that repeating an operation is safe.

Smoke test: An end-to-end test that proves the main flow works.

## Flashcards

Q: Who creates the Docker container?

A: The worker, through the Docker provisioner.

Q: Why should the API not create containers directly?

A: It would couple slow infrastructure work to the request path and could cause timeouts.

Q: What does `POST /resources` create?

A: A resource row, a job row, and an event row.

Q: What should you check first if a resource is stuck waiting?

A: The worker.

Q: What should you check first if the resource is running but the URL fails?

A: Traefik and routing.

Q: Why keep a deleted resource in the database?

A: To preserve audit history and prove cleanup finished.

Q: Why is Docker socket access dangerous?

A: It can effectively grant control over the Docker host.

Q: What is the difference between exposing and publishing a port?

A: Exposing documents an internal listening port. Publishing binds a port to the host.

Q: What is a reverse proxy?

A: A service that receives client requests and forwards them to the correct internal service.

Q: What does wildcard DNS help with?

A: It lets many subdomains point to the same server so the proxy can route them dynamically.

## Should The Browser Keep Flashcards?

Recommendation:

Keep the flashcards while this is a learning project, but consider adding a "Learning Mode" toggle before using it as a polished portfolio demo.

Why:

- For you, flashcards are useful because they force active recall.
- For interviewers, the flashcards show that the project is intentionally educational.
- For a polished production-style demo, the UI may look more professional if learning prompts are hidden by default.

Best final approach:

Keep the feature, but make it collapsible or toggleable. That way you can show either a clean control panel or a guided learning view.

## Two-Week Interview Study Plan

### Days 1-2: Architecture

Explain control plane, data plane, API, worker, database, Docker, and Traefik out loud.

### Days 3-4: Resource Lifecycle

Trace create, stop, start, restart, and delete through the code.

### Days 5-6: Auth And Security

Explain password hashing, token hashing, ownership checks, Docker socket risk, and private networking.

### Days 7-8: Docker And Traefik

Explain images, containers, ports, private networks, reverse proxy routing, and why workloads do not publish host ports.

### Days 9-10: Debugging

Practice diagnosing waiting, failed, running-but-404, and deleted-container log scenarios.

### Days 11-12: Tests

Read the tests and explain what behavior each test protects.

### Days 13-14: Mock Interview

Answer the interview questions in this guide without reading the model answers. Then review the code for any weak spots.

## Final Interview Story

Use this as your base answer:

I built TinyProvisioner to learn how compute provisioning platforms work. A user can log in and request a resource. The API validates the request, stores desired state in Postgres, creates a job, and returns quickly. A worker processes queued jobs and calls a provisioner interface. In Docker mode, the provisioner creates a container on a private network, applies resource and security limits, and updates Traefik routing so the workload can be reached by hostname. The app also records lifecycle events, exposes logs, enforces basic quotas and TTL cleanup, and has a System Status panel to debug API, database, Redis, Docker, worker, and proxy health.

If asked what you learned:

I learned that provisioning is mostly about state, ownership, retries, and cleanup. Creating a container is only one piece. The harder part is safely tracking intent, moving through lifecycle states, debugging failures, and cleaning up resources without losing audit history.
