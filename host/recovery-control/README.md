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

## IMP-09 current-authority recovery

The public `RecoveryCoordinator` composes `EncryptedCaptures`, `FileJournal`, a
separately signed `RecoveryLedger`, fresh `RecoveryAuthority`, `CaptureSource`
and `RecoveryTargets` ports. `ports.py` defines the exact typed adapter contract.
Construction requires an explicit continuing-host custody predicate. A false or
unavailable predicate denies recovery and generation admission. Signatures and
old timestamps never substitute for continuing host provenance; root/whole-host
loss still needs stronger externally established custody.

Nine allocated recovery operations validate the closed LLD DTOs. Additional
server-authenticated evidence reads expose the exact sealed `PromotionBinding`.
Target reconciliation must return complete current rights/audit/schema/artifact
and uncertainty evidence, then pass a fresh target digest/head comparison.
Unknown restrictive intent forbids validation. Data import/reconciliation is
owned by a concrete data gateway adapter; staging a filesystem marker alone is
never treated as completing those operations.

An approval authenticates current human identity and fresh MFA, consumes the
exact immutable proposal ceremony, and expires within 300 seconds. Human identity
must differ from both restore operator and proposer even across account aliases.
Execution revalidates approver/operator/proposer current authority, original
backup expiry, exact sealed target and exact journal head. `PromotionExecute`
`expected_serving_generation` names the prior generation; the binding names the
new generation. Generations increase monotonically. The final valid signed 64-bit generation
can serve; exhausted allocation stays explicit and cannot wrap or overflow.

The signed ledger persists maintenance before any DB or router change. It then
records `fenced_old`, `routed_target`, `enabled_target` and `smoke_verified` only
after each concrete adapter action. Protected generation admission remains zero
through the smoke probe. Every boundary rechecks exact approved authority/head
and target. A restriction can still enter the independent journal during
maintenance and invalidates the approval. Interruptions never resume a cutover
automatically. Reconcile under restriction, revalidate and obtain a new approval.

`BoundGenerationJournal` scopes the authoritative gate to one target. It emits
`serving_generation=0` unless the signed host ledger, current journal lineage,
router and DB state agree on one completed promotion. After successful promotion,
ordinary journal checkpoints may advance; any `serving_fence` after the exact
approved baseline always revokes that completed promotion. The gate reads head
and records in one verified journal snapshot. The underlying live barrier is
still returned for final data/dispatch checks. The composition must use the wrapper at
data final authorization, dispatch, and edge admission; an unconnected wrapper is
not enforcement. AI admission remains separate from manual smoke/serving.

`inventory()` exposes original immutable capture expiry. `expire()` requires
current hold accounting from the maintenance composition, preserves the signed
manifest and unlinks only known encrypted objects after expiry. Its result says
`physical_erasure_proven=false`. Restore does not renew backup expiry; known
host/identity/spool/temporary copies must be separately accounted for before a
rights request can claim copy completion.

Host tests use real cryptographic/filesystem state, subprocess death at every
cutover gap, and explicit target/router/identity doubles. PostgreSQL/network
adapters need separate integration evidence. Creation/proposal/approval/cutover
wall-clock stamps are durable; the verification harness must measure full
restore-to-serving elapsed time including approval delay, capture age and
failures. No unconditional RPO/RTO or live promotion is established by unit tests.
