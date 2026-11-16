# IMP-03 — Protected manual client-to-worker service

**IMP-03 closed on 2026-11-16, with G-03 accepted for the reviewed private synthetic candidate.** [Execution ledger](../../executions/2026-11-16-IMP-03/ledger.json). [Human acceptance record](sessions/005-review-recovery-implementation/G-03-acceptance.json). Participant admission and IMP-04 remain inactive.

Final implementation and handoff: [session005 recovery/toolkit implementation and verification](sessions/005-review-recovery-implementation/README.md), based on [session004 design](sessions/004-review-recovery-design/README.md). The accepted implementation is deployed to the continuation lab; three successive fresh Chrome runs passed in one profile, without cookie/cache clearing or retries.

Prior qualification: [session003 index](sessions/003-live-qualification/README.md), [status](sessions/003-live-qualification/qualification-status.md), [handoff](sessions/003-live-qualification/handoff.md). The [archive index](sessions/003-live-qualification/archive/README.md) locates prior attempts, the last qualification packet and unchanged approval receipts.

Current verification: 738 Python tests, 81 web tests, real isolated TLS provisioning, eight English/French accessibility scans and three complete Chrome cycles. See session005 for the exact results, current toolkit environment and fresh human-review tabs. Earlier observations and source counts remain historical evidence in session003. The current user decision records performed and approved human acceptance against the session005 candidate.

Canonical allocation: IMP-03, tasks IMP-03-A/B/C/D, gate G-03, dependency G-02 explicitly accepted. The canonical planning baseline remains unchanged. The user separately authorized source publication on `feat/imp-03-protected-manual-service` against `main`; original accepted candidate bindings remain preserved.

Implementation ownership: apps/web/src/review and manual; tools/demo; services/core manual transport; services/data; services/identity manual recovery; packages/domain and policy-input; host/recovery-control; bounded contract/build/verification tooling. See the [data gateway](../../../../services/data/README.md) and [core boundary](../../../../services/core/README.md).

Historical sessions: [001 implementation](sessions/001-implementation/handoff.md), [002 runtime completion](sessions/002-runtime-completion/handoff.md), [002 validation guide](sessions/002-runtime-completion/G-03-validation-guide.md). The guide's independent-infrastructure prerequisite was superseded for the explicitly accepted bounded Option B profile; it is not the current status.

The original Option B target and its generation1 fence remain retained. Continuation uses shared SPIRE/Keycloak with a separate state domain. No sibling changes, fence reset, HLD/LLD rewrite, commit/push or next-slice authority follows from these records.

Closeout is administrative: the demo resources and working tree are retained. There is no remaining IMP-03 implementation work within the accepted scope. Any next slice starts with a separate instruction/chat and the accepted ledger and handoff above.
