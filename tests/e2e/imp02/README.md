# IMP-02 real browser qualification

These tests drive the configured local Keycloak UI and the actual BFF, identity store, help spool and static listener. They contain no token injection, fake login endpoint, mocked permit or automatic service installation/start. Role accounts are separate synthetic profiles used by the same project owner; this is not independent-human acceptance.

The coordinator owns the pinned root dependencies (`@playwright/test` and `@axe-core/playwright`), lab startup and credential provisioning. The suite fails when real-lab configuration is absent; it does not silently replace it with a fixture lane. Unit/component tests remain a separate evidence class.

Create an owner-only JSON file outside the repository, with the actual provisioned values:

```json
{
  "mainOrigin": "https://main.localhost:18443",
  "helpOrigin": "https://help.localhost:19443",
  "oidcOrigin": "https://id.localhost:20443",
  "staticOrigin": "https://static.localhost:21443",
  "participant": {
    "username": "PROVISION_LOCALLY",
    "password": "PROVISION_LOCALLY",
    "totpSecret": null
  },
  "otherParticipant": {
    "username": "PROVISION_LOCALLY_OTHER",
    "password": "PROVISION_LOCALLY",
    "totpSecret": null
  },
  "worker": {
    "username": "PROVISION_LOCALLY_WORKER",
    "password": "PROVISION_LOCALLY",
    "totpSecret": "PROVISION_REAL_TOTP_LOCALLY"
  },
  "ignoreHTTPSErrors": true,
  "staticReviewProfile": "owner_review_local_demo"
}
```

`staticReviewProfile` explicitly selects the expected receipt semantics; the default is `independent`. Owner-demo runs require canonical `/static/v1/manifest` to remain unavailable and inspect only `/demo-static/v1/manifest` for the non-independent owner receipt. The values above are documentation placeholders. Local role provisioning must map the exact provider issuer/subject; provider group claims alone never grant a role. The worker flow uses its real provider TOTP challenge. The generated code stays in memory and is never attached to a report.

Use distinct hostnames for the BFFs, provider and static process: cookie scope does not distinguish ports. Chromium receives a process-local `*.localhost → 127.0.0.1` resolver rule. No host DNS configuration is changed. The reverse proxies/provider must separately resolve the same pinned names. `ignoreHTTPSErrors` is an explicit temporary-CA browser setting; runs using it do **not** prove browser certificate trust or replace the platform's actual TLS/peer validation tests.

From the repository root, after authorized startup and locked dependency installation:

```sh
export CARE_LINK_IMP02_E2E_CONFIG=/private/tmp/OWNER_ONLY_LAB_BROWSER_CONFIG.json
export CARE_LINK_IMP02_E2E_OUTPUT=/private/tmp/care-link-imp02-browser-results
mkdir -p -m 700 "$CARE_LINK_IMP02_E2E_OUTPUT"
export CARE_LINK_IMP02_BROWSER_CHANNEL=chrome
pnpm exec playwright test --config tests/e2e/imp02/playwright.config.ts
```

`CARE_LINK_IMP02_BROWSER_CHANNEL=chromium` is the default and uses the matching separately installed browser. Set `CARE_LINK_IMP02_BROWSER_PATH` only to an explicitly selected local executable. Tests do not download browsers or packages. The report records the actual browser version. The evidence directory must be owner-only (mode 0700); existing broader permissions are rejected rather than silently changed. Traces, video, automatic failure screenshots and persisted authentication state are disabled because provider login and private session material must not enter ordinary evidence. The public static-page tests explicitly attach desktop/mobile screenshots and bind them to the raw HTTP body hash and publication manifest; provider/private pages are not captured. Authentication failure details are suppressed; investigate private failures in the isolated lab, without copying credentials into reports.

The normal phase covers:

- Real participant/workforce login and MFA in separate browser profiles, role/ownership/CSRF negatives and honest `accepted_unconnected`.
- Separate BFF cookie custody, no private browser storage, logout and forged-callback denial.
- Actual upstream commit followed by an intercepted lost response, full browser navigation/relogin and recovery of the same durable create identity.
- Both EN/FR static pages and help surfaces with axe WCAG rules, keyboard focus and 320px/200% text reflow. Axe summaries omit private HTML and list incomplete checks separately; automated passes do not establish human screen-reader or language review.

Run the full real-clock step-up qualification separately (approximately six minutes, no shortened cooldown or clock override):

```sh
CARE_LINK_IMP02_E2E_PHASE=cooling pnpm exec playwright test --config tests/e2e/imp02/playwright.config.ts
```

It proves first MFA starts the required five-minute cooling, consumed-proof replay denies, and a second fresh MFA after the boundary verifies only the exact ceremony. Progress is divided into real-clock intervals of at most 30 seconds. It performs no export/delete and grants no ambient AL3 session.

Run the outage phase only with the coordinator supervising leased lab services:

```sh
export CARE_LINK_IMP02_E2E_PHASE=outage
export CARE_LINK_IMP02_OUTAGE_CONTROL=/private/tmp/OWNER_ONLY_IMP02_OUTAGE_CONTROL
pnpm exec playwright test --config tests/e2e/imp02/playwright.config.ts
```

The test atomically writes `request.json` with `{nonce, phase}` where phase is `main_down`, `identity_down` or `restored`. The owner-controlled supervisor changes only named lab resources, then atomically writes `ack.json` with the same nonce/phase, `status: "applied"` and `mock_used: false`. The main/identity outage acknowledgement waits are each bounded to 45 seconds; verified restoration has a 150-second acknowledgement deadline within the 360-second test limit. This accommodates restoration of the same persisted lab node. API/UI authority assertions retain their existing deadlines. The test requests restoration in `finally` and independently checks actual API/UI/static outcomes after each acknowledgement. A checkpoint file is not denial or outage proof on its own. Record whether the real operation stopped only the main process or the actual application cluster; do not generalize the former into cluster-loss evidence.

Type/lint checks for this source:

```sh
pnpm exec tsc -p tests/e2e/imp02/tsconfig.json
pnpm exec eslint tests/e2e/imp02 --max-warnings 0
pnpm exec prettier --check tests/e2e/imp02
```

The source-only operator-session utility initiates the real BFF protocol with `role: operator` / `return_route: operations`, then drives the actual provider UI and MFA. It does not insert a DOM role option, mint a proof or bypass local entitlements. Load the provisioned `users.main` mapping from the separate owner-only provider-state file:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/care-link-imp02-002/browsers \
node --experimental-strip-types tests/e2e/imp02/operator-session.ts \
  --lab-config /ABSOLUTE/PRIVATE/LAB/browser-config.json \
  --provider-state /ABSOLUTE/PRIVATE/LAB/provider-state.json \
  --output-cookie /ABSOLUTE/PRIVATE/LAB/FRESH_MAIN_COOKIE_FILE
```

The output parent must already have mode0700, and the cookie output path must be new. Only after actual provider OTP submission and a fresh server `BrowserSession` matching the provisioned main UUID, `operator`, and `AL2`, the utility writes exactly the configured main Secure/HttpOnly/host-only session cookie value (no newline or JSON envelope) to that mode0600 file. `--session-cookie-name` may specify the explicitly configured main cookie name; its default is `__Host-care-link-session`. The utility emits only safe browser/role/mapping/assurance metadata. It creates no persisted browser authentication state, screenshot, video or trace. Failed qualification removes only its own reserved empty/partial output. The coordinator must use and dispose of this short-lived credential through the separately authorized immediate retention check; it must never enter Git, ordinary logs or demonstration evidence. Type stripping is an experimental Node22 execution feature of this local verification utility, not an application runtime requirement.
