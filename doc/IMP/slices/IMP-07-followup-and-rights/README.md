# IMP-07 — Follow-up and rights

G-07: automated_qualified for the isolated synthetic source candidate. Tasks IMP-07-A/B/C/D and 29 allocated operations; prerequisite G-05 automated-qualified.

[Session 001 implementation](sessions/001-implementation/README.md) · [latest closure handoff](sessions/002-closure-and-pr/handoff.md) · [G-07 ledger](../../executions/2026-11-21-IMP-07/ledger.json).

Code: services/data lifecycle modules/migration, services/core typed adapters, identity proof, policy/shared contracts and apps/web lifecycle UI at `/follow-up`. Tests cover PostgreSQL/signatures/OPA/current proof, rights/retention/holds/races and bilingual UI.

Qualification evidence belongs to the bound implementation candidate. [PR #14](https://github.com/zencodeai/care-link-demo/pull/14) is open against `main`; source publication and continuity are in [session 002](sessions/002-closure-and-pr/README.md). Human review deferred_until_after_IMP10. Backup recovery/expiry and physical erasure remain IMP-09 obligations. No deployment/publication or next slice is authorized by this handoff.
