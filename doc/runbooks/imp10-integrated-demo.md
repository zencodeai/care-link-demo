# IMP-10 integrated synthetic demo

Use an isolated workstation test environment with fictional accounts, services and artifacts. Training and replay have separate data custody. The existing demo release and serving approvals remain independently controlled.

## Reproduce the automated candidate

1. Start from [the slice handoff](../IMP/slices/IMP-10-integrated-demonstrator/README.md) and verify the candidate manifest. Use the locked Python and Node dependencies and the pinned OPA executable from the environment receipt.
2. Provision the disposable TLS PostgreSQL fixture using `python -m tools.imp09_verification.database start`. Port 35439 is required by the encrypted recovery regression. The fixture rejects adoption of an existing target. Run `python -m tools.imp10_verification.checks --out <new-absolute-output-path> --opa <pinned-opa-path>` from the demo repository. The runner avoids logging the private DSN and keeps the full regression and matched-assistance test in separate processes. Stop this owned fixture using `python -m tools.imp09_verification.database stop`.
3. For browser checks, supply the approved pinned Chromium fixture described in [the isolated browser procedure](../../deploy/images/imp03-browser/README.md) and the exact Chromium image in the environment receipt. Set `IMP10_TRAINING_BROWSER_WS_ENDPOINT` and `IMP10_TRAINING_BROWSER_OUTPUT` to the private loopback endpoint and a new output directory. Run `pnpm exec playwright test --config tests/e2e/training/playwright.config.ts`. The adjacent referral, assistance, rights-follow-up, governance and recovery configs consume `PLAYWRIGHT_WS_ENDPOINT` plus their own `IMP05_BROWSER_OUTPUT` through `IMP09_BROWSER_OUTPUT` settings. Keep the private browser endpoint out of durable reports.
4. Run `python -m tools.imp10_verification.trace --check` to verify the source, requirement, control and operation matrix. The matrix retains unassessed rows and the scope of predecessor evidence.

The durable actor journey uses [real PostgreSQL and OPA](../../services/data/tests/test_imp10_integrated_journey.py). A participant and worker confirm the service channel. The receiver stores a single package after a lost reply, reads it under separate receiver authority and records partial acceptance. The journey checks a scoped plan share and revoke, one audited inbox delivery, one-use own-data export, and deletion with unresolved-copy exceptions. The browser fixtures exercise separate actor views, EN/FR keyboard navigation and axe. Together these checks cover different boundaries.

## Bind an isolated trainer and evaluator

Use `tools.imp10_runtime.training.training_application` with a separate verified-TLS database that owns [the training schema](../../services/simulators/migrations/002_training.sql), a training-specific content key, separately authenticated workload, currently approved trainer roster and deterministic policy permit. The permit receives the current actor, exact action, scenario target and request digest and must fail closed. Enable the separate short-lived Identity training proof audience only for that topology. Bind the trainer HTTP gateway and the signed Data evaluation gateway to the existing Core composition through its `training` and `evaluation` ports. The evaluation service requires the [quality migration](../../services/data/migrations/013_imp10_evaluation.sql), a separately authorized replay catalog, and an exact admitted policy build. The optional evaluation module can accompany the IMP-08 base Rego in an isolated policy candidate.

In `/training`, sign in as a current MFA trainer. Use the SHA-256 of the exact bytes in [training-artifact.json](../../config/demo/imp10/training-artifact.json) and set a UTC fictional business clock. Choose the delay fixture to start a stoppable run. Immediate fixtures commit an encrypted recording with their terminal projection. The reading route shows revision, state and evidence digest. Independent authority clocks control proof validity and expiry.

Use `admit_completed_capture` from the training composition under current trainer authority to package the durable capture. The offline catalog uses the exact manifest, recorded observations and bundle pins. The bundle includes the exact deterministic runner, artifact and contracts, plus any other configured rules or sources. Bind the explicit trainer and optional governance reviewers before loading the authorized catalog into the Data composition. Enter those four values in the replay form. A missing or divergent pinned observation gives a failed replay report. A foreign trainer, unregistered digest or expired capture is denied.

Training channel labels, directory states and receiver variants are fixture observations. They leave operational service, operational metrics and external destinations outside their effect surface. Identity linking denies at the public and Data surfaces under LD-13. Training ciphertext is eligible for bounded active-store cleanup through `TrainingService.expire_recordings` after seven days from the original capture. Keep catalog copies in private, time-bounded custody with the same anchor. Verify remaining copy expiry separately.

## Failure and rollback

| Condition | Expected behavior |
| --- | --- |
| Model disabled or inference capacity saturated | Scoped assistance is unavailable or explicitly uncertain. The fixture shows human-authored manual work continues while both inference slots remain occupied. |
| Current identity, policy, journal or required audit unavailable | Deny the affected protected action or private projection. Retry by its original key after dependencies recover if the outcome was uncertain. |
| Simulator receive reply lost | Keep delivery unknown until the stable dispatch lookup resolves. Continue to distinguish delivery from human acceptance or connection. |
| Capture incomplete, diverged, expired or forbidden | Preserve the typed replay state or deny the request. Show only authorized digest metadata. |
| Cluster unavailable | Public fallback has its independent host route where the separately validated installation exists. Host help depends on its own current identity and custody. Use the current release's approved fallback content and avoid any connection claim. |

Select a candidate for rollback only when its artifact, configuration and current negative authority are verified. Preserve revocations, holds and expiry. Use the current-authority [recovery procedure](../IMP/slices/IMP-09-backup-and-recovery/README.md) for protected restore or promotion. Restrict private serving and retain independent static fallback when the compatible candidate or current authority is uncertain.
