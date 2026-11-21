# Recovery operator runbook

Use only a separately authorized synthetic target. Construct the coordinator
with distinct capture encryption, journal signing, generation-ledger signing,
target DB and human authority custody. Supply a current continuing-host custody
predicate. Keep the current journal outside all restored volumes. This runbook
is source documentation; it does not execute a live restore or grant approval.

1. Capture a consistent DB snapshot with its schema/artifact/audit checkpoint and
   WAL recovery position through `CaptureSource`; keep identity and help-spool
   captures separate. Verify inventory and original seven-day expiry.
2. Request `restore_create` with exact backup/manifest and revision `0`. The
   target adapter creates a new quarantine database with distinct credentials
   and no private serving, receiver or model egress. Filesystem staging alone is
   insufficient isolation.
3. Execute `restore_validate` at the current target revision. Verify current
   journal identity/continuity, audit checkpoints, current tombstones/revokes/
   holds/kill switches, suspended positive authority, disabled sessions/tokens/
   leases/reviews and reconciled stable-ID unknown sends. Any unresolved
   restrictive intent keeps the target unvalidated.
4. Read the server-sealed target evidence. Propose the exact binding and current
   target revision. A distinct provisioned human reviews that immutable proposal
   under fresh MFA and supplies its single-use `promotion` ceremony. Approval
   expires within five minutes and names only this target/head/generation.
5. Execute with proposal ID, approval ID, exact binding digest and prior serving
   generation. The coordinator enters maintenance, fences every old DB generation,
   switches the route under restriction, enables the exact target and executes a
   bounded current manual smoke. Data, dispatch and edge require the host gate
   in addition to DB/router state. Admit AI only through its separate controls.
6. Record full recovery time, approval/staffing wait, original capture age, command
   identities and failures. Do not exclude approval delay to meet RTO.

After an interruption, stale head, failed smoke or target mismatch, keep every
protected path restricted. Inspect signed ledger, current live journal, router
and DB together. Do not restart an interrupted execute or flip to the old DB.
Revalidate a compatible quarantined target under newest rights, obtain a new
independent approval and run the same sequence. Missing/suspect current host
custody cannot be repaired by selecting an older signed journal.

Expiry accounting preserves original signed manifest. Current holds prevent
unlink. Account separately for encrypted captures, restored quarantine copies,
identity and help spool copies, scratch exports and any retained dependency.
Known-copy unlink is not a universal physical-erasure claim.
