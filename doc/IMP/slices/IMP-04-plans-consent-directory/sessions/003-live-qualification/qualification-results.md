# Live qualification outcome

Deployment is applied. IMP-04 is **not yet qualified for G-04 acceptance**. Actual failures and incomplete evidence remain alongside passed cases. Deployment approval is not stage acceptance.

The target is `care-link-imp04-002`, main origin `https://plans.localhost:30443`, provider `https://id.plans.localhost:31443`, application image `sha256:b5282ae84b127c301f8dbc5cfec7a14c5e8e278b7c9317c0a8eb11811dc88edd`. The public build uses those exact origins. The browser validates native TLS with the new CA in its own NSS home and `ignoreHTTPSErrors:false`; host trust and DNS were not changed. OPA and the signed policy/directory fixture hashes remain pinned.

| Procedure | Actual outcome | Evidence |
| --- | --- | --- |
| Q01 target binding/preservation | Strict transport CA/SAN validation, image file hashes and own SPIRE authority; final comparison preserves all64 accepted containers | `evidence/tls-strict-validation.json`, `evidence/image-source-verification.json`, `evidence/final-snapshot.json` |
| Q02 separate actors | Nine genuine password+OTP provider sign-ins, actual roles/AL2, separate cookie jars, native TLS | Actual live summaries in `evidence/live/` |
| Q03 plans/attribution | Own plan stable create, append attribution, unshared denials; assigned worker conflicting safety report retains two authors/dispute; DB pending-review count1 | normal008 observations, `evidence/database-lifecycle-review-controls.json` |
| Q04 exact sharing | Real visible preview, subject-bound MFA/confirmation, strategies-only sharing; medication absent; revoke then deny | normal008 observations |
| Q05 own reports/reload | Carer/professional reports retained with cross-author denial; actual UI visible author/words, manual reselection before/after reload | report-ui003 passed. Report IDs are API-bound and used as React keys, not rendered text |
| Q06 signed directory | Seven exact fixtures, EN/FR projections/provenance, fixed observation times, truthful stale/unknown or unavailable status | directory003 passed. First service remains security-suspended; no state reset |
| Q07 lifecycle | Support close retains active plan; separate retirement anchors retained copy at actual retirement+30days | lifecycle001 passed; database copy metadata. No elapsed30day purge/backup completion claim |
| Q08 accessibility | Actual PID English scan26rules, zero violations/incomplete, keyboard focus passed; earlier attempt also PID French passed. Four-actor bilingual run did not complete | accessibility001/003/004. French second-search503 unresolved; screen-reader and actual200% zoom not run |
| Q09 retention/manual/replay | Own plan/read after native reload/reselection; real inherited two-party event-stream handoff/messages and duplicate key once; actual journal fault produces UI pending503 then same-key/body retry200 with one field in projection | reload001, manual002, pending-ui002 passed. No full-reload draft/pending-intent persistence claimed |
| A01 unshared/forged access | Unshared carer/professional/other PID and unassigned worker denied; direct forged-header backend403; no client SVID denied | normal008, network-denials. No claim of a live browser-role-forgery matrix |
| A02 grant expiry/narrow survival | Wider grant expires on actual wall clock; narrower strategy-only grant survives, then revoke denies | normal-continue001 observations passed before later reload-driver failure |
| A03 pending output | Actual entered/released timing receipts and journalled revocation; final instrumented response503 `manual.gateway_denied`, no projection | race012. **Strict race qualification failed**; no final-output expiry/role-change proof claimed |
| A04 concurrent absent scope | Actual pending grant held, independent revocation, release; response503 `manual.gateway_denied` | absence002. **Strict serialization qualification failed**; durable metadata checked separately |
| A05 delegation | Separate offline ten-minute exact delegation; strategies/purpose/subject checks; wall-clock delegation expiry denies new grant and disclosure while previous grant still otherwise unexpired | delegation001 and delegation-expired001 passed |
| A06 source controls | Invalid digest quarantined, serving revision preserved, participant admin denied, security suspension survives valid reingest | directory003 passed |
| A07 workload controls | No-SVID/foreign-CA denial; independently signed logical URI comparison, protected UID/route checks, backend403, cross-role config absent | network-denials; real issuer-expiry result recorded separately |
| A08 dependency loss | Actual Docker freezer pause of each new identity/PDP/journal app; plan read503 without projection; ordinary read200 after unpause | dependency001 passed. Independent host watchdog20s plus unconditional cleanup |
| A09 database | Runtime DDL/delegation writes/immutable updates/deletes denied; non-superuser/non-createdb/non-createrole/non-bypass-RLS and three forced-RLS tables | database evidence. DB remains internal; probes use protected data connector |

The initial SIGSTOP fault control did not stop namespace PID1. Its200 outcome is retained as a failed test attempt, and no denial proof is attributed to it. The replacement freezer control confirms actual `Paused` state on an immutable inspected container ID and recovers outside the paused container.

The original ingress limit16 caused measured concurrent native-TLS failures. The narrowly reviewed correction permits64 connections, retaining the same image, routes, credentials, network, publication, memory/CPU and time/buffer limits.64 TLS sockets then succeeded and65th was denied. The exact old/new ingress IDs and before/after proof are retained.

Repeated browser harness runs accumulated143 zombie processes under the512-process ceiling (counter116 hits); memory OOM counters were zero. Only the new browser was restarted, retaining its CA/home and configured limits. This is an operational limitation; no init reaper was added. It does not explain every prior UI timeout.

The PDP container was genuinely OOM-killed under its approved256MiB limit at20:24:58.586479633Z. It failed closed and was restarted with the same ID/image/configuration/limits/state. The underlying memory/concurrency issue remains open; restart is recovery, not a fix. A later French-search503 occurred with PDP still running, so it is tracked separately.

No policy/identity/deadline/clock bypass or old restriction reset was used. Temporary timing controls are disabled after restoration. All failed attempts remain indexed; source-only checks do not convert these live gaps into passes. No G-04 decision, participant admission, next-slice activation, commit or push occurred.

The issuer-expiry procedure waited beyond300seconds with no clock change. Protected bootstrap503 and public health200 proved denial while workload certificates were expired. Issuer-only restart did not restore all roles within the driver75second window, so `workload-expiry.json` remains failed. Later `workload-expiry-late-recovery.json` records all five genuinely renewed URI-bound certificates and protected/public200, without any agent/fence restart or restriction reset. Delayed recovery is not erased from the record.

The final normal009 attempt ran after default data composition restoration and real trust recovery. All nine genuine actor sign-ins passed, but the first new-session request returned503 AUTHORITY_UNAVAILABLE after1158ms. No whole normal phase is reported as passing. Earlier successful case-level observations remain valid at their recorded times; current ordinary-path availability/performance needs follow-up alongside the French-search failure.

Final read-only database verification proves exactly one committed durable operation and one field for pending-ui002, correlated by plan, author and session. The earlier ineffective-pause pending-ui001 returned200 and committed its synthetic field; that effect is retained, not undone. The final primary-plan review-work count is3 after these additional conflicting strategy appends (the earlier Q03 checkpoint was1). Final counts and attribution are in `database-final.json`; failed assertions do not imply that prior successful commands had no effects.

The exact absent-race operation `edb6ec07-c642-4f4b-8fbf-c3329a6334cc` has no durable operation row. The read-only verifier expected one durable rejected row, so `database-absence.json` is failed. A missing resource ID is not asserted to prove a global zero-grant count. A04 remains unresolved.
