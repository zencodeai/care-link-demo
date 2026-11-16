# Host recovery-control foundations

`FileJournal` implements `care_link_domain.JournalPort`. Provisioning is explicit
and refuses an existing directory. Reopening requires the expected journal ID and
generation and the separately held Ed25519 signing key. No key or state is created
at import time. Callers must supply a current authenticated host boundary; this
package is not a SPIFFE attestation or deployed network-isolation claim.

Each append validates the closed LLD `JournalAppend`, locks the single writer,
verifies the signed origin/head and full signed hash chain, checks the expected
tip, fsyncs the new record, fsyncs a replacement head, replaces it and fsyncs the
directory before acknowledgment. A changed command under an existing ID conflicts.
Use distinct child command IDs for terminal records, linked by `db_operation_id`.
Restrictive records advance the barrier; terminal/checkpoint records advance only
the tip. Relax intentions never grant. Serving fence sets serving generation zero;
serving promotion is unavailable in this slice. Missing/corrupt/torn/unmatched tail
or head fails closed; there is no automatic trimming or replay-to-serve repair.

An existing object detects a decreasing live high-water mark. A complete host
rollback between process lifetimes cannot be proven fresh by signatures or this
local filesystem alone. Continuing trusted host custody remains an assumption;
suspected rollback/loss requires quarantined recovery and stronger evidence.

`EncryptedCaptures` accepts a caller-provided consistent `database.dump` and flat
object inventory with schema/artifact/audit digests, WAL position and journal head.
AES-256-GCM encrypts every object with the exact manifest as associated data;
Ed25519 signs the immutable manifest. Capture retry preserves the original time
and seven-day expiry. Partial, expired, modified or incomplete captures fail.
Input consistency/WAL completeness must be established by the owning DB adapter.

`restore_quarantine` verifies/decrypts into a new private directory and records
`quarantined_unvalidated`, `serving_allowed=false`. It never imports SQL, restores
bearers as active, replays sends or enables serving. After actual DB import, the
recovery validator must disable restored credentials/continuations/leases/reviews,
suspend positive grants, reconcile current restrictions and unknown sends, and
obtain the later independently authorized serving decision. A quarantine marker
alone is not network isolation or proof those DB transformations happened.
No RPO/RTO, physical erasure, trusted serving restore or human acceptance is claimed.
