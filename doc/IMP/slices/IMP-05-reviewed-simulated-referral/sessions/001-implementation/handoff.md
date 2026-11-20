# IMP-05 implementation handoff

**Complete · G-05 automated_qualified · 2026-11-20.** The user assigned “Implement service slice 05”. This session implemented the canonical IMP-05-A/B/C/D scope and 18 allocated operations using the current automated qualification policy. Human acceptance is absent; human review remains deferred_until_after_IMP10.

Starting/current commit: 75f8836b731b135f4a15cd8ba2b5acd937aca614; branch: feat/imp-04-plans-consent-directory. The tree was clean at assignment and now contains the uncommitted implementation. No commit, push, merge, live deployment, host trust change or next-slice activation occurred. Prior IMP-04 closure/human evidence was preserved.

Delivered:

- `services/data`: exact current source selection, immutable encrypted referral drafts, review vector/expiry, pending outbox, fresh guarded authorization, consumed attempts, final output authority checks, stable dispatch reconciliation, append-only observations and referral copy custody. Migration005 is additive to the existing data baseline.
- `services/simulators`: independent verified-TLS receiver database/credentials, encrypted immutable packages, atomic custody registration, dispatch/digest deduplication, service-scoped current receiver access, versioned decisions, fixed workload routes and signed human receiver envelopes. Receiver migration001 is for a distinct database.
- `services/core`: typed named data and receiver ports, authenticated/CSRF-protected actor routes, signed preflight metadata and independent receiver identity transport. `services/identity` exposes only opt-in receiver resolve/current, including review-origin composition; consent-proof/recovery stay denied.
- `apps/web/src/referrals`: EN/FR worker/client/receiver flows, authorized source/service selection, exact payload/provenance/digest review, actual step-up proof binding, explicit consent, separate enqueue/send, honest receipt/unknown/partial states and same-key uncertain-write recovery.
- `packages/contracts`, `config/demo/imp05/policy`, runtime/verification tools and image assets: coordinated additive contracts, versioned exact OPA policy, admitted signed simulator mapping, opt-in role composition, reproducible checks and bounded qualification packaging. Workspace root changes are manifests/configuration only.

Verification and bindings:

- All38 final source commands passed: 1,261 Python tests passed,3 explicitly gated legacy checks skipped; 167 web/contract tests passed. [Commands/logs](evidence/source/attempt005/checks.json).
- Real TLS PostgreSQL and separate receiver credentials; actual OPA and real IdentityService Ed25519 evidence through signed Core/data gateway composition. Provider and workload/mesh fixtures are labelled. Tests cover current rights/source/policy/assignment/directory races, audit-time expiry, authorization consumption/crash, response loss, invalid evidence, idempotency, receiver scope, final-write rollback and pending-copy retention.
- Real Chromium: 6/6 EN/FR actor cases, 12 axe scans with zero violations or incomplete findings, keyboard and 1280/640px reflow. [Browser evidence](evidence/browser/checks.json) uses mocked synthetic API/provider responses over loopback HTTP.
- Restricted Core and qualification images built and passed network-none smokes. [Manifest](candidate-manifest.json) binds image IDs, 121 verified packaged source/web files, current source (including untracked code), configuration/contracts/fixtures/environment and dirty-source digest.
- [Results](results.json), [schema-valid AgentResult](agent-result.json), [schema-valid automated DemoPacket](demo-packet.json), [execution ledger](../../../../executions/2026-11-20-IMP-05/ledger.json), [review corrections](review.md). Earlier failed attempts remain preserved. Frozen plan validator/archive bytes remain unchanged; the compatibility runner resolves only digest-verified historical relocations and still rejects current broken links or altered archived bytes.

Bounded decisions and remaining scope:

- A changed source selection creates a new draft identity; free-text structured review edits are rejected. An authenticated worker explicitly pumps pending work. Not-found/unavailable stays reconciliation-needed; no automatic reauthorization/resend or autonomous scheduler is claimed.
- Sender/receiver copies register purpose, source/parent identity, encrypted custody and pending terminal-delivery/parent anchors. Session closure cannot purge unknown delivery. Coordinated rights/cleanup jobs remain IMP-08.
- The three skipped legacy checks require distinct Docker capture/Linux UID/provisioning harnesses. They are not current IMP-05 passes. Deployed HTTPS/real MFA/native200%/human review and production/clinical/real-partner capability are not established by this source qualification.

All owned test containers, ephemeral databases/roles, Vite server and temporary database credentials were removed; built images remain local artifacts. Existing demo resources were preserved. [Cleanup](resource-cleanup.json).

Next chat: start from this handoff and the canonical workflow/plan. A requested deployment follow-up needs its own session and concrete target/configuration/action scope; the source implementation does not transfer earlier deployment approvals. A separately assigned IMP-06 starts its own slice/chat using this qualified dependency. Preserve synthetic-only and no-police-integration boundaries and runtime consent/MFA/human authority.
