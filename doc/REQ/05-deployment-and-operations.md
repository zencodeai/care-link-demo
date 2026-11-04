# Local deployment and operations

> Scope update (2026-11-04): [Decision answers](08-open-decisions.md) and [demo parameters](demo-parameters.json) establish Ottawa/Ontario context and exclude all police roles, brief sinks, connectors and partnerships from the proposed demo. Earlier police-specific descriptions below are retained only as historical source context and are superseded for implementation; they do not imply a police relationship. Source FR-C6 and AQ-9/AQ-26 are excluded by current user scope, not satisfied. Concrete defaults replace earlier open engineering choices; clinical/legal approvals and hardware-dependent checks remain unresolved.

Sources: user requirements; HLD §12; FRS NFR-1…9, 17…20. This section specifies desired deployment behavior, not the current host state. No host services, cluster, model installation, network policy, hardware capacity or credentials were inspected or changed.

## Host and container requirements

**TR-OPS-01.** SHALL deploy demo application, all actor UIs, deterministic services, stores, audit and simulators on the user's system using Docker images and Kubernetes. LM Studio SHALL run locally on the host as the explicit inference exception; containerized application services SHALL use the constrained inference adapter. No remote inference fallback. Before build, inventory OS/CPU architecture/RAM/GPU, available disk, Docker runtime, Kubernetes distribution, ingress/ports, storage class, network-policy support and host routing (D-01).

**TR-OPS-02.** SHALL keep reproducible Docker builds and Kubernetes manifests/overlays in source, with pinned dependencies/images, non-root containers, minimal privileges, probes, resource requests/limits, persistent volumes, service accounts and restricted ingress. Proposed repository organization: `apps/web`, `services/api`, `services/runtime`, `services/audit`, `services/simulators`, `packages/contracts`, `config/demo`, `deploy/k8s`, `tests`, `doc`. Framework/language/runtime versions require D-05; no arbitrary stack is a source mandate.

**TR-OPS-03.** SHALL expose separate role routes and private demo entry points, backed by server-side access checks. Only static fallback may have an unauthenticated/public listener. Use explicit allowlists for cluster-to-host inference traffic; deny runtime direct inference, business databases, internet and simulator traffic. A cluster accepting NetworkPolicy YAML is insufficient evidence: run actual allowed/denied probes, including external DNS/HTTP and host alternate ports.

**TR-OPS-04.** SHALL isolate local demo from historical production checkout, volumes, namespaces, secrets and ports. No reusing abandoned private keys, authentication sessions, policy approvals or database contents. Demo seed/reset SHALL operate only on explicitly named demo resources, be idempotent and refuse non-demo targets. Preserve external role logins and audit records unless a specifically documented reset includes them.

## Startup and usable-system requirements

**TR-OPS-05.** SHALL provide documented commands for prerequisites, configuration validation, image build/load, cluster deploy, migration, fixture seeding, start/status, smoke test, stop and demo-only reset. Startup SHALL validate model identity/availability, migrations, policy/artifact bundle, database and audit readiness. Dependency failure SHALL produce an actionable operator status and retain fallback; it SHALL not display a ready system with nonfunctional actor flows.

**TR-OPS-06.** SHALL support health/readiness distinctions and safe graceful shutdown. Do not accept consequential work before audit/storage readiness. Bound and drain in-flight requests, preserve pending operations and reconnect state. Migrations SHALL use reviewed backward-compatible expansion/contraction or explicit maintenance of the live demo path. Document rollback behavior for data migrations that cannot be reversed.

**TR-OPS-07.** SHALL use a last-known-good release bundle, candidate deployment and smoke tests before switching live demo traffic. Failed checks SHALL retain/recover the last-known-good version. Always usable means a working accepted baseline plus independent fallback during intentional failures; it cannot guarantee operation while the only host is powered off. No automatic claim of FRS monthly availability or session RPO/RTO from single-node setup.

## Failure and recovery

**TR-OPS-08.** Kill SHALL disable new agent actions and affected tools, cancel pending model output, retain access to static guidance and an ungated human-help path, preserve audit history and show safe-mode status. It SHALL not require successful inference, directory lookup or business policy evaluation to request help. D-02 must specify the safe-mode contract and caller path before integration; test kill during every consequential workflow.

**TR-OPS-09.** Static fallback SHALL be a separate content artifact, host process/container, listener and publication path independent of Kubernetes/runtime authentication, registry, database, directory and kill controller. Host-local isolation can demonstrate application/cluster failure survival; it cannot demonstrate whole-host/account/DNS independence in HLD §12.5. Document that residual explicitly; any full independent hosting requires a separately reviewed environment decision (D-07).

**TR-OPS-10.** SHALL back up persistent state with explicit encryption, schedule, retention and recovery instructions. Restore into an isolated demo target, verify schema/version, audit-chain integrity, consent revocations/deletions and pending-side-effect reconciliation before accepting traffic. Backup success without a restore drill is insufficient. Actual local RPO/RTO SHALL be measured; required FRS targets remain ≤1-minute session RPO and ≤5-minute RTO for a future conforming deployment.

## Performance and observability

**TR-OPS-11.** SHALL measure source budgets separately: first response ≤2 seconds p95; first actionable step/question ≤5 seconds p95; hazard recognition ≤5 seconds from relevant input; provisional acuity ≤90 seconds p95 where interaction permits; plan retrieval ≤10 seconds p99; human connection initiation ≤10 seconds p95. An acknowledgement SHALL not be counted as an actionable safety step. Initiation SHALL not be reported as a connected human. LM Studio generation latency SHALL be reported separately, with deterministic urgent paths independent of it.

**TR-OPS-12.** SHALL declare a demo load envelope before performance acceptance: concurrent active sessions, arrival rate, transcript size, model context/output cap, channel mix, sample size, warm/cold inference, hardware and percentile method (D-06). Report failures and timeouts with latency, not only successful requests. Queue inference with bounded concurrency/backpressure; never silently swap to a remote model. Numeric clinical, queue, kill, retention and alert thresholds SHALL remain open until approved or explicitly labelled fixture-only.

**TR-OPS-13.** SHALL expose correlated logs/traces and dashboards for session state, dependency health, generation latency, denied actions, queue age, handoff failures, audit lag/commit failure, storage/backup and artifact versions. Health UI SHALL distinguish simulator status, real participant login infrastructure, non-clinical output and future production obligations. Establish runbooks for model-down, audit-down, poisoned feed, contaminated data, partner outage, revoked credential, lost host connectivity, rollback and restore.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
