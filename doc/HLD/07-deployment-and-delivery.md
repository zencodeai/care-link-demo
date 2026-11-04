# Local deployment, build and delivery

## Proposed host topology

One Ottawa-hosted computer runs a Docker-capable local Kubernetes environment, host LM Studio, and an independent host static/help-spool environment. The OS/CPU/RAM/GPU/disk, Kubernetes distribution/CNI, private DNS/ports, trusted certificates and host-to-VM routing are not inventoried. Select a distribution only after demonstrating enforceable NetworkPolicy and restricted host reachability; do not infer safety from manifests being accepted. No installation or host configuration is performed by this HLD.

Namespaces: `care-demo-edge`, `care-demo-core`, `care-demo-ai`, `care-demo-control`, `care-demo-data`, `care-demo-sim`, `care-demo-observe`. Unique service accounts and mTLS identities per workload; no default token automount except narrowly required controllers. Resource limits, non-root user, read-only root filesystem, dropped capabilities, restricted volumes, startup/readiness/liveness and graceful termination are mandatory. Identity has persistent data separate from business restore. Proposed minimal replicas are one per deployable; OPA can run alongside control initially with authenticated API and central fencing. No production availability claim.

Host inference is behind a dedicated authenticated TLS bridge if LM Studio’s selected deployment cannot satisfy the required trust boundary directly. Permit only inference gateway source/network and pinned bridge destination; bridge forwards exclusively to the host’s local LM Studio listener. Never expose the model server on all interfaces for convenience. Verify VM NAT/source behavior, redirects, DNS, alternate ports and IPv6. The host listener port and route are admission parameters, not hardcoded assumptions.

Fallback runs outside the application cluster with static signed/verified content bundle, its own listener and review/publication process. It reads no registry, identity or business store at request time. Human-help spool lives independently of core storage/policy, with restricted file permissions, bounded disk capacity, expiry and local audit diagnostics. Logical help-gateway Kubernetes deployment may be replaced by an independent host container/process to satisfy cluster-loss help acceptance; this HLD selects the host process for the minimal gateway/spool. The full workforce console still depends on browser/network/auth; fallback remains available if cluster help UI is lost. No same-host design survives host power/storage failure.

## Repository structure

| Path to implement | Contents |
|---|---|
| `apps/web` | Actor routes, accessible components, human review and event client |
| `services/edge` | BFF/OIDC sessions, channel mapping and private ingress |
| `services/core` | Domain modules, broker, deterministic task and state coordination |
| `services/runtime` | Untrusted stateless proposal worker |
| `services/inference` | Pinned host adapter and bounded capacity |
| `services/data` | Scoped repositories/commands, migrations and audit functions |
| `services/control` | OPA policies, activation/revocation, signal adapter |
| `services/help`, `services/simulators` | Minimal independent help and isolated doubles |
| `packages/contracts` | Normative schemas, generated types, positive/negative fixtures |
| `config/demo`, `deploy/k8s`, `deploy/host` | Validated config, manifests/overlays, fallback/bridge/help templates |
| `tests`, `tools`, `doc` | Contract/integration/adversarial/evaluation/drill tooling, operator docs |

These paths are design targets; only documentation currently exists. Keep domain interfaces independent of network framework. Separate modules for session/assertions, plans/consent, directory/content, queue/handoff, referral/follow-up, tasks/reviews, control/audit/metrics. Avoid a generic agent with unrestricted repositories.

## Build, secrets and bootstrap

Pin supported dependency/runtime/image versions and hashes after compatibility/security checks. Build reproducible multi-stage Docker images with minimum runtime assets; scan dependencies/images/IaC and secrets, produce SBOM/provenance. Offline artifact intake/download is an operator maintenance action, not runtime egress permission. Runtime model/prompt/config/image identity is bound in the signed release manifest.

Bootstrap order: validate host/resources and approved demo profile→trust issuer/identity/secrets→persistent storage/migrations→control/audit/data→help/fallback verified bundle→core/jobs/simulators→edge/actor credentials→runtime/inference admission→smoke. Readiness can report manual-only while AI disabled; consequential functions require healthy enforcement/audit. Separate account provisioning from fixture seeding; never seed shared production passwords. Generated one-time credentials are delivered securely, rotated and never checked in.

## Human-reviewed rollout

HLD creation does not change GitHub settings or modify the open requirements PR. Implementation uses small reviewed PRs and required checks. Candidate release manifest binds commits, schemas/migrations, dependency/model/prompt/policy/config/directory/content digests and reviewer receipts. Independent human approval is distinct from signing/CI execution. If reviewers are unavailable, preserve candidate status without self-approval.

Use last-known-good and candidate app releases; bootstrap is the one exception before an accepted baseline exists. Smoke candidate against isolated demo fixtures, compatible schema and simulator routes; switch private ingress only after checks. Single-node memory may not support duplicate full stacks: use shared approved backwards-compatible services or stop candidate admission rather than disrupting baseline. Rollback chooses a compatible approved artifact set and a new governance epoch, preserves revoked state, fences old writers and reconnects streams. Forward migrations use expand/contract; destructive changes need an explicit recovery window/design, not an assumed down migration.

[NetworkPolicy documentation](https://kubernetes.io/docs/concepts/services-networking/network-policies/), [Keycloak OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers) and [OPA bundle lifecycle](https://www.openpolicyagent.org/docs/management-bundles) support selected mechanisms; they do not prove the local distribution, CAEP capability, bundle signature algorithm support or current runtime configuration. Ed25519 release-manifest verification is application-owned; do not assume OPA natively accepts that signing format.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
