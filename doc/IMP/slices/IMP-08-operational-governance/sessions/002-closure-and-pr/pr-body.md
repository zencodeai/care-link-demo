IMP-08 adds the operational governance workflow: signed artifact review, independent human authority checks, policy activation with current per-boot ACKs and higher-epoch rollback, bounded incident containment, scoped audit evidence, and coupled aggregate metrics with disclosure suppression. The `/governance` workspaces support operators, security, governance and auditors in English and French.

Qualification binds the isolated synthetic source/build to G-08. Runtime checks reject stale boots, revoked signers, expired or ineligible approvals, raced custody changes and stale private evidence. AI disable preserves manual service while restrictive controls remain enforced.

Validation:
- 1,684 Python tests passed; 3 existing legacy checks explicitly skipped.
- 223 frontend tests, 102 focused slice tests and 13 Chromium route-fixture checks passed.
- All 38 source commands and final contract, typing, formatting, dependency and evidence checks passed.
- Closure verified all 900 source hashes, 58 reference hashes, 3 build hashes and 47 check bindings. The merged IMP-07 base tree equals the qualified baseline.

Scope limits: live activation through this path admits Rego policy artifacts; audit access is metadata-only. Containment supports exact principals or explicit global capability scope. Human usability, screen-reader, visual and language review remains deferred until after IMP-10. Browser fixtures do not establish deployed network/provider readiness, and the local latency sample is not a deployed SLO. No deployment, real-data/clinical readiness or production certification is implied.

Evidence: `doc/IMP/slices/IMP-08-operational-governance/sessions/001-implementation/handoff.md` and `doc/IMP/executions/2026-11-21-IMP-08/ledger.json`. Closure/publication records are in `sessions/002-closure-and-pr/`. Unrelated research resources are excluded.
