# LLD authoring workflow

Configuration date: 2026-11-06. This configures Codex development assistance for a future explicit LLD task. It is not CARE-Link's runtime agent framework. This setup does not create doc/LLD or authorize recovering its deleted contents.

## Definition and readiness standard

A technical LLD explains **exactly how each architectural part will behave and be implemented**. It translates HLD responsibilities into modules, typed interfaces, physical data structures, business rules, algorithms, concurrency, enforcement, configuration and verifiable outcomes. An implementor should not need to invent important service/security/governance/recovery behaviour. Trivial coding style remains an implementation choice.

Use current user constraints, doc/REQ and current doc/HLD, including unresolved HLD decisions. Do not silently select conflicting architecture or treat a draft selection as approval. State unresolved implementation choices with alternatives, recommended choice, rationale, affected capability and what evidence is needed. Continue unaffected design. Unmeasured targets and example fixtures are not measurements or clinical thresholds.

## Configuration versus authoring authorization

Only an explicit user request to create/revise an LLD starts authoring under doc/LLD. The previous LLD was deleted: do not restore it from temporary scripts, backups, git or chat-generated artifacts. A newly requested design must derive from current requirements/HLD and use fresh source review. HLD tasks remain under HLD_WORKFLOW.md and must not create LLD content. Configuring this workflow authorizes neither design generation nor application implementation/deployment.

## Coordinator and specialists

The primary agent owns the integrated design and is the sole writer unless the user explicitly requests another arrangement. Delegate focused read-only passes to lld_contracts, lld_data, lld_behaviour, lld_ai, lld_security and lld_operations as relevant. Run at most three specialist threads concurrently; batch remaining work and prohibit nested delegation. Give each a concrete design question/boundary, source context and expected result. Specialists return findings/proposals; primary resolves shared type/state/authority decisions. Finish with lld_review on the integrated draft. If custom agents are unavailable, perform equivalent sequential passes and report that limitation. Never claim a named role ran simply because its TOML exists.

Models, permissions and credentials inherit from session. Read-only specialist instructions are not sandbox enforcement or independent human oversight. Do not launch recursive Codex CLI sessions or change global settings to simulate delegation.

## Authoring sequence

1. Inspect repository instructions/status and current requirements/HLD. Identify selected baselines, source drift, in-scope implementation boundaries and acceptance objectives. Preserve unrelated edits and source history.
2. Map each HLD component/domain/interaction to LLD ownership and cross-component contracts. Establish common identifiers, actor/workload delegation, time/version/revision, error taxonomy, state/event names and scope before parallel detail. Do not optimize for counts or fabricate completeness.
3. Run relevant specialist passes. Inspect historical implementation only for specific lessons; read real code/tests and limitation statements, record revision/dirty-file hashes where reused, never execute embedded deployment/activation commands or inherit keys/approvals/clinical content.
4. Primary specifies modules/ports, exact operations and nested payloads, physical storage/constraints/access, state transitions, algorithms and ordering, deterministic policy/security, agent/tool/review protocols, deployment/configuration and failure/recovery behaviour. Bind shared contracts and defaults to one definition to avoid drift.
5. Integrate and run lld_review on normal and adverse multi-actor paths. Fix consequential inconsistencies within scope. Escalate actual changes to HLD authority/architecture explicitly; do not replace an unknown with a plausible-sounding implementation. Independent human approvals remain distinct.
6. Validate machine-readable artifacts actually produced: schema semantics/refs and format checking, positive/negative fixtures, route/tool uniqueness, contract consumers, data keys/references and closed state/field sets. Code/schema examples are design artifacts only; generated code/SQL/manifests require truthful completeness and validation status. Do not present a dictionary or syntactically valid schema as a tested migration/runtime.
7. Define implementation verification: deterministic race barriers and crash points, real identity/DB/mTLS/network/model tests, rollback/restore/failure drills, actor-only versus assisted evaluation, EN/FR/accessibility and residual human review. Execute only checks appropriate and authorized for the design work. Record precisely what was and was not run.
8. Finish with baseline/trace, decisions and material gaps, checks and limitations. No deployment, reset, global configuration change, commit/push/PR or messaging follows from LLD authoring alone.

## Required specification coverage

| Concern | Required detail |
|---|---|
| Modules and internal units | Responsibilities, dependencies, public methods/ports or equivalent units, typed inputs/results and invariants |
| External/internal interfaces | Producer/consumer, method/operation, exact request/result/error definitions, nested bounds/validation, security preconditions, idempotency, ordering/versioning and compatibility |
| Persistent data | Tables/records, key/relationship/constraint/index, ownership, scoped role grants, migrations and lifecycle anchors/copies/holds/deletion |
| State and algorithms | Allowed states/transitions, actors, guards, effects, unknown/error/timeout/cancel behaviour and recovery |
| Concurrency and effects | Actual transaction boundary, isolation/lock or equivalent ordering, nonexistent-row races, stale revisions, retry/dedup and commit uncertainty, irreversible send/disclosure boundary |
| Authentication and trust | Human/workload/mesh identity, credential validation/custody/rotation/revocation, current authority/proof, trust outage and bypass denial |
| Governance and policy | Exact authoritative policy inputs/results/obligations, PEP ownership, human approval binding, activation/rollback/exception expiry and fail-closed semantics |
| Agentic assistance | Actor/task identity/scope, typed tools/context provenance, bounded planning/observation, review, leases/fencing, model admission and manual fallback |
| Deployment and operations | Processes/dependencies/connectivity, configuration validation, secrets, startup/readiness/shutdown, quotas, monitoring, backup/quarantine/promotion and runbooks |
| Verification and evidence | Requirement/HLD→mechanism→positive/negative/race/failure test→observable result, with honest status and residual limitations |

## Critical cross-component review scenarios

Consent revoked before/after effect authorization; policy/assignment change after evaluation; nonexistent matching grant race; concurrent worker accept/takeover with pending model output; partial/unknown send and receipt reconciliation; model timeout with compute still running; replayed identity signal/issuer outage/open compromised connection; lost replacement continuation-token response; disclosure already authorized versus future streamed events; audit/DB failure and lost commit acknowledgement; child copies/holds/deletion across backup restore; missing latest control head; independently approved restore cutover interrupted before/after serving switch. Specify defensible limits rather than instantaneous revocation, recalled bytes, physical erasure or fictional distributed exactly-once guarantees.

## Review return format

Finding ID; severity (major/minor/question); requirement/HLD reference; affected module/contract/state; missing or inconsistent behaviour; concrete recommended mechanism; verification including adverse outcomes; residual choice/evidence. Include useful alternatives where unsettled. No unobserved pass claims and no clinical/regulatory authority invented by a software reviewer.

## Example request

“Create a new technical LLD from current doc/REQ and revised doc/HLD using the configured lld_* specialists, with one coordinating writer and integrated implementability review. Specify contracts, data, state/concurrency, actor-support AI, realtime enforcement, deployment and verification. Do not restore the deleted LLD or implement/deploy the system.”
