# Reliable Job Processing Learning Guide

TinyProvisioner uses PostgreSQL as a small durable job queue. This guide explains how several workers can safely share that queue, what happens when infrastructure calls fail, and why the design promises at-least-once rather than exactly-once execution.

## The Race Condition We Fixed

The first worker implementation effectively did this:

```text
Worker A: SELECT jobs WHERE status = 'queued'
Worker B: SELECT jobs WHERE status = 'queued'
```

Both workers could read the same row before either changed it. They could then create or modify the same infrastructure at the same time.

The reliable implementation claims a row inside a short database transaction:

```sql
BEGIN;

SELECT *
FROM jobs
WHERE status = 'queued'
  AND available_at <= now()
ORDER BY available_at, created_at, id
LIMIT 1
FOR UPDATE SKIP LOCKED;

UPDATE jobs
SET status = 'running',
    claimed_by = :worker_id,
    attempts = attempts + 1,
    heartbeat_at = now();

COMMIT;
```

`FOR UPDATE` places row-level locks on the selected job and its resource. `SKIP LOCKED` tells another worker not to wait for those rows; it should look for different available work. Locking the resource prevents two different lifecycle jobs for one resource from running concurrently. A partial unique index allowing only one `running` job per resource is the final database-enforced backstop against a commit race. PostgreSQL specifically documents `SKIP LOCKED` as useful for multiple consumers of a queue-like table.

SQLAlchemy generates this locking clause from:

```python
select(Job).with_for_update(skip_locked=True, of=(Job, Resource))
```

References:

- [PostgreSQL locking clause](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [SQLAlchemy `with_for_update`](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.GenerativeSelect.with_for_update)

## Why the Lock Is Short

The worker commits immediately after changing the job to `running`. It does not hold the PostgreSQL row lock while Docker or SSH performs slow work.

Holding the transaction open around an infrastructure call would:

- Occupy a database connection for the duration of the call
- Increase lock contention
- Make database maintenance harder
- Risk long-running transactions and table bloat
- Couple infrastructure latency to database health

The durable lease replaces the long transaction after the claim is committed.

## The Lease and Heartbeat

A claimed job stores:

| Field | Meaning |
| --- | --- |
| `status` | `running` while a worker owns the lease |
| `claimed_by` | Unique identity of the worker process |
| `claimed_at` | When this attempt began |
| `heartbeat_at` | Most recent proof that the worker still owns the job |
| `attempts` | Number of times the job has been claimed |
| `max_attempts` | Maximum claims before dead-lettering |

The worker writes heartbeats using a separate, short-lived database session. That matters because the main worker may be awaiting Docker or SSH and should not keep a database transaction open.

If `heartbeat_at` becomes older than `JOB_LEASE_SECONDS`, another worker treats the job as abandoned. It locks the stale row, records a recovery event, and schedules another attempt.

Completion is also fenced by the lease owner. Before writing success or failure, the worker locks and reloads the job row and verifies that `claimed_by` still matches its identity. A paused worker that wakes after its lease was recovered cannot overwrite the newer worker's result.

Worker processes also have rows in the `workers` table. The System Status panel now checks these application-level heartbeats instead of inferring worker health from whether a Compose container exists. A running container can contain a stuck worker; a fresh heartbeat proves that the loop is actually communicating with the control-plane database.

## Retry State Machine

```text
queued and available
        |
        | atomic claim
        v
      running
       /   \
      /     \
 success   failure
    |          |
    v          | attempts remain
succeeded      v
            queued for later
                 |
                 | attempts exhausted
                 v
                dead
```

The `dead` status is the dead-letter state. The job remains in PostgreSQL with its error and attempt history so an operator can investigate it. TinyProvisioner does not silently delete failed work.

## Exponential Backoff and Jitter

Retrying immediately can make an outage worse. If Docker, a registry, or a remote host is unavailable, rapid retries create extra load without improving the result.

The delay grows approximately as:

```text
base × 2^(attempt - 1)
```

It is capped by `JOB_RETRY_MAX_SECONDS`. A small deterministic jitter is added so many jobs do not all retry at the same instant. For the default five-second base, the schedule is approximately 5, 10, and 20 seconds before continuing upward toward the cap.

Permanent errors are different. An unknown job kind or a missing required external ID will not heal after waiting, so those jobs move directly to `dead`.

## Why This Is At-Least-Once Delivery

Consider this timeline:

```text
1. Worker asks Docker to create a container.
2. Docker creates it successfully.
3. Worker process crashes before recording success in PostgreSQL.
4. The lease expires.
5. Another worker retries the job.
```

PostgreSQL cannot know whether step 2 happened. Therefore a correct system must assume the operation may run more than once.

TinyProvisioner's provisioners make repeated operations safe:

- Provisioning uses a deterministic container name and returns an existing container.
- Start returns successfully if the container is already running.
- Stop returns successfully if it is already stopped.
- Delete returns successfully if it is already gone.
- The API lifecycle prevents duplicate queued operations in normal request retries.

This property is idempotency: repeating the operation produces the same intended final state.

## Configuration

| Variable | Default | Purpose |
| --- | ---: | --- |
| `JOB_MAX_ATTEMPTS` | 3 | Claims allowed before dead-lettering |
| `JOB_RETRY_BASE_SECONDS` | 5 | Initial retry delay |
| `JOB_RETRY_MAX_SECONDS` | 300 | Backoff cap |
| `JOB_LEASE_SECONDS` | 90 | Heartbeat age that makes a job abandoned |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | 10 | Busy-worker heartbeat frequency |
| `WORKER_STALE_AFTER_SECONDS` | 30 | System Status health threshold |

The lease must be comfortably longer than the heartbeat interval. With the defaults, a healthy worker has several opportunities to renew before recovery begins.

## How the Tests Prove It

The fast unit suite proves:

- A claimed job cannot be claimed again
- Different jobs for the same resource cannot run concurrently
- Claim SQL compiles to `FOR UPDATE OF jobs, resources SKIP LOCKED`
- A heartbeat extends the job and worker lease
- Transient failures retry with delayed availability
- Permanent failures do not waste retry attempts
- Exhausted jobs enter `dead`
- Stale leases are recovered

CI also starts a real PostgreSQL service. Two threads with separate database sessions attempt to claim work simultaneously. The test covers both one queued job and two jobs belonging to the same resource. The assertions prove only one worker receives work for that resource. SQLite remains useful for fast behavior tests, but it cannot prove PostgreSQL row-lock semantics.

### Run the PostgreSQL cases locally

These concurrency tests delete their own test records. They contain a safety guard and refuse to run unless the database name ends in `_test`. Never point `TEST_DATABASE_URL` at a development or production database.

Create and migrate a dedicated local database:

```bash
docker compose exec postgres createdb -U provisioner provisioner_test
DATABASE_URL=postgresql+psycopg://provisioner:provisioner@127.0.0.1:5432/provisioner_test \
  .venv/bin/python -m alembic upgrade head
```

Run the complete suite against it:

```bash
DATABASE_URL=postgresql+psycopg://provisioner:provisioner@127.0.0.1:5432/provisioner_test \
TEST_DATABASE_URL=postgresql+psycopg://provisioner:provisioner@127.0.0.1:5432/provisioner_test \
  .venv/bin/python -m pytest
```

## Hands-On Labs

### Lab 1: Watch two workers share the queue

Start multiple worker containers:

```powershell
docker compose up --build --scale worker=2
```

Create several resources and inspect job ownership:

```sql
SELECT id, kind, status, attempts, claimed_by, heartbeat_at
FROM jobs
ORDER BY id;
```

Each job should have only one `claimed_by` value for its current attempt.

### Lab 2: Observe lease recovery

Set a short lease in a temporary local environment, begin a provisioning job, and force-stop its worker. Do not use a production environment for this experiment.

```text
JOB_LEASE_SECONDS=20
WORKER_HEARTBEAT_INTERVAL_SECONDS=5
```

Watch the job events for `job.recovered`, then confirm another worker claims the retry after `available_at`.

### Lab 3: Read the retry schedule

Query jobs that are waiting after a transient failure:

```sql
SELECT id, attempts, max_attempts, available_at, last_error
FROM jobs
WHERE status = 'queued'
ORDER BY available_at;
```

Explain why `available_at` is better than making the entire worker sleep for one failed job: the worker remains free to process other ready work.

## Interview Explanation

> I made the database-backed worker safe to scale horizontally with PostgreSQL row locks and `SKIP LOCKED`. A worker claims one job in a short transaction, commits a renewable lease, and performs the slow infrastructure call outside the transaction. Transient failures use capped exponential backoff with jitter, exhausted work enters a dead-letter state, and stale leases are recovered using heartbeats. The design provides at-least-once execution, so Docker and SSH operations are idempotent. A real PostgreSQL concurrency test proves two workers cannot claim the same job.
