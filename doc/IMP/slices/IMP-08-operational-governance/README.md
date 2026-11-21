# IMP-08 — Operational governance

G-08: automated_qualified for the bound isolated synthetic source/build. Tasks IMP-08-A/B/C/D and 30 allocated operations; prerequisites G-03 historically accepted and G-05 automated-qualified.

[Session001 implementation](sessions/001-implementation/README.md) · [implementation handoff](sessions/001-implementation/handoff.md) · [closure handoff](sessions/002-closure-and-pr/handoff.md) · [latest CI follow-up](sessions/003-ci-followup/handoff.md) · [G-08 ledger](../../executions/2026-11-21-IMP-08/ledger.json).

Code: services/data governance/migrations/current activation fence, services/core signed typed transports, shared contract validators, policy/enforcer duty admission and apps/web /governance. Tests exercise real signatures, OPA, PostgreSQL and filesystem journal with synthetic identity/mesh, plus bilingual browser fixtures. Scope: policy-only live activation, metadata-only audit, exact principal/global containment and non-authorizing bounded exceptions.

Human review deferred_until_after_IMP10. The user authorized closure and private PR publication. [PR #15](https://github.com/zencodeai/care-link-demo/pull/15) is open against main; [session002](sessions/002-closure-and-pr/README.md) records source continuity and publication. No deployment, merge or next-slice activation. Existing model/serving/host trust and unrelated research resources preserved.

CI follow-up: session003 corrects the manual-test subscription timing and binds the test/tool-only delta. Original runtime qualification remains preserved; check the live PR for the corrected-head CI result.
