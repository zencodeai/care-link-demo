# IMP-02 session 004 — deterministic cache-expiry test

The user reported a GitHub check error on [PR #9](https://github.com/zencodeai/care-link-demo/pull/9). This follow-up fixes that check and updates the existing PR under its delivery authorization. It does not authorize merge, deployment, lab changes or another slice.

Baseline: `7a34d7452138b9fd6a270bf28dea89f37f03e137`, branch `feat/imp-02-identity-trust-fallback`. Both push run `42688155738` and pull-request run `42688193650` failed the same test: `test_provider_key_failure_cannot_reuse_expired_cache`. Both container jobs passed.

## Cause and correction

The test assigned `_keys_at = 0` to simulate cache expiry. Zero is a valid monotonic timestamp: a runner clock below 300 seconds still sees a fresh cache. The test therefore depended on the host clock's origin/uptime. The original test failed locally when the provider's clock was held at 30 seconds; see [reproduction.log](reproduction.log).

Only `services/identity/tests/test_provider.py` changes executable code. The test now controls the provider module's clock without replacing the process-wide time module, and runs with origins 0, 30 and 1000 seconds. It verifies one JWKS fetch while the cached key is still fresh at 299 seconds, then refresh and denial at exactly 300 seconds when the provider no longer supplies that key. Runtime cache policy, cryptographic checks and error handling are unchanged.

## Verification and evidence binding

- Provider test suite: 62 passed.
- Fresh full fast lane: 353 Python passed, one Linux-only skip; 46 TypeScript/UI/parity passed. Locked dependencies, generated contracts, source boundaries/admission, types, lint/format, E2E source checks and build passed. See [fast-check.log](fast-check.log).
- No live lab, provider, retention, outage or deployment operations were run.
- G-02 decision, presented packet and candidate manifest remain unchanged historical records. The delivery adds a test-only delta; it does not silently rebind acceptance to new bytes. The accepted test SHA-256 was `166ddb40515b8d87c6224266a77cac146c13fd33dbd12753770b32e88c5e939c`; the corrected test is `ab9788fb82fa85f8f5368f291ff15effc7d0df626629da770c5f4630f9cb961a`. This single path appears twice in the manifest arrays; all other array bindings still match. Application/runtime source, configuration, fixtures and live evidence are unchanged.

Participant admission remains disabled. PR #9 remains the review vehicle; CI reruns on the fix commit. Remote status is reported in the chat/GitHub checks rather than rewriting accepted evidence.
