# IMP-03 session001 — source candidate and verified local mechanisms

The user requested “Implement service slice 03” and later “proceed.” This session implemented and locally verified the manual-service source candidate. It does not record human G-03 acceptance or a deployed manual service. Participant admission remains disabled. Baseline/HEAD remains `caf3ddea7c8b4057d84f56632be1c0031e8ddecb`, existing branch `feat/imp-02-identity-trust-fallback`; initial tree was clean and current changes are uncommitted.

## Implemented behavior

- Typed human and workload-duty values; named BFF/data transports; fresh identity/CSRF and request-bound signature ports; current policy/deadline/barrier checks under ordered PostgreSQL guards.
- Synthetic persona/session creation, exact disclosure acknowledgement, attributed encrypted turns/assertions, deterministic stub assessment/escalation, human request, queue, reservation/acceptance and two-party channel confirmation. Acceptance never implies connection.
- Explicit observe/interrupt/takeover, ownership epochs, current message views and audited reference events. Reconnect generations cannot revive old ACKs. Both endpoint principal/role/access revisions, support ACL and current liveness apply. Disconnect reports loss of connection while preserving accountable ownership and unresolved support.
- Stable logical operations, durable rejected keys and current-authorized retries/status. A test commits a real PostgreSQL transaction then drops its acknowledgement; reconciliation finds one operation and one queue effect.
- Digest-only AL0 continuation issuance/rotation/recovery. The explicit additive issuance route resolves the original public-protocol gap. Lost rotation or recovery replies require a fresh exact same-principal ceremony; lineage fences unknown successors. No identity linking or assurance upgrade follows.
- Signed bootstrap OPA/Rego, canonical SQL-verified audit chain, journal-before-DB restrictions, signed/fsynced hash-chain host journal and current barrier checks. Known rollback duty failures record canonical DENY with workload identity; unknown commits never become false denials.
- Canonical identity Signal and persisted reservation-expiry DueJob operations through separately admitted signed machine duties. Registry defaults empty/disabled; no machine proof can occupy a human slot. Other job kinds and unsupported workload-compromise routing remain capability-disabled for their later scope.
- Native lifecycle copy/dependency inventory, encrypted captures with original seven-day expiry, consistent exported-snapshot pg_dump and actual restore into a new role-quarantined database with serving disabled. No trusted serving recovery, PITR, RPO/RTO or physical-erasure claim.
- Server-selected EN/FR participant/worker/supervisor components, explicit pending/unknown/reconciliation states, unsent input preservation, exact interruption confirmation and visible unqualified recovery protection.

Read [implementation decisions](implementation-decisions.md) for the public issuance/recovery additions, internal prepare-transfer response reconciliation and Psycopg/SQL migration tooling delta. Frozen REQ/HLD/LLD/IMP artifacts and existing acceptance records were not rewritten.

## Actual verification

[Full check](evidence/full-check-complete.log): 463 Python passed, one existing Linux-only test skipped; 56 TypeScript/UI/parity passed. Locked resolution, reproducible generation, source boundaries/admission, strict Python/TS, lint/format, E2E source checks and Vite build passed. [Database/policy lane](evidence/database-duty-final.log): 69 passed. Real PostgreSQL TLS, native row/security/grant/transaction behavior, real pinned OPA, real signed journal and actual logical capture/import were exercised. Identity/provider/workload-current registries in these composition tests are declared fixtures, not deployed trust proof.

[Clean offline verification](evidence/clean-verification-qualified.log): 410 Python passed, 54 expected opt-in fixture/platform skips, 56 TS/UI/parity passed. Intentional Python/pnpm lock drift and schema loosening failed as expected. Initial clean attempts lacked the correct offline cache or socket permission; the qualified run used the established temporary caches and allowed temporary local sockets. No test was weakened to obtain a pass.

[Final build](evidence/core-build-final.log) and [restricted smoke](evidence/core-smoke-final.log) passed. Image `sha256:cddbea55ca882ffb65075c46f22b4af174c24513eb117353bac189110a9f1ccb` is the isolated core artifact, with no business DB driver/credentials or unrelated service packages. Its default application remains developer-only and `/v1` unavailable; it is not a deployed/manual-service admission claim. Browser build retains a 585 kB chunk warning (110.75 kB gzip); the test stack emits an existing TestClient deprecation warning.

Configured specialists actually ran: imp_scope, imp_python, imp_web, imp_platform, imp_controls and imp_review, with at most three concurrent specialists and no nested delegation. The primary integrated shared files, ran the real database/resource checks and owned final evidence. Review found and corrected the material races/contracts recorded in [review.md](review.md). Final focused recheck reported no remaining critical finding, without supplying human acceptance.

## Resources and failure history

Only the separately named disposable `care-link-imp03-001-postgres` fixture (loopback25433, tmpfs) was created. Its test databases/roles and quarantined targets were cleaned, and the labelled container was removed. The existing IMP-02 cluster, provider, host help/static, fences and model were not changed. New local image tags and a pinned OPA executable in temporary storage were artifact/test inputs only.

One failed assertion printed a temporary fixture DSN. The retained diagnostic was redacted, the fixture password was replaced immediately, dataclass representations were hardened, and the fixture was ultimately destroyed. No real participant/account credential or story was used. Secrets and TLS material stayed in owner-only temporary files and were not included in the candidate manifest.

Other caught defects included authority-guard UPSERT requiring a prohibited INSERT grant (fixed with UPDATE-only preexisting guards), test-table/module isolation collisions, and a missing explicit original capture timestamp. Runtime grants were not widened, clocks were not relaxed and audit checks were not removed.

## Remaining work and next-chat starting point

Start a separate IMP-03 completion chat/session, read this handoff and candidate/check records, then recheck branch/HEAD/diff and actual host authorization. The source verification baseline is ready; the stage is not accepted.

Prepare the exact remote service composition and operational test packet: private origins and real issued accounts, independently credentialled data/identity/host journal, actual signed delegation/current identity adapters (the in-process ManualIdentityAuthority is a verification bridge), SVID/proxy/certificate/fence checks, admitted bootstrap/duty artifacts with actual receipt provenance, and deterministic real browser barriers. Compose required ports explicitly; there are no permissive default runtime authorities. Any host creation/deployment/outage action needs its own concrete scoped authorization. Do not mutate the retained IMP-02 lab on the strength of this source handoff.

Then execute separate participant/worker/supervisor browser journeys, real stream takeover/disconnect and fresh OIDC continuation-recovery cases, current audit/PDP/journal loss behavior and independent help/static truthfulness. Human keyboard/screen-reader/EN-FR content review and bounded resource/latency qualification remain unrun. Only after exact candidate/evidence presentation can an actual human accept G-03. Do not advance IMP-04, infer reviewer independence, enable participant admission or claim production/clinical readiness.
