# Integrated review and reconciliation

imp_controls and imp_python implemented disjoint backend paths; imp_web implemented the actor UI. imp_review performed three read-only integrated passes, with no nested delegation. Primary integrated shared contracts/transports, policy, locking, inline fences, source evidence and fixes.

| Finding | Resolution and automated regression |
|---|---|
| Review expiry during canonical audit could commit activation | Final review/authority/signer recheck; injected expiry rolls back DB activation even after journal intent |
| Broad path prefixes classified unknown/authority code C1 | Explicit trusted path map, unknown C3, semantic max floors and source/path regressions |
| Missing current ACK affected only dashboard | Inline current boot/full instance set/freshness and signer checks on business and evidence; paused permit, drift and re-ACK tests |
| Ineligible distinct human could approve recovery/exception | Purpose-specific current role/authority checks and distinct worker receipt negative |
| Nonpolicy bytes could replace Rego digest | Reject nonpolicy activation before any fence; signed registry/review retained and independent subsystem admissions preserved |
| Authenticated bad ACK had no canonical denial | Bounded workload DENY and terminal rejected operation replay tests |
| Restrictive epoch changes disabled manual service | Explicit restrictive evaluator lineage; AI disable preserves manual with current boots; restart still denies until re-ACK |
| Custody mutation could race final check/commit | BEFORE STATEMENT global-first lock triggers; concurrent boot and receipt writers block through final commit |
| Grant outlived approver eligibility | Current reviewer role checked on every query/page/export |
| Evidence actions were exempt from boot fence | Only recovery/control operations exempt; stale-boot grants/downloads deny |
| Private UI evidence could render after signed_out | Account/authority-epoch render masking and abort guards; original full-suite assertion retained plus delayed-export regression |
| Export Next used search instead of export page | Preserve export identity and cursor across GET pages; component and Chromium regressions |

The final reviewer reported no remaining blocking finding. Automated qualification is coordinator-owned and must match final actual check results. No human acceptance was inferred.

Historical failures remain in evidence: initial fixture duplicate principal, baseline-mode assumptions and missing workload-action SQL check; a deliberately blocked old review-expiry test revised to an injected clock after custody locking; one safe deadline denial during a concurrent verification load; initial browser accessibility markup; full-suite UI render race; and test-only lint. No failure is relabeled a pass. See final reconciled source/slice/browser runs in results.json.
