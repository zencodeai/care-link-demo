# Implementation decisions and source reconciliation

- Current instruction authorizes IMP-03 code and local verification. Existing G-02 acceptance is a prerequisite, not transferred live host/deployment authority. Current lab stays unchanged.
- Initial review identified missing public continuation issuance. The explicit additive protocol below resolves that gap while preserving SessionView and the historical canonical catalog.
- Channel challenge secrets are one-use and digest-only at rest. GET releases only a party’s own nonce once. Lost/repeated release requires prepare-transfer to fence and replace the challenge; raw secrets are never reconstructed.
- Retain accepted OPA/Rego direction. Signed bootstrap policy means cryptographic integrity, not independent human approval or admission. All new content remains synthetic stub; no new participant admission/clinical authority is inferred.

## Reviewed additive continuation protocol

The source gap in initial issuance is resolved with the explicit local `continuation_issue` operation: `POST /v1/sessions/{session_id}/continuations`, `RevisionCommand` → `ContinuationIssued`. The named internal counterpart is `POST /internal/v1/data/continuation_issue`, with `Gateway_continuation_issue`. This leaves existing SessionView bytes and canonical operations unchanged. Current own-session authority, revision, policy, guards and audit apply; one active family per participant/session is issued at AL0, with digest-only custody and once-only return. A committed replay returns HTTP409 `REPLACEMENT_UNAVAILABLE` and the stable operation ID through the existing Error shape. OperationStatus remains the safe reconciliation query. The former internal bootstrap helper now calls this use case and no longer implements different authority rules.

A separate local BFF `ContinuationRecoveryStart` DTO and `/v1/auth/continuation-recovery` route bind an existing fresh-authentication ceremony to the exact session/family. It uses the existing provider MFA reauthentication and ceremony confirmation mechanisms (stronger than the AL1 minimum), without granting ambient AL3 or identity-link authority. Gateway own-session authorization remains required. Proof is consumed once; lost replies require another fresh bound proof. These are implementation protocol deltas, not retrospective edits or invented approvals of the frozen LLD artifacts.

## Other compatibility and engineering decisions

- The canonical public prepare-transfer response is `TransferPreparation`; the internal operation catalog still says `AssignmentView`. Both implemented transports return `TransferPreparation`, preserving the required challenge ID/expiry. This local reconciliation is explicit; the historical design catalog is unchanged.
- PostgreSQL access uses typed Psycopg and immutable ordered SQL migrations, following the existing identity service convention. This differs from the SQLAlchemy/Alembic direction in IMP03. Explicit guard ordering, grants, forced RLS, canonical audit verification and transaction tests are retained; no ORM/migration-tool execution is claimed.
- Server channel generations use an unpredictable boot namespace and strictly advance on each connection/replacement/disconnect. Two-party ACKs bind current principal/role/access revisions and current support ACL. An old connection or old ACK cannot be revived by reconnect.
- Signed request expiry is preserved separately from browser-session expiry and is checked after fresh identity lookup and at final transaction authorization. Input dictionaries are frozen before asynchronous policy or authority work.
- Bootstrap policy and disclosure bytes are synthetic engineering artifacts. Signature verifies integrity; no independent language/clinical/human acceptance or new participant admission follows.
- Restore qualification is intentionally quarantine-only: actual consistent exported-snapshot PostgreSQL dump, signed encrypted inventory and a new database with no runtime CONNECT grant, mode quarantine, generation0 and restored credentials/ACL/continuations/challenges disabled. It does not establish network-separated recovery, live restriction reconciliation, trusted serving promotion, PITR or measured RPO/RTO.

## Canonical workload duties and current connection reporting

`DutyCommands.identity_revoke(Signal)` and `job_execute(DueJob)` use a separate immutable WorkloadActor/DutyEvidence path, with canonical DutyDefinition wrapped by a signed artifact. Admission requires exact configured receipt/artifact bindings and current certificate/fence evidence; the registry is empty/denied by default. HTTP delegation binds peer, method/path, audience, body digest, operation ID, nonce and scope. Reservation expiry is the only admitted job kind in this slice. Valid stale/gapped signals restrict service and quarantine their source; unsupported workload-compromise routing never becomes a grant. Operator-only local maintenance helpers remain distinct and do not impersonate these machine operations.

Audit storage adds optional workload actor_context and a compatible defaulted append argument. Existing human hashes omit null context; workload hashes include full discriminated actor/evidence and revisions. Verified known-rollback denials get a separate canonical DENY transaction. Commit-unknown remains unknown. Stable rejected keys cannot later become successful work.

A confirmed handoff stores its exact challenge reference on the assignment. Current projections recheck endpoint generations, both principals, support ACL and access revision; a disconnected party is never reported as currently connected. Accountable human ownership and unresolved support remain intact across transport loss.
