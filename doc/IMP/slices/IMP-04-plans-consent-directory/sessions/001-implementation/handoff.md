# IMP-04 source implementation handoff

The user assigned “Implement service slice 04” on 2026-11-16. Source implementation is complete on `feat/imp-04-plans-consent-directory`, based on clean commit `a91087350306cf847ade2479c9ad05542c9d3adb`. Changes remain uncommitted. G-03 was accepted before this session. G-04 has no human decision; the accepted lab was not changed.

## Delivered behavior

PID plans support creation, append-only attributed fields, disputes and human-review work, retirement and current account sharing. Carers and professional participants have their own attributed reports and a current author-scoped report view; relationship labels grant no PID or workforce permission. AL2 edits and consent use fresh identity. Verified self-consent ceremonies bind the subject and purpose; independently provisioned delegation is separately checked against exact fields, purpose and expiry. Plan copies retain their own retirement+30-day anchor and survive support-session closure.

Consent grants bind the session, subject, account/service recipient, purpose, fields, proof/basis, explicit interval and source revisions. Current grants recheck principal and delegation authority. Revocation journals a restriction before the guarded database transition. Subject guards protect absent grants, and pending work recomputes complete policy inputs. The final disclosure check tests every selected field against both the evaluated policy scope and current grants, including expiry during projection and narrower surviving grants. Previously disclosed bytes remain disclosed.

Directory operations retain immutable source versions, quarantine rejected feed digests and authoritatively suspend services. Signed manifests bind exact source payloads to independently pinned Ed25519 keys; a signature proves engineering integrity, not human review. All seven operating states have EN/FR qualifications, provenance, truthful availability/unknowns and alternatives or explicit absence. Structural/operational/near-realtime freshness limits remain 720 hours/24 hours/300 seconds. Fixed fixture observations naturally become stale; no clock or timestamp refresh is treated as new evidence. No executable destination is created.

The bilingual UI includes plan edits, exact sharing previews, proof completion, current shared views, revocation, saved own reports, directory options and stable-key unknown-result reconciliation. Carer/professional sign-in choices use participant routes and remain server authorized. ReviewApp integrates the same capability with its existing view lease.

## Source and contract continuity

Canonical tasks are IMP-04-A/B/C/D; the 22 allocated public/data operations are recorded in the integration packet. Additional actor-owned report transport is narrowly scoped and documented in [implementation-deltas.md](implementation-deltas.md). REQ/HLD/LLD and the canonical planning allocation were not rewritten.

Ownership: plans/consent under `services/data`; source admission/directory under their own data modules; BFF adapters under `services/core`; proof verification under `services/identity`; UI under `apps/web/src/plans`; coordinator owns migrations, contracts, policy, composition and evidence. Specialists ran `imp_python`, `imp_controls`, `imp_web`, `imp_verifier` and read-only `imp_review`, never more than three concurrently. The primary performed decomposition and integration; no nested agents ran. [Review and corrections](review.md).

Migration `services/data/migrations/003_plans_consent_directory.sql` was applied only to the dedicated disposable test database, after 001. Existing 002 review-migration tests also pass against the additive schema. Runtime cannot provision delegations, mutate immutable fields/events/versions or run DDL. Activation requires a separately authorized target migration/configuration/image plan; no such action occurred here.

## Verification and limits

[checks.json](checks.json) and its evidence logs record the final reproducible lane. [results.json](results.json) records counts, actual failures/corrections and not-run reasons. Python tests use real isolated TLS PostgreSQL, real OPA and signed filesystem journal in composition; identity-provider and mesh provenance remain explicitly labelled fixtures. UI tests use controlled HTTP fixtures. These are source/adapter proofs, not deployed SVID, live IdP, native browser, accessibility, clinical or production qualification.

The planning validator encounters a pre-existing frozen-inventory mismatch for `doc/IMP/README.md`; current bytes match the starting commit. Its inventory was not silently refreshed. Required source checks, contract generation, dependency boundaries and application tests are recorded independently.

Reproduce with the already configured private fixture and existing OPA binary:

```sh
.venv/bin/python -m tools.imp04_verification.run_checks \
  --database-config /private/tmp/care-link-imp04-001/database/connection.json \
  --opa /private/tmp/care-link-imp03-tools/opa
```

The fixture tool can prepare/start/stop only `care-link-imp04-001-postgres` on loopback 25434 with its pinned cached image. Verification creates and removes `imp03_manual` and test roles only inside that container. No accepted IMP-02/03 resources are reused. Secrets remain in owner-only temporary storage, outside Git/evidence. Check the results record for final fixture cleanup state.

## Next chat

Start from this handoff and the [execution ledger](../../../../executions/2026-11-16-IMP-04/ledger.json). Prepare a concrete deployment/qualification delta if the user requests one: name the isolated target, migration 003, policy source/signature/key, independently pinned directory sources, actor provisioning, source/image hashes and rollback. Then verify separate PID/carer/professional/worker accounts, all seven source states, consent expiry/revocation during pending output, EN/FR keyboard/accessibility journeys and current workload trust. Obtain the actual G-04 decision on that candidate. No acceptance, deployment, commit, push, participant admission or IMP-05 activation follows from this handoff.
