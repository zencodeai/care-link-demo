# Deployment, configuration, resource isolation and release

## Process and connection specification

The accepted deployment target is this workstation. Docker-built nonroot containers run in private single-node Kubernetes. Separate workload identities and least-privilege service accounts apply even when services share a node. Disable service-account token automount except the specific attestation/bootstrap interface that requires it. No privileged/hostNetwork container or broad hostPath. Read-only root filesystem, drop capabilities, seccomp/runtime restrictions, bounded tmpfs and explicit secret mounts. Product versions, CNI enforcement, storage durability, OS/CPU/RAM/GPU and host-VM routes remain admission inputs, not observed facts.

Proposed service listeners below are implementation configuration defaults, not installed ports. Each protected service exposes mTLS proxy8443 with permission-restricted Unix backend socket owned by separate app/proxy OS users and peer validation. Loopback alone is insufficient separation in a shared network namespace. Health port8081 is private, metadata-only and never a business bypass. Host public/private ports are release parameters to avoid existing services. LM loopback port and private interface are discovered/pinned; no hard-coded public `0.0.0.0` exception.

| Caller | Allowed destination / protocol | Denied or conditional |
|---|---|---|
| Authorized browser/device | private edge TLS443; identity OIDC listener; private host help; independent static | No data/PDP/runtime/management/store direct ingress |
| BFF | identity and core8443 | No DB, direct simulator/inference, user-supplied upstream |
| Runtime | broker subset of core8443 | No direct model/data/PDP/simulator/Kubernetes/internet/telemetry destination; redacted diagnostics go through broker |
| Core | data/PDP/inference/simulator8443; identity current proof | Only typed methods/peer identities, no arbitrary egress |
| Data gateway | business PostgreSQL5432 TLS; live recovery-control head8443 | DB-role grants scoped; journal read does not grant append |
| Identity | identity PostgreSQL5432; pinned Keycloak/discovery/token/JWKS endpoints | No business content DB; provider URLs not supplied by token |
| Control | named data commands; journal append/head8443; attested enforcers | No unrestricted transcript projection |
| Jobs | core/control named handlers8443 | No raw DB/connector/recipient credentials |
| Inference gateway | fixed authenticated host bridge TLS | No alternate host ports, redirects or remote inference |
| Host bridge | pinned LM Studio loopback only | No download/load/internet APIs; block direct runtime access |
| Simulators | own DB and explicit response paths | No live partner/internet routes; generic emergency target has no business path |
| Host help | current identity authority8443; own local spool; explicit recovery reconciliation→core | No core policy/audit/registry as private-help prerequisite; identity outage disables private help |
| Host static | reviewed local content | No request-time auth/registry/model/DB/control dependency |
| Recovery-control | explicit backup/restore target administration under maintenance identity | No normal business-content serving; restore-worker cannot approve promotion |
| Telemetry | scoped collector/store | Content-free bounded metrics; cannot issue permissions |

Default-deny ingress/egress at CNI AND host boundaries. Necessary DNS goes only to constrained resolver; runtime uses broker service identity routing and cannot use DNS as arbitrary external egress. Restrict IPv4 and IPv6 equally; disable/block untested family. Host proxy authenticates attested gateway identity, not merely a NAT source IP. Verify every allowed call plus direct-backend, alternate-port, DNS/redirect and control-plane bypass denial. YAML acceptance does not establish enforcement. Cost/rotation/host integration comparison with a full mesh remains DEC-01 qualification.

## Config, artifacts and secrets

The closed ReleaseManifest type in [contract definitions](contracts/definitions.schema.json) defines activation inputs. One immutable release manifest binds application/image/source/contract/migration digests, product/version pins, model artifact/quantization/license/template/tokenizer, prompt/tool/policy/directory/content artifacts, CNI/proxy/issuer/host routes, approved configuration, reviewer receipts and compatibility. Startup validates schema, signatures/digests and fixed prohibitions before private admission. Unknown/null pins cannot be treated as installed defaults. Environment substitution cannot expand destinations/roles/population. Configuration reload is a classified reviewed activation, not a mutable ConfigMap watched directly into authority.

REQ demo-parameters remains the authoritative numerical target catalog. [Implementation defaults](implementation-defaults.json) adds labelled proposed parser/lease/queue/resource settings without modifying REQ. Validate relational constraints: output reserve fits context/window; all deadlines finite; security expiry uses real time; queue limits positive; no unknown policy obligation; current epoch/barrier mandatory; no positive permission cache; same-host independence false; fixed no-police/emergency/data/production flags cannot change. Unknown host limits block resource acceptance, not documentation.

Mounted secret files contain DB credentials, BFF/provider secrets, signing/key references and encrypted-store keys. Keys never enter git/images/browser/prompts/ordinary logs. Separate DB/data, identity, journal, proxy issuer, release signing, audit reader, backup and approver custody. Encrypt volumes/backups/temporary export/replay with reviewed key custody; select vetted authenticated encryption implementations and record key ID/nonce/tag in encrypted object envelope. Never claim PostgreSQL provides transparent encryption by merely choosing it. Rotation must preserve authorized decryption of retained copies and revoke inappropriate access; key destruction must respect holds/dependencies and is not universal physical-erasure proof.

## Startup, readiness and shutdown

1. Independent host static/help/journal/bridge processes start under separate OS identities and files; static verifies approved content locally. No fictitious crisis contacts are published. Unverified fallback content blocks participant-use release, while design/testing can continue with non-service placeholders labelled unavailable.
2. Verify clock/trust/journal continuity/storage, identity provider/account policies and DB schema compatibility. Data/control load current serving generation, barrier, policy bundle and enforcer ACKs. Missing current authority stays quarantined.
3. Admit protected manual capability only after current identity, PDP, DB/audit append/read and current barrier checks. Exercise separate-participant→human request→worker acceptance smoke with honest connection states.
4. Admit each AI function separately after exact model manifest and capability evidence; model failure removes only AI readiness. Inference queue cannot delay manual/help admission.
5. Readiness exposes capability, reasons, effective epoch and serving generation; liveness says only process alive. Private help readiness requires current identity and own spool, static has independent content health.

Shutdown removes new-work readiness, fences new effect authorization, stops lease claims, drains bounded requests (proposed 10seconds), persists unresolved/unknown operations and closes streams with reconnect status. Inference cancellation fences output without assuming compute stopped. Do not end unresolved client sessions. Independent help/static/journal remain running unless explicitly stopped; no installer or host action is performed by this document.

## Pools, quotas and delivery

Reserve separate executors/pools: proposed manual16 in-flight, urgent/human-help4 additional, background4; DB gateway pool8 plus2 maintenance connections; runtime2 and inference max 2 queue8 per existing parameters. Per-account input bucket proposed 30 requests/minute burst10, turn burst5; dedicated human-request idempotent command has separate bucket10/minute and never waits for inference. Enforcement before costly parse/compute; denial cannot automatically abandon accompaniment. Quotas are hypotheses to measure at 10 active sessions, not proven capacity. Memory/CPU/GPU requests and file descriptor/disk limits require host inventory.

Build immutable images/dependency locks/SBOM in maintenance plane; no runtime auto-download/update. Expand/backfill/contract migrations and compatible artifact bundles retain last-known-good demo. Candidate gets independent fixtures/smoke, no duplicate live dispatch. If host cannot fit parallel stacks, use bounded compatible phased replacement and independent fallback. Traffic switch requires current serving generation and reviewed rollback. Rollback is newer activation preserving newest restrictions; schema downgrade that loses data is not a routine rollback. Planned command names (`validate`, `build`, `migrate`, `seed-demo`, `smoke`, `status`, `stop`, `restore`) must be implemented with explicit demo target safeguards; no working CLI/manifests are claimed here.

Static publication has its own host-admin listener, authenticated operator and exact independent content-review receipt. Verify content bytes/digest, locales, verification/review dates, signature and fixed no-private-data rules locally; stage a new read-only directory, fsync and atomically replace the local current-publication pointer. Startup retains only a valid last-reviewed bundle, never reads runtime registry at request time. Publication rollback selects another currently valid reviewed bundle. Missing or overdue independent review is visible and blocks participant-use acceptance; do not replace real crisis content with generated fictional contacts.

Local custody defaults: help spool directory 0700/files 0600 under help OS identity; recovery journal/key directories 0700 under a distinct recovery-control identity; application/proxy Unix sockets permission-restricted to their exact peer identities. These are proposed implementation permissions, verified against the actual host/service manager before admission. SQLite has no PostgreSQL GRANT model; its access boundary is OS ownership plus the typed help service.

The selected model is `google/gemma-4-12b-qat` in host LM Studio (download user-reported). Accepted recommended choices and starting defaults are documented in the [acceptance record](decisions/2026-11-06-implementation-choices-and-model.md); proposed/default terminology in mechanism descriptions is not evidence of installation or measurements. Null product/resource/account-period inputs still need explicit completion.
