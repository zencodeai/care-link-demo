# Independent reviewed static process

`care-link-static` reads a local publication and its externally supplied Ed25519 review public key. It has no runtime identity, core, policy, registry, model or database dependency. The default process serves an EN/FR unavailable placeholder and returns503; it invents no contacts and grants no participant admission.

After locked workspace setup, from `care-link-demo`:

```sh
uv run --locked care-link-static --port 8023
```

Open `http://127.0.0.1:8023/fallback?locale=en-CA` or `?locale=fr-CA`. This local engineering placeholder is independent of the developer API. Stop with Ctrl+C. Private serving/TLS and host OS isolation are separate lab configuration.

For reviewed publication, supply both `--directory /ABSOLUTE/PUBLICATION/DIRECTORY` and `--review-public-key /ABSOLUTE/REVIEW/PUBLIC.pem`. Public service custody should mount the directory read-only; a separate OS identity/admin process owns writing. No private signing key is generated or stored by the application.

The local artifact format is `public-text-1`: ordered EN/FR plain text title/body plus an exact Ed25519 signed review payload containing receipt, distinct reviewer/operator account IDs, artifact digest, verification/review-due dates and the explicit public-only assertion. Text renders through an escaped semantic Markdown subset with no raw HTML execution. Signature checks establish custody of the configured key; they do not independently establish reviewer entitlement or that the review actually occurred. The admission record must bind real reviewer authority and current reviewed content before participant use. Synthetic test reviewer keys are test fixtures only.

`create_admin_app` binds a **separate non-browser authenticated admin channel**. Its injected resolver must validate fresh human operator/MFA delegation from that protected channel; it cannot trust caller identity headers. Cookie and Origin-bearing browser requests are rejected. This bounded adapter supports external operator tooling rather than adding an unreviewed browser publication UI. POST `/static-admin/v1/publications` requires JSON `StaticPublish` and a canonical UUID `Idempotency-Key`; a trusted local artifact loader resolves only staged bytes and the exact review receipt. Missing/changed/expired review, changed current digest, mismatched receipt/operator or unknown fields reject.

Publication and operation-key/principal/body binding share a single fsynced record, atomically replaced under an OS file lock. A retry after a lost acknowledgement performs no second publication; it returns the currently valid manifest and cannot republish an older generation. Reused keys with changed input/principal conflict. The4MiB operation-custody cap fails closed rather than silently forgetting retry identity. Account/reviewer metadata follows the separately selected Option B schedule; copy/purge/backup implementation and verification remain separate evidence. Files use0600 and new directories0700; actual host ownership, encryption, crash durability and signer custody still require qualification.

Tests use real signatures and temporary local files; the simulated independent reviewer is not a human approval:

```sh
uv run --locked pytest host/static/tests
```

## Explicit owner-operated local demo

Session002 records the user's assignment of review, publication and retention roles to owner account `main`. `owner_review_local_demo` is an explicit supplemental profile for that private engineering scope. It does not claim independent review, a human cryptographic signature, participant admission or G-02 acceptance. The default `independent` profile and its exact `public-text-1` signature payload remain unchanged; it still requires distinct reviewer/operator identities.

Owner-demo admission requires **both** `PublicationStore(..., allow_owner_demo=True)` and `create_app(..., allow_owner_demo=True)`. The CLI exposes the corresponding explicit `--allow-owner-demo` switch. Unknown profiles, same-owner independent receipts, owner receipts with different reviewer/operator IDs, changed profile/signature and review intervals beyond the approved 30-day cadence reject. A store configured for the default profile cannot read an owner-demo publication.

The owner profile uses a signed `public-text-owner-demo-1` payload with `review_profile`, `independent_review: false`, `participant_admission: false` and `signature_purpose: local_artifact_integrity`. Its public page displays an EN/FR owner-review qualification separately from the accepted card text. **`/static/v1/manifest` returns 503 for this profile.** The supplemental `/demo-static/v1/manifest` returns `owner_review_digest`, profile and explicit false admission/independence fields; it never supplies `independent_review_digest`.

A separately composed `create_admin_app(..., allow_owner_demo=True)` supports `/demo-static-admin/v1/publications` with `owner_review_receipt_id`. It retains the fresh operator/MFA, non-browser authenticated channel, exact artifact, operation key and CAS controls. The canonical admin endpoint accepts only independent-profile artifacts. A local preparation helper can also publish into a named private lab directory under the authorized lab operator's custody; passing a UUID to that helper is not online authentication or evidence of an independent human act.

Prepare the unsigned final candidate and mechanical conversion record without modifying accepted session001 files:

```sh
uv run --locked python tools/prepare_fallback_card.py prepare \
  --output /ABSOLUTE/PRIVATE/LAB/card-candidate.json \
  --delta /ABSOLUTE/PRIVATE/LAB/card-conversion.json
```

The compiler verifies accepted source hashes, moves the exact first heading into title/H1, removes the drafting banner and authoring review-provenance sentences, and preserves the fixed no-autonomous-contact statement. It records the changed bytes and does not treat earlier Markdown acceptance as a signature or final-render acceptance. The final page renders a small escaped Markdown subset with semantic headings/lists/links and responsive CSS bound by an exact CSP hash. Raw HTML and executable/credential-bearing/unsupported link schemes remain escaped text. No remote content is fetched while serving.

After the authorized operator resolves `main` to its actual provisioned UUID and records current source verification, the explicit helper can prepare a local integrity key and publish the owner-demo artifact:

```sh
uv run --locked python tools/prepare_fallback_card.py publish-owner-demo \
  --candidate /ABSOLUTE/PRIVATE/LAB/card-candidate.json \
  --directory /ABSOLUTE/PRIVATE/LAB/publication \
  --owner-account-id ACTUAL_MAIN_ACCOUNT_UUID \
  --operation-id STABLE_OPERATION_UUID \
  --integrity-private-key /ABSOLUTE/PRIVATE/LAB/owner-integrity.pem \
  --verified-at ACTUAL_UTC_SOURCE_VERIFICATION_TIME \
  --review-due-at UTC_REVIEW_DEADLINE_WITHIN_30_DAYS
```

Use actual ISO UTC values ending in `Z`; no verification time is fabricated by the helper. Add `--expected-current-digest` for a new reviewed replacement. Retain the same operation UUID and inputs when reconciling a lost reply. The helper generates a mode0600 integrity key only when absent, emits its public PEM path, and binds the actual same-owner UUID to both receipt roles. The signature establishes local artifact integrity only. It must remain outside source/images/browser storage. The application itself still creates no key. Final rendered accessibility evidence and the actual stage decision remain separate records.

## Offline Option B custody maintenance

New stores use `public-text-custody-2`. An operation keeps its immutable principal/body binding separately from `event_at` and exact review reference. Same-key retries preserve all timestamps and never republish an older artifact. Replacing a publication archives its exact signed receipt and text artifact with actual publication/retirement times; replacement does not invent the end of a recovery or other review dependency.

The same authorized offline writer/custodian (`main`) may call these library methods under the existing private directory/file lock:

- `end_review_dependency(review_digest, ended_at=..., evidence_digest=..., custodian="main")` records an actual, evidenced final dependency end for an archived review. It cannot silently replace or renew an existing anchor. The end must not precede the actual serving boundary (the earlier of retirement and the exact signed review deadline); later recovery dependencies still require their later evidenced end.
- `retire_current(review_digest, ended_at=..., evidence_digest=..., custodian="main")` explicitly ends the current serving/recovery dependency and makes publication unavailable. It retains the exact archived receipt/artifact until the evidence-bound end plus 90 days. A current hold must first receive an explicit evidenced release.
- `set_retention_hold("review" | "operation", reference, reason=..., review_date=..., custodian="main")` records the owner, reason and UTC review date. Holds never expire automatically. Holding an operation also preserves its linked archived artifact.
- `release_retention_hold(kind, reference, evidence_digest=..., custodian="main")` records an explicit current custodian review before removing the hold.
- `cleanup_retention(custodian="main")` removes archives only after final dependency end plus 90 days and without relevant holds; it removes operation metadata only after event plus 90 days and after all associated artifact/review dependencies are gone. Active publication bindings remain protected. It reports overdue holds as `hold_review_required` with explicit references for the owner.

These methods use the same atomic full-record replacement/fsync transaction as publication. They are not browser APIs, do not authenticate a supplied owner string, and add no request-time identity/core dependency to the read-only public service. Their caller must already be the authorized OS writer and maintain the referenced dependency/review evidence outside the public listener.

An expired current review always makes serving unavailable. It is not silently retained as completed housekeeping: absent a documented recovery hold, cleanup returns `dependency_review_required`, `current_review_expired: true`, and `current_dependency_requires_custodian_decision: true`. The custodian must document a remaining recovery hold or explicitly retire its final dependency; no replacement card is required merely to retire it. Hold review dates becoming overdue only raise a flag, never release the hold or restart a retention clock.

Legacy records without event/dependency anchors fail closed with `migration_pending`; no historical timestamps are guessed. Reconcile them using actual dated evidence before any custody migration, or prepare a fresh isolated publication directory while retaining the legacy record under its documented disposition. Public serving also remains unavailable for an unmigrated record. The completion lab must therefore regenerate the earlier prototype publication before final qualification.

Cleanup proves removal from the current active custody file only. It does not assert backup expiry, restore reconciliation, physical erasure or deletion of separately held copies/evidence. Those copy inventories and exceptions remain the custodian's separate Option B obligations.
