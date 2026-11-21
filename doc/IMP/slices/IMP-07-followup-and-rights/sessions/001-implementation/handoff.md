# IMP-07 implementation handoff

G-07 is automated-qualified for the uncommitted source candidate bound in [candidate-manifest.json](candidate-manifest.json). Baseline a1be01f91d461c59669517307fd2ea5259182235 remains on the existing branch; no commit, push or deployment was performed.

Implemented explicit post-crisis anchors/contact consent/internal inbox/cancellation/outcomes, own-subject AL3 export/delete, copy graph/holds/source-bound active minimization, current disclosure and truthful retained/backup progress. UI: `/follow-up`, EN/FR. Runtime product consent, MFA and recovery authority remain enforced.

Final verification: all 38 source commands passed; 1579 Python tests passed with 3 explicit legacy skips, 207 frontend tests passed, 99 focused slice tests passed and 6 Chromium route-fixture cases passed. [Results](results.json), [automated qualification](demo-packet.json), [implementation notes](implementation-notes.md), [review trace](review-findings.md), [execution ledger](../../../../executions/2026-11-21-IMP-07/ledger.json). Earlier failures remain historical evidence; use source003, db009 and final001 as reconciled final results. The final journal-release delta is bound to the complete data-suite and static recheck.

Human usability, screen-reader, visual and language review is deferred_until_after_IMP10. Backup/recovery reconciliation and physical erasure remain IMP-09 obligations. Unknown delivery/compute, holds, other-author content and unsafe graphs stay explicitly retained. Current external holds remain conservative until committed release evidence is reconciled during recovery.

The dedicated loopback35437 database and owned Chromium/Vite fixtures were verification resources; [cleanup is recorded separately](evidence/cleanup.json). Existing demo serving remains unchanged. Pre-existing untracked research resources were excluded and untouched.

Next chat: read this handoff and the slice README, verify the source hashes and current working tree, then follow only the new user-assigned scope. IMP-08 was not activated. Any publication or deployment requires its actual authorization.

Final source reconciliation: the journal-release guard delta passed all 269 data-service tests (one existing gated legacy check skipped), plus full repository Ruff/format/Pyright. All 99 focused tests passed. The final planning README artifact digest was refreshed after its execution-status update, and the canonical planning/link validator passed.
