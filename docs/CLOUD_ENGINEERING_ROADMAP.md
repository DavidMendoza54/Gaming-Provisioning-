# Cloud Engineering Project Roadmap

This roadmap turns TinyProvisioner into a portfolio project that demonstrates how software is built, secured, deployed, observed, and recovered. Each phase has a learning outcome and concrete evidence that can be shown in an interview.

## Phase 1: Continuous Integration

**Status:** Complete. Local validation and GitHub CI both passed before merge.

Learn:

- CI compared with continuous delivery and continuous deployment
- Ephemeral runners and reproducible builds
- Least-privilege workflow permissions
- Automated quality gates and build artifacts
- Dependency update automation

Evidence:

- Pull-request quality checks
- Test and coverage artifacts
- Successful Docker image build and HTTP smoke test
- CI/CD learning guide

## Phase 2: Reliable Job Processing

**Status:** Complete. Real local PostgreSQL concurrency and GitHub CI both passed.

Learn:

- Race conditions and database locking
- At-least-once delivery and idempotency
- Retries, exponential backoff, and dead-letter jobs
- Heartbeats and abandoned-job recovery
- Graceful worker shutdown

Evidence:

- Multiple workers cannot claim the same job
- Failed jobs retry according to a documented policy
- Integration tests prove crash recovery
- Architecture decision record explains the queue design

## Phase 3: Observability

**Status:** Complete. The full stack, scrape targets, alert rules, and provisioned dashboard were validated live with Docker Compose.

Learn:

- Structured logs, metrics, and traces
- Service-level indicators and service-level objectives
- RED metrics: rate, errors, and duration
- Alert design and symptom-based monitoring

Evidence:

- Prometheus metrics endpoint
- Grafana platform dashboard
- Alerts for API failures, worker health, and queue depth
- Version-controlled dashboard, learning guide, ADR, runbooks, and failure labs

## Phase 4: Infrastructure as Code

Learn:

- Terraform state and the plan/apply lifecycle
- Reusable modules and environment boundaries
- Cloud networking, IAM, compute, managed databases, and DNS
- Cost estimation and budget controls

Evidence:

- Reproducible development cloud environment
- Remote encrypted state with locking
- CI validation for formatting, plans, and policy checks
- Architecture and monthly cost diagrams

The cloud provider will be selected before this phase so the design supports the jobs being targeted instead of hiding provider concepts behind premature abstraction.

## Phase 5: Container Delivery

Learn:

- OCI registries, tags, and immutable digests
- Software bills of materials and provenance
- Vulnerability scanning
- Environment approvals and rollback
- Workload identity instead of long-lived cloud credentials

Evidence:

- Versioned image in a container registry
- Security scan and SBOM attached to the release
- Development deployment after CI succeeds
- Manual approval before production
- Tested rollback procedure

## Phase 6: Kubernetes Deployment

Learn:

- Deployments, Services, Ingress, and Helm
- Readiness compared with liveness probes
- Requests, limits, autoscaling, and disruption budgets
- ConfigMaps, Secrets, and network policies

Evidence:

- Local Compose remains the developer path
- Helm chart is the clustered deployment path
- Safe rolling update and rollback demonstration
- Worker and API scale independently

## Phase 7: Backup, Recovery, and Reliability Exercises

Learn:

- Recovery point and recovery time objectives
- Database backup and restoration
- Failure injection and incident response
- Blameless postmortems

Evidence:

- Automated database backup
- Regular restore verification
- Disaster-recovery runbook
- Recorded failure experiment and postmortem

## Definition of Done for Every Phase

A phase is complete only when:

1. The feature works.
2. Automated checks prove the important behavior.
3. The security and failure modes are documented.
4. A learner can explain the request or data flow in plain language.
5. The README links to visible evidence.

This definition prevents the project from becoming a list of technologies without demonstrated understanding.
