# Flashcards And Labs

Use these after each build session. If you cannot answer a card, open the code and find the answer.

## Flashcards

### Control Plane

Q: What is the control plane in this project?

A: The API and database layer that records desired state and queues work.

Q: Why should the API not create containers directly?

A: Container creation is slow and failure-prone. A worker can retry, record state, and avoid blocking HTTP requests.

Q: What does `POST /resources` create?

A: A resource row, a job row, and an event row.

### Data Plane

Q: What is the data plane in this project?

A: The backend where workloads run: fake resources for learning, Docker containers for real provisioning.

Q: What is an external ID?

A: The backend-specific identifier, such as a Docker container ID.

### Auth

Q: What is authentication?

A: Proving who someone is.

Q: What is authorization?

A: Deciding what that person is allowed to access.

Q: Why store a password hash?

A: So the app does not store recoverable user passwords.

Q: Why store a token hash instead of the raw bearer token?

A: If the database leaks, attackers should not immediately get usable tokens.

### Lifecycle

Q: What is desired state?

A: What the platform wants.

Q: What is actual state?

A: What is currently true or in progress.

Q: Why does delete go through `deleting` before `deleted`?

A: Cleanup can take time and can fail halfway through.

Q: Why is delete idempotent?

A: Repeating delete should be safe and should not create duplicate cleanup jobs.

### Docker

Q: What is a Docker image?

A: A static template for containers.

Q: What is a Docker container?

A: A running or stopped instance created from an image.

Q: Why is mounting `/var/run/docker.sock` into user containers dangerous?

A: It effectively gives control over the Docker host.

Q: Why do user containers not publish host ports?

A: Traefik should be the public entrypoint; user containers stay private.

### Networking

Q: What does Traefik do?

A: It receives public traffic and routes hostnames to the correct internal container.

Q: What does wildcard DNS do?

A: It points many subdomains at the same server so the proxy can route dynamically.

### Operations

Q: What data must survive restarts?

A: Postgres data, backups, `.env.production`, TLS certs, and possibly Redis queue data.

Q: Which ports should be public on the VPS?

A: `80`, `443`, and restricted `22` for SSH.

Q: Why should Redis and Postgres not be public?

A: They contain or control sensitive app state and can be abused if exposed.

## Labs

### Lab 1: Trace Resource Creation

Goal: Explain what happens after `POST /resources`.

Steps:

1. Open [app/api/routes.py](../app/api/routes.py).
2. Find `request_resource`.
3. Follow the call to `create_resource`.
4. Open [app/services/resources.py](../app/services/resources.py).
5. Identify where the resource, job, and event are created.
6. Open [tests/test_resources_api.py](../tests/test_resources_api.py).
7. Find the test that proves this behavior.

Deliverable:

Explain the flow in five sentences.

### Lab 2: Trace Worker Provisioning

Goal: Explain `pending -> provisioning -> running`.

Steps:

1. Open [app/worker.py](../app/worker.py).
2. Find `process_queued_jobs`.
3. Find the branch for `provision_resource`.
4. Follow the call to `provision_resource`.
5. Identify where the resource becomes `provisioning`.
6. Identify where it becomes `running`.
7. Open [tests/test_worker.py](../tests/test_worker.py).

Deliverable:

Draw the state transition and name the event rows created.

### Lab 3: Break Quota On Purpose

Goal: Understand quota behavior.

Steps:

1. Open [tests/test_quota_cleanup.py](../tests/test_quota_cleanup.py).
2. Find `test_resource_quota_blocks_excess_active_resources`.
3. Change the expected `409` to `202`.
4. Run tests.
5. Read the failure.
6. Revert the change.

Deliverable:

Explain why the second resource is blocked.

### Lab 4: Prove Delete Is Idempotent

Goal: Understand safe retries.

Steps:

1. Open [tests/test_resource_lifecycle.py](../tests/test_resource_lifecycle.py).
2. Find `test_delete_is_idempotent_and_finishes_deleted`.
3. Identify where delete is called twice.
4. Identify the assertion that only one delete job exists.

Deliverable:

Explain why this matters when a worker or network call fails halfway.

### Lab 5: Read Docker Provisioning Like A Security Review

Goal: Understand Docker risk boundaries.

Steps:

1. Open [app/provisioners/docker.py](../app/provisioners/docker.py).
2. Find `self.client.containers.run`.
3. Identify `ports={}` and `publish_all_ports=False`.
4. Identify memory and CPU limits.
5. Identify labels.
6. Identify hardening options.
7. Open [tests/test_docker_provisioner.py](../tests/test_docker_provisioner.py).

Deliverable:

List three ways the Docker provisioner reduces risk and one risk that still remains.

### Lab 6: Smoke Test Reflection

Goal: Understand what "smoke test passed" means.

Steps:

1. Open [scripts/smoke_test.py](../scripts/smoke_test.py).
2. Write down every endpoint it calls.
3. For each endpoint, write what table or state it depends on.
4. Run the smoke test again.

Deliverable:

Explain what the smoke test proves and what it does not prove.

