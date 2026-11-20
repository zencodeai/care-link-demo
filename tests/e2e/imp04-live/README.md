# IMP-04 isolated live browser qualification

These tests target only `https://plans.localhost:30443` and the new provider
`https://id.plans.localhost:31443`, with native certificate verification. They
never select an IMP-03 operator profile. The coordinator must first deploy the
accepted separate target and initialize its dedicated Chrome NSS CA custody.

The private `browser.json` has `mainOrigin`, `oidcOrigin`, `caFile`, `endpoint`
(or `wsEndpoint`) and `actors`. Each of the nine exact slots has `accountId`,
`role`, `username`, `password` and `totpSecret`. No credential belongs in this
directory. Operator/security use genuine application login API intents and the
actual provider password/OTP UI; other actors start through the visible role
selector and sign-in button. Cookies/credentials are not fabricated.

Run from the repository with an owner-only output directory and private inputs:

```sh
CARE_LINK_IMP04_E2E_CONFIG=/private/tmp/care-link-imp04-002/browser.json \
CARE_LINK_IMP04_E2E_OUTPUT=/private/tmp/care-link-imp04-002/qualification-normal-001 \
CARE_LINK_IMP04_E2E_PHASE=normal \
pnpm exec playwright test --config tests/e2e/imp04-live/playwright.config.ts
```

Phases are `signin`, `normal`, `directory`, `lifecycle`, `accessibility`, `race`,
`dependency`, `absent-race`, `delegation`, `delegation-expired`, `normal-continue`,
`authority-loss`, `reload-only`, `report-ui`, `pending-ui`, `manual-regression` or `all`.
`all` includes only the baseline normal/directory/lifecycle/accessibility cases;
fault, timing and independently admitted delegation phases require explicit
selection. Every phase checks the nine actual accounts/roles/assurance in
separate contexts. `normal` exercises
actual visible sharing preview and subject-bound provider MFA, scoped plan
disclosure, attributed saved reports, assigned-worker conflicting safety report,
revocation, real wall-clock expiry with a narrower surviving grant and committed
work restoration by manually selected IDs. It writes private `live-state.json`.
It also checkpoints session/subject/plan IDs in `normal-checkpoint.json` before
the visible ceremony, then records the completed visible grant/proof.
`normal-continue` reads that checkpoint from `CARE_LINK_IMP04_E2E_STATE`, requires
the original visible grant already revoked, completes fresh real subject MFA,
and runs only the subsequent expiry/revocation/reload block. Earlier plan,
report and assignment commands are never replayed. Expiry-grant IDs are saved
before the first shared read so timeout outcomes can be reconciled. Existing
grants age on the real wall clock; continuation does not silently clear them.
`manual-regression` creates a separate PID/worker2 support session, establishes
both actual EventSource transports and server-issued channel challenges/ACKs,
confirms a real human connection, exchanges fictional messages and verifies the
same stable message key yields one durable message in both actual reads. It
always closes both streams and never modifies the earlier plan's assignment.
This additional regression phase runs only when explicitly selected.
`directory` ingests all seven fixed signed fixtures, checks honest stale views
and unknown/unavailable states, rejects an unknown artifact digest into quarantine
and exercises participant denial plus source suspension across reingest. A
retained security-suspended entry remains suspended on a rerun; the harness binds
its actual initial admission and never resets it to manufacture a stale baseline.
`lifecycle` closes a different PID's support conversation, verifies its active
plan survives, then retires it; copy anchors still require read-only DB evidence.
`accessibility` does EN/FR axe and keyboard-focus checks for four actor roles;
it attempts genuine native Chrome200percent desktop zoom through browser
accelerators and counts that only when doubled pixel ratio, halved CSS viewport,
constant outer viewport and unchanged visual/pinch scale are observed. CSS or
pinch scaling is never substituted. Unsupported native zoom is `not_run` and
requires human completion. Browser checks do not replace human visual or
screen-reader qualification.

Initial authentication is sequential: close each provider/app context after
capturing its genuine browser state, then restore only that exact same actor's
state into separate blank contexts. API actors use the actual main HTML/CSP
with only app JavaScript assets aborted; no API response is intercepted. Real
UI cases load the normal app bundle explicitly. This keeps the approved browser
resource budget without weakening native TLS, CSP or current authorization.
Owner-only `progress.json` checkpoints record sign-in completion safely.

OTP single-use counters persist across phases in the exact owner-only target
file `/private/tmp/care-link-imp04-002/otp-used-windows.json`. It holds usernames
and last reserved thirty-second counters only. Reservations are saved before
submitting an OTP; the driver waits for a new window rather than retrying a code.
No OTP code or seed is written to this file or public evidence.

For a bounded sign-in diagnostic only, `CARE_LINK_IMP04_E2E_PHASE=signin` can
add `CARE_LINK_IMP04_E2E_SLOTS=worker1` (or a comma-separated set of exact slots).
Other phases reject actor subsets. Missing visible login POST diagnostics retain
only CSRF/login request paths, methods/statuses and derived panel/button state;
they never include authorization URL queries, forms, headers or response bodies.
API transport failures record only a whitelisted error-name category, duration
and fetch/body stage. The existing fifteen-second deadline is retained; raw
exception messages and private response bodies are never copied into it.

Later phases can restore only the real previously saved owner-only session
states (they recheck each issued identity and sign in again if stale). Use a
new output directory for every attempt, retaining old results:

```sh
CARE_LINK_IMP04_E2E_CONFIG=/private/tmp/care-link-imp04-002/browser.json \
CARE_LINK_IMP04_E2E_STATE=/private/tmp/care-link-imp04-002/qualification-normal-001 \
CARE_LINK_IMP04_E2E_RESUME=1 \
CARE_LINK_IMP04_E2E_OUTPUT=/private/tmp/care-link-imp04-002/qualification-directory-001 \
CARE_LINK_IMP04_E2E_PHASE=directory \
pnpm exec playwright test --config tests/e2e/imp04-live/playwright.config.ts
```

`race` requires the coordinator's explicit new-target timing adapter activation.
Each `race` and `absent-race` attempt creates a new actual synthetic session,
subject and plan with its own real subject-bound MFA proof, writes those IDs to
private `live-state.json`, and never reads a prior phase's rights as its baseline.
Previously failed-attempt grants/restrictions remain retained on their subjects.
Actual recipient success and genuine CSRF are warmed before the timing hold.
The receipt-bound persistent `tools.imp04_deployment.barrier_bridge` arms/waits/
releases the real data service. The first case revokes after metadata locks are
released and before real policy; the second waits for genuine grant expiry
immediately before final output. Neither changes clocks, policy inputs or auth.
The normal serving image must have the adapter disabled after qualification.
Failure to enter or release the exact barrier is a harness failure; it is never
counted as a successful rights restriction. Source/adapter races remain distinct
from these deployed timing checks.

`dependency` invokes only the inspected new-target identity/PDP/journal container
pause/resume CLI, always resumes in cleanup, rejects projection while paused and
checks ordinary current reads after recovery. `absent-race` uses the real
consent-grant policy barrier while an old grant is concurrently revoked; rejected
pending command IDs are retained for coordinator verification of zero new DB
grant effects. `delegation` requires separately admitted private `delegation.json`
(override with `CARE_LINK_IMP04_E2E_DELEGATION`): exact PID subject, carer grantor,
`plan.strategies`, purpose `plan` and natural ten-minute expiry. It denies wider
fields/purpose/subject and demonstrates only the permitted scope. The separate
`delegation-expired` phase refuses to run until actual expiry, then checks denial;
it never adjusts the clock. The coordinator supplies runtime delegation write
denial evidence independently.

`authority-loss` requires a separately issued fresh case carer in the root's
private case browser configuration. It creates a new PID subject/plan, admits
only an exact strategies/plan delegation via the fixed-case host helper, and
uses the genuine carer browser to grant to worker2. The positive projection and
control channels (including the fixed-case persistent authority channel) are
warmed before minting a fresh signed proof from the real
operator session. That proof's actual operation/nonce/expiry binds a journalled
business-principal revocation of the new case carer while a recipient read is
held. Strict denied status, no projection and later denial must all hold while
the grant and delegation remain otherwise unexpired. This is grantor principal
authority loss, not a literal provider-role-change claim. The case principal
stays revoked; existing actors/rights are never reset. No caller-constructed
Actor, role or clock enters the helper; a proof expiry is a failed attempt and
does not authorize deadline extension or proof renewal inside the hold.

All Playwright results and browser storage states remain private. `observations.json`
contains selected safe IDs/states/counts, but inspect/redact it before copying to
the documentation evidence folder. Raw traces/video/screenshots are disabled.
`phase_coverage` counts each phase's own required passing observations; missing
browser checks cannot yield a passing phase. `not_run` is phase-specific and
retains separately owned DB/manual evidence without implying other phases were
globally not executed. A passing phase
is no human G-04 decision, clinical certification or participant admission.

Suggested clean coordinator sequence: `signin` → `normal` → `report-ui` and
`reload-only` using that normal state → `directory` → `lifecycle` →
`accessibility` → explicit timing-adapter activation → independent `race` and
`absent-race` → restore default serving → `pending-ui`, `dependency` and
`manual-regression`. Actual independent delegation admission and expiry plus
network/DB/issuer recovery remain coordinator-owned steps. A fresh dedicated
output directory is mandatory for every attempt; no success retries occur
inside an application request or by changing authorization deadlines.

Source check: `pnpm exec tsc --project tests/e2e/imp04-live/tsconfig.json`.
