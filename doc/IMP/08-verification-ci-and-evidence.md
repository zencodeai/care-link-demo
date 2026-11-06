# Verification, CI and trustworthy implementation evidence

## Quality lanes

| Lane | Trigger / content | Evidence limit |
|---|---|---|
| Fast local/PR | Formatting, lint, strict types, contract parity, boundary imports and deterministic unit properties | Does not prove real DB/network/model behavior |
| DB/integration | Schema/privilege/transaction/audit/outbox, missing-row races, migration upgrade/compatibility with real PostgreSQL | Separate disposable targets; mocks/SQLite cannot discharge PostgreSQL obligations |
| Actor/browser | Playwright separate contexts, real API flows, EN/FR/a11y checks, exact review and reconnect | Browser transport alone is not human connection or clinical benefit |
| Security/policy | Rego unit cases, current epoch/obligations, signals/credential replay, direct API and deployed proxy/CNI/host bypass probes | A scanner/valid YAML/test PDP is not runtime enforcement |
| AI/admission | Exact local model/tokenizer/template/schema, per-function grounding/EN-FR/attack/timeout/usefulness | Mocked generation cannot admit Gemma; no clinical efficacy claim |
| Chaos/recovery/load | Crash barriers, journal/DB partial success, uncertain send, restore promotion, cold/warm and failed-request timing | Single-host and human approval delay remain in actual measurements |

Use meaningful tests proportional to risk. Cover authoritative state/decisions and visible behavior, not the incidental implementation shape or broad snapshot churn. No arbitrary test-count/coverage threshold establishes safety. Coverage reports can reveal missing paths; critical denied effects and race outcomes are explicit assertions. Property/stateful tests target invariants such as no authority expansion, budget monotonicity, one current owner and no restored stale grant. [Hypothesis](https://hypothesis.readthedocs.io/en/latest/).

Deterministic concurrency tests pause at actual boundaries: after metadata/PDP, before/after guard, journal fsync, DB commit, dispatch consume/network store and output release. Order revoke/hold/takeover/activation in both directions, kill processes and drop replies. Assert committed rows/audit and absence of unauthorized bytes/effects, not just a returned HTTP status. Isolate parallel DB/schema/port/volume/model resources and retain seed/case identity for reproduction.

## CI and dependency ownership

CI enforces the same pinned native commands as local development, existing source/LLD contract checks and required applicable stage tests. Changed-path selection must include downstream dependencies/contracts; it cannot skip controls because an edit was labelled UI-only. Trusted classification maps authority-sensitive paths/artifacts to the source C0–C3 floor. Dependency/schema/policy changes get explicit review and compatibility checks.

Actions are pinned by immutable commit; use least-privilege token permissions and no credentials on untrusted PR execution. Hosted CI can run structural/unit/disposable integration tests where supported, but cannot prove this workstation's firewall, host LM Studio or independently served fallback. A controlled workstation test lane executes only trusted reviewed code under explicit scope. No unattended remote self-hosted execution of arbitrary PR code on the developer workstation. [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use).

Dependency scanners and image/SBOM/secret checks record exact tool/feed/artifact versions and actionable findings. Do not auto-upgrade/fix/live-patch or auto-merge high-risk changes. An exception has exact finding/scope/approver/expiry/compensating controls and cannot waive fixed exclusions. Rego policy tests supplement gateway, stream and effect enforcement. [OPA testing](https://www.openpolicyagent.org/docs/policy-testing).

## Evidence data model

Every CheckResult records command/tool/version, target/candidate, start/end, exit status or not_run/blocked reason, expected and actual outcome, evidence locator+digest, fixture/resource context and whether a mock was used. Sensitive payloads/credentials/real names are excluded from ordinary reports. Canonical application audit, local help diagnostics, screenshots, test logs and human decisions remain different evidence classes. Store synthetic replay/private evidence under explicit lifecycle/access, not public CI attachments.

Retain raw counts/missingness/failures/timeouts and distributions, not only success p95 or a green badge. Human actor usefulness/accessibility/language review remains needed alongside automated browser/axe tests. [Playwright accessibility guidance](https://playwright.dev/docs/accessibility-testing).

The [LLD verification families](../LLD/13-verification-and-traceability.md) remain the behavioral oracle. All 90 local requirements,114 source requirements/16 invariants and18 acceptance groups receive final implementation disposition at IMP-10. Earlier stage acceptance never silently closes real-world deferred/excluded scope. Allocation of operations/tasks is not implementation evidence.

Network negative evidence requires a known-active permitted control listener and a demonstrated allowed caller in the same relevant route family. Connection refusal from an absent server is not proof of a firewall rule. If LM Studio is not running, an explicitly authorized isolated probe listener can prove the host-route boundary; real gateway/model integration still requires IMP-06 evidence. No automatic model/server start follows from a failed probe.
