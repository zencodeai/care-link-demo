# Independent opaque help

This package implements `help_create`, `help_status`, `help_accept`, and
`help_cancel`. A request stores an opaque identifier, owner, time, state,
accepted worker, revision and authority digest. No story, PID, transcript,
phone, address or plan is accepted. Acceptance always remains
`accepted_unconnected` with `connection_confirmed=false`.

The composition root constructs `Spool` in a dedicated existing `0700`
directory, `SignedReceipts` with pinned Ed25519 public keys,
`HttpAuthority` and `HttpBrowserSessions` with a pinned, authenticated
workload HTTP client, then `HelpService` and `create_app(HelpConfig(...))`.
The client must verify the identity proxy's TLS chain/SAN and present the
attested help identity. Internal identity endpoints must authenticate that
peer before reading `X-Help-Session` or `X-Help-Origin`. Neither header is
accepted as browser authority by help. Credential headers and callback
queries must be excluded from logs.

Mount the separately configured identity BFF routes on the help origin,
with its own OIDC client/callback and `__Host-care_link_help` cookie. Browser
tokens stay server-side. `GET /v1/auth/csrf` supplies the current CSRF token;
mutations require exact `Origin`, `X-CSRF-Token`, JSON and a random UUID
`Idempotency-Key`. The browser never obtains an internal help proof.
Main-origin cookies do not authorize this origin. No permissive test-login
route or module-global configured application exists.

Before create, the browser calls `POST /help/v1/create-intent` with the
strict `HelpCreate` body and current CSRF protection. This adapter returns
`{operation_id: UUID}` after fresh signed authorization. Its SQLite registry
keeps one unresolved create key per account across response loss, process
restart and full OIDC reauthentication. The same locale/jurisdiction returns
the same key; changing that payload conflicts until the associated request
is explicitly cancelled. The browser uses this server key as the actual
create request's `Idempotency-Key`; it never mints a replacement after an
unknown outcome. Preparing an intent records no help request. Concurrent
prepare calls choose one winner; a loser obtains new authority for the
winner's exact target before returning its key. Registry, nonce consumption
and local audit commit atomically. This is a local browser-recovery adapter,
not a new LLD business operation.

Every operation obtains a new one-use proof and signed receipt, checks the
exact request binding and original one-second budget, and applies local
owner/worker predicates. SQLite `BEGIN IMMEDIATE` serializes nonce use,
revision change, operation record and local hash-linked audit. Foreign keys,
WAL and `synchronous=FULL` are set explicitly; files use `0600`. Retries
reauthorize and project current state, while changed idempotency payloads
conflict. A create target is deterministically opaque from the random
operation UUID so lost responses can retry the same logical request.

`HttpBrowserSessions` calls the identity service's protected
`help-browser-context` and `help-browser-proof` adapters. The latter returns
`proof_ref`; the help-authority request carries it as `browser_proof_ref`.
Signature encoding is unpadded base64url Ed25519 over UTF-8 canonical JSON
(sorted keys, compact separators, `ensure_ascii=False`) excluding
`signature`. Unknown keys, issuers, audiences, altered fields, expired
receipts and consumed nonces deny. Missing fresh identity shows the
independent static link and performs no private spool effect.

Local spool audit is separate from canonical business audit. Core
reconciliation belongs to its allocated later-stage operation and is not
advertised as implemented here. Account-retention decisions, filesystem
durability/custody, separate OS identities, Keycloak/PostgreSQL deployment,
mTLS proxy/issuer/CNI/host routes and independent fallback content review
remain deployment qualification work. Health reports process/configuration
state and `participant_admission=false`; it does not assert live authority
or participant readiness.

Run the scoped local tests after locked workspace setup:

```sh
uv run --locked pytest host/help/tests
```

These use real SQLite and Ed25519 signatures. The HTTP composition test uses
the real identity service with fake provider/store/workload transport; it
does not establish deployed Keycloak, PostgreSQL or network enforcement.

## Same-custodian Option B maintenance

`spool.lifecycle` exposes offline `status()`, `review_active(help_id)`,
`hold(help_id, reason_key, review_at)`, `release_hold(hold_id)` and `run()`.
These methods require the actual configured effective custodian UID and the
existing0700 directory/0600 spool. There is no browser purge route, new identity
service dependency, automatic review decision or automatically started job.
The deployment's scheduled maintenance must invoke this API under the help
custodian; schedule/retention ownership is main per the actual user decision.

An additive side-table migration preserves original request/operation/intent
insert contracts. New writes atomically capture request creation, actual
cancellation, operation events, intent creation, and consumed decision nonce
acceptance/expiry. Existing missing anchors remain `migration_pending`; restart
does not manufacture historical timestamps. Only `cancelled` is terminal.
`recorded`, `accepted_unconnected` and unmaterialized create intents retain the
minimal ownership/retry dependency, with explicit overdue30day review status.
Age, silence and maintenance never imply connection or close unresolved help.

After the later of actual cancellation and dependent operation/audit event anchors
plus90days, a maintenance transaction can
remove owner/worker account linkage and the related operation/create-intent retry
rows only when anchors are known and no active hold exists. Holds require main
ownership, a bounded semantic reason key and review date; overdue holds are
reported and never silently released. Explicit release still leaves all terminal,
anchor and replay checks in force. Retired logical operation/target IDs become
one-way hashes without account identifiers or payload; fresh authority cannot
recreate those old logical requests. New deliberate requests use new keys.
Markers remain restrictive pending separate copy/grant accounting, have30day
review status, and are capped at10000 by default. Reaching capacity rolls back
maintenance and reports `help.lifecycle_retirement_capacity`; no marker is dropped
to admit an old replay. There is no automatic marker-release API.

Expired nonce metadata can be removed after90days from its original one-second
authority expiry. The receipt verifier and final spool expiry check still reject
old signed receipts; deleting expired deduplication metadata cannot renew them.
Legacy nonces with unknown timestamps remain pending explicit migration.

Audit maintenance verifies the stored chain and can prune only a contiguous
expired90day prefix that crosses no active/held/legacy request dependency. Its
checkpoint retains only the last deleted sequence/hash and pruning time, without
account or request references. A later append continues from that checkpoint,
including after restart. Status says `checkpoint_to_current_only`; deleted
historical events are not claimed reconstructible or complete. Corrupt chains or
checkpoints fail closed, including new private spool writes. Active dependencies
may retain an older prefix until their purpose ends; holes are never punched into
the chain to remove later events.

Every spool connection enables `secure_delete=ON`. After the unlinkage transaction
commits a durable pending marker, offline maintenance runs a TRUNCATE WAL
checkpoint, VACUUM to rebuild legacy free pages, and a second TRUNCATE checkpoint.
`managed_copy_cleanup=complete` means these managed SQLite page/WAL operations
succeeded. An old reader or lock preventing cleanup leaves a persistent
`pending_busy_or_reader` status, including `managed_copy_reader_pending=true`;
other cleanup errors remain `pending_error`. Retry `run()` after readers drain.
Logical unlinkage can already be committed while this copy cleanup is pending.
An interrupted cleanup retains the committed pending marker. This operation
requires offline scheduled custody; it can contend with concurrent spool access.

Backups, exports, reader-held external copies, filesystem snapshots and storage
device remnants still require separate copy inventory and expiry proof. Reports
retain `pending_separate_spool_copy_inventory` and never claim physical SSD
erasure. Tests inspect actual temporary SQLite/WAL bytes for removed owner/worker
identifiers after successful cleanup, plus pinned-reader and legacy-free-page
cases with controlled clock boundaries; they do not claim90days of observed
wall-clock operation or host power-loss durability qualification.
