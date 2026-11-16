# Session003 review

Configured `imp_review` performed an actual read-only source/coverage pass. The primary ran all checks and wrote evidence; no specialist changed source or operated Docker. Final evidence review found no substantive corrections: counts/results, source inventories/digests, evidence hashes and fixture/live distinctions match. The review is recorded in `specialist-results.json`.

## Q-01 — Mutation barrier may stop before the mutation endpoint

Severity: medium qualification-script coverage defect; unresolved. Source: `tests/e2e/imp03/live.spec.ts:33` and barrier assertions around line 231.

The request helper fetches `/v1/auth/csrf` before a POST. If that GET fails, it returns the bootstrap status without sending the POST. During an identity outage the barrier assertion can consequently label a failed CSRF bootstrap as a protected mutation denial. No live phase ran here, so this session makes no false mutation-denial claim.

Before relying on live barrier results, fetch a valid proof before barrier readiness, retain it only in browser memory, send the actual intended mutation after the fault, and verify the attempted method/path. Check durable prohibited-effect absence independently. This session leaves the candidate source unchanged and carries the correction as required follow-up work.

## Evidence limits

- G-02 receipt and all five referenced evidence hashes remain consistent. This is inherited dependency acceptance, not acceptance of current IMP-03 changes or refreshed deployed trust.
- Provider/workload seams in local composition tests and illustrative provider subjects in provisioning remain fixtures. Actual PostgreSQL TLS1.3, pinned OPA, journal/capture and kernel UID behavior are distinguished in `checks.json`.
- No independently supplied live target, issued accounts, origin/certificate binding, renewed SVID evidence, deployed per-role isolation or human observations are present.
- Both full-lane skips were executed separately: provisioning/audit-grant test and Linux UID/fence test. The Linux test uses current read-only mounted source in a fresh cached-image container; it does not prove IMP-03 deployed role isolation.
- Automated source checks passed without changing implementation, dependencies, locks or prior evidence. Existing deprecations and the client chunk warning are retained in logs.
