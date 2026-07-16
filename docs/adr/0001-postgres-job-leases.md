# ADR 0001: PostgreSQL Job Leases

- Status: Accepted
- Date: 2026-07-16

## Context

TinyProvisioner records infrastructure work in a `jobs` table. The original worker selected every queued row without locking it. If multiple worker processes ran, more than one process could select and execute the same job.

The platform already requires PostgreSQL for durable control-plane state. Its current workload is small, and resource updates, job transitions, and audit events benefit from sharing one transaction system.

## Decision

Use PostgreSQL as the current job queue and distribute work with `SELECT ... FOR UPDATE SKIP LOCKED`. Claiming locks both the job and its resource so separate lifecycle jobs cannot operate on one resource concurrently. A partial unique index permits at most one `running` job per resource as a database-enforced race-condition backstop.

Each worker will:

1. Lock and claim one available job in a short transaction.
2. Commit a `running` status, worker identity, attempt count, and lease heartbeat.
3. Perform Docker or SSH work outside the claiming transaction.
4. Mark success, schedule a retry, or move exhausted work to `dead`.
5. Renew long-running work through a separate heartbeat session.

Workers will recover running jobs whose leases expire. Provisioner operations must therefore be idempotent, and the delivery guarantee is at least once.

## Alternatives Considered

### Redis and RQ

RQ would provide a mature queue and worker ecosystem. It remains a reasonable future choice when throughput, queue routing, or independent queue operations justify another source of state. It was not selected now because TinyProvisioner still needs PostgreSQL transactions for resource and event state, and adding a second coordination system would introduce dual-write failure modes before the project needs that scale.

### Hold a database lock during provisioning

This would prevent another worker from touching the row, but Docker and SSH calls may be slow or hang. Long transactions would consume connections, retain row versions, and increase lock contention.

### PostgreSQL advisory locks

Advisory locks can coordinate arbitrary resources but require careful key design and connection ownership. Row locks express the queue ownership directly in the job records and work naturally with ordered selection and `SKIP LOCKED`.

### Optimistic update only

An atomic `UPDATE ... WHERE status = 'queued'` can claim a known row, but workers still need an efficient way to select different ordered work under contention. `SKIP LOCKED` provides that queue-consumer behavior directly.

## Consequences

Positive:

- Multiple worker replicas can share the queue safely.
- Job, resource, and event state remain in one durable database.
- Queue ownership and failures are directly inspectable with SQL.
- No additional runtime service is required for correctness.

Tradeoffs:

- PostgreSQL availability is required for both API state and job progress.
- The system provides at-least-once, not exactly-once, execution.
- Provisioner methods must remain idempotent.
- Very high queue throughput may eventually justify a dedicated queue system.
- SQLite unit tests cannot validate row-lock behavior, so CI includes a real PostgreSQL concurrency test.
