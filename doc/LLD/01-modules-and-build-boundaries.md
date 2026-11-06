# Modules, processes and ports

The core owns domain meaning. The data gateway is the only business-store process; it exposes named commands/projections, not SQL forwarding. An in-process core module cannot bypass the gateway. Jobs call the same command handlers with a job identity and originating authority, never a connection string. All declared ports use the DTOs and operation IDs in [contracts](02-contracts-and-protocols.md).

| Repository unit / process | Internal modules and public ports | State / dependency ownership |
|---|---|---|
| `apps/web` / static UI at edge | role routing, accessible forms, review diff, status and source display | Ephemeral view state only; no tokens, transcripts or private data in localStorage/service-worker cache |
| `services/edge` / BFF | login intents/callback, CSRF, cookie sessions, typed core proxy, SSE delivery | Encrypted server-side tokens in identity boundary; no business DB credentials |
| `services/identity` | provider adapter, account status/MFA evidence, continuation proof ceremonies, signed signal inbox | Identity DB; issuer keys and audience allowlist; role authority still local entitlements |
| `services/core` | SessionService, AssertionService, AssessmentStub, RationaleAssembler, WorkforceService, PlanService, ConsentService, DirectoryService, ReferralService, FollowUpService, TaskCoordinator, ToolBroker | Stateless workers; named commands to data gateway, PDP, inference and simulator clients |
| `services/runtime` | task snapshot interpreter, bounded planner, proposal validator | Disposable process memory; sole application peer broker; no provider/store credentials or capability tokens |
| `services/inference` | admitted-function router, context/token accounting, timeout and compute-slot ledger, host bridge client | Fixed model manifest and bounded job state through gateway; cannot call arbitrary URLs |
| `services/data` | AuthContextReader, CommandUnitOfWork, ProjectionReader, AuditAppend, OutboxLease, LifecycleRepository | Business/control/audit PostgreSQL transaction; separate narrow read/write DB identities |
| `services/control` | artifact registry, review verifier, activation and revocation coordinator, drift/containment controllers | Named data commands and host journal; no raw conversation read |
| `services/jobs` | due follow-ups, dispatch/reconcile, retention, metrics, checkpoints, timeout scans | Claim bounded jobs, then reenter owning domain handler; no standing user privilege |
| `services/simulators` | receiving inbox, handoff/channel/feed scenarios, receipt/status handlers | Separate synthetic DB/credentials; no live network connectors |
| `services/telemetry` | redacted traces/health/security counters and bounded alerts | Separate telemetry store, no request bodies or raw prompts |
| Host `help` | own auth entry, opaque request/status/accept and reconcile | Own spool and local audit; fresh identity authority per operation; no history projection |
| Host `static` | approved content manifest loader and read-only publication | No request-time auth/registry/database dependency |
| Host `recovery-control` | append/head/checkpoint, maintenance fencing, target/promotion orchestration | Journal signing key, exclusive host files and serving-generation state outside cluster volume lifecycle |
| Host `inference-bridge` / LM Studio | authenticated fixed-route proxy / pinned local generation | Only inference gateway is admitted; LM listener not reachable directly from runtime |

Every domain handler implements `handle(command, VerifiedCaller, deadline) -> Result`, where VerifiedCaller is constructed by the receiving PEP from mTLS plus current human/job delegation, never deserialized directly from an actor request. Each handler performs syntactic validation, metadata-only context lookup, PDP evaluation, final guarded transaction and result projection. Each repository port takes an exact operation ID, typed body and server authority context; generic `query`, `execute_sql` and `fetch_url` ports are absent.

## Shared dependencies

`packages/contracts` holds generated DTO/validator bindings from the LLD contract definitions. `packages/domain` contains deterministic state and fixture rules without HTTP or DB imports. `packages/policy-input` constructs the closed PDP context. `packages/rendering` encodes plain text and approved template variables. `config/demo` contains reviewed immutable manifest inputs, never credentials. `tests` separates contract, DB/race, component, deployed network and human evaluation evidence. These are planned paths, not application files created by this task.

Dependency rule: UI→BFF→core→data/PDP/inference/simulator; runtime→broker only; control→data/journal; data→business DB; identity→identity DB/provider. Private host help→identity plus own spool. Host help reconciliation→core only after recovery. Static has no reverse dependency. Telemetry is one-way redacted output, never an authorization service. Build-time acquisition is a separate maintenance plane.

The initial topology can co-locate compatible core modules but cannot merge runtime/data identities or run operator tools with data-owner credentials. Source element ownership remains mapped through HLD09 and the LLD trace matrix. Service extraction must retain the same operation identity, policy and transaction boundary, not just the same method name.
