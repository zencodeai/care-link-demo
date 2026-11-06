# Verification obligations, traceability and evidence

The [trace matrix](traceability.json) maps every local requirement and source element to LLD mechanism chapters and test families. Original114 source requirements/16 invariants and 53 question dispositions remain linked and retain exclusions/deferred claims. Mapping counts are design navigation, never test coverage or source conformance. All implementation tests below are `not_assessed` until an implementation supplies reproducible evidence.

## Required test families and deterministic race barriers

| ID | Mechanism / setup | Observable positive, negative and failure outcomes |
|---|---|---|
| VT-01 | Admission/disclosure/actor clients | Separate browser identities and personas; missing/wrong tags/role/jurisdiction prohibited action denied; EN/FR disclosure limits; no hidden role upgrade |
| VT-02 | OIDC/identity proof | Wrong iss/aud/azp/nonce/kid/alg/time/redirect/state, duplicate callback, exchange timeout, unavailable keys deny; fresh scoped step-up works; two accounts same human cannot self-approve |
| VT-03 | Continuation recovery | Consume token then drop replacement reply; same-key status gives replacement_unavailable; fresh own-principal AL1 recovery revokes family; stolen/expired token/other-account/metadata recovery denied |
| VT-04 | Intake and deterministic escalation | Capture/unknown/deferred/conflict/correction, hazard before model, no model-tier authority; disagreement/decline separate; youth/coercive guardian negatives; 30min silence never closes unresolved support |
| VT-05 | Queue/worker ownership | Pause two workers after ticket read; unique reservation/owner wins; accept not connected; transfer drop preserves support; pause old model/message at release, takeover, resume→old output absent |
| VT-06 | Consent and dispatch | Pause after PDP then revoke/expire/change subject/source/assignment/policy; final authorization denies stale effect. Test nonexistent grant creation/revoke under parent guard. Before-vs-after authorization produces documented in-flight semantics |
| VT-07 | Unknown delivery | Crash before intent, after DB authorize, after consume, after receiver store, before local receipt; stable dispatch lookup dedups; no blind retry/new effect; partial/unavailable receipt never “connected” |
| VT-08 | Agent state/budget/lease | Concurrent claims/reclaim old fence, malformed proposal retry/restart, tool budget exhaustion, scope/recipient/authority injection; shared counters never reset and no partial proposal effects |
| VT-09 | Real local model admission | Exact Gemma/LM Studio/tokenizer/template identity and schema roundtrip, context/output bounds, EN/FR/ambiguous/adversarial functions; timeout ignoring cancel keeps compute slot unknown and manual path usable |
| VT-10 | Policy/activation/exception | Unknown inputs/obligation or REQUIRE_HUMAN denies; stage/ACK/restart boot mismatch; restrict during paused permit; relaxation without independent review denied; expired exception/old rollback cannot revive rights |
| VT-11 | Audit/DB atomicity | Inject audit append failure and commit-ACK loss; no accepted state/outbox/private result without durable audit; same logical key resolves; hash/sequence/concurrent append and scoped-reader negatives |
| VT-12 | Identity events/mTLS/network | Forged/replayed/stale/gapped events; lost notification still current check; compromised open connection fenced. Direct runtime→DB/PDP/simulator/LM/host ports/internet/Kubernetes/DNS/IPv6 bypass denied by actual probes |
| VT-13 | Rights/retention/copies | Closure/retirement/capture anchors; unknown parent/cycle/hold; active plan source expiry; own AL3 export excludes other reports; deletion24h/backup7d target measured with retained exceptions; restore cannot resurrect |
| VT-14 | Journal partial success | Crash before/after fsync, DB update/commit/ACK; terminal ACK does not advance barrier; intent-ahead DB blocks live auth; restrictive replay denies, relaxation intent alone never grants |
| VT-15 | Restore promotion | Old backup+latest revoke/delete/hold; missing/corrupt/rolled-back head blocks; change head after approval invalidates; crash after old fence/router switch/target enable leaves at most one admitted generation and no duplicated dispatch |
| VT-16 | Independent help/static | Edge/core/PDP/audit/model down with identity healthy allows narrow fresh help; identity down→static only; receipt replay/body swap/competing acceptance denied; reconcile dedups and never imports connection |
| VT-17 | Release/operations/load | Startup wrong digests/schema/clock, candidate rollback current rights, graceful shutdown, saturation with reserved manual/help; timed cold/warm/error distributions at declared10-session workload |
| VT-18 | Actor usefulness/accessibility/metrics | Full carer→worker→receiver→follow-up with all suggestions rejected and AI failure; matched assisted baseline and seeded reviewer errors; EN/FR keyboard/screenreader; coupled metrics, suppressed cohorts, no individual exposure/export |

Race tests use deterministic barriers immediately before/after authority read, guard acquisition, journal fsync, audit append, DB commit, effect consumption/send/receiver-store and output release. Start competing revoke/takeover/hold/activation at each barrier, release in both orders and assert durable state, canonical audit count and absent forbidden bytes/effects. Sleep-based timing alone is not a race proof. Inject process death and lost acknowledgements, not only thrown exceptions. Use real PostgreSQL transaction/privilege tests and deployed mTLS/CNI/host probes; mocks cannot discharge those obligations.

## Evidence and execution layers

Design validation checks local links, unchanged input hashes, complete $refs, closed nested schemas, OpenAPI structural validity, unique routes/tool discriminants, positive/negative and semantic fixtures, state closure, operation→type references and trace integrity. It does not execute FastAPI handlers, migrations, Rego, OIDC/mTLS, model or network routes. No SQL/manifests/application code are generated or deployed here.

Implementation evidence records commit, exact artifacts/config/host products, reviewer roles, fixture seeds/cases, expected and actual results, failures/timeouts/missingness, raw counts/distributions and timestamped canonical/local evidence references. Independent human/specialist release review remains distinct from development AI review. Critical authority/containment failure blocks affected demo admission; clinical/legal/community production obligations remain unsatisfied by synthetic tests.

See [validation record](design-inventory.json) for checks actually run on this package and residual decisions. The validator can be rerun without access to a live cluster, identity provider or model. Validation dependencies are tooling-only; no runtime stack version is implied.
