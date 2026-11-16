# Review recovery implementation

**Session and IMP-03 closed on 2026-11-16.** [Accepted execution ledger](../../../../executions/2026-11-16-IMP-03/ledger.json). Implementation work is complete within the accepted scope; demo resources and evidence are retained. Source publication was separately authorized by the user: commit, push and PR from `feat/imp-03-protected-manual-service` to `main`.

Implemented and deployed. **Three successive fresh runs passed in one Google Chrome for Testing profile**, without cookie/cache clearing or test retries. **G-03 human review was performed and approved by the user on 2026-11-16.** [Acceptance record](G-03-acceptance.json). [Pre-acceptance test summary](results.json) is retained unchanged; its pending human-acceptance flag describes the time it was recorded.

The UI restores conversations, assignments, encrypted drafts, stable submission intents and supervisor grants from the server. Duplicate tabs have explicit **Use this tab** control. Request deadline failures preserve login and tab state. Fixed actor realms on the existing Keycloak server isolate sign-in sessions; application accounts and existing infrastructure are retained.

Current toolkit environment: `imp03-review`. Human review was prepared with run `8135ccd8-427c-4b10-a950-9d316771e68d` in four ordinary native Chrome for Testing tabs. Use the toolkit below to inspect current run state. The former `imp03-continuation` environment is historical; its test runs are closed.

From the repository, inspect the current run and obtain the issued usernames:

```sh
.venv/bin/python -m tools.demo doctor --environment imp03-review
.venv/bin/python -m tools.demo run list --environment imp03-review
.venv/bin/python -m tools.demo actors list --run 8135ccd8-427c-4b10-a950-9d316771e68d
```

For each slot (`participant`, `worker1`, `worker2`, `supervisor`), use its username from `actors list` and retrieve its password/code explicitly. Replace `participant` below for another slot. Seeds are never displayed; credentials stay outside Git.

```sh
.venv/bin/python -m tools.demo credentials reveal --environment imp03-review --actor participant --reveal-password
.venv/bin/python -m tools.demo credentials otp --environment imp03-review --actor participant --fresh
```

The checked visible sequence is:

1. Sign in in the four role tabs. Participant: start a fictional conversation, acknowledge the disclosure, ask for a human, then submit the fictional situation.
2. Worker1: refresh queue, reserve, accept, and prepare confirmation. Participant and worker each confirm their own app channel; worker confirms the connection.
3. Exchange manual messages. Reload recovers saved work; **Use this tab** restores interactive control. **Return to workspace** recovers navigation after a conversation becomes inaccessible.
4. Supervisor: observe, explicitly authorize interruption, then take over. Fresh channel confirmation is required afterward. Workforce authentication requires renewal after five minutes; **Sign in** preserves server-saved work.

To repeat from scratch, close the current run, then create another. Existing conversations remain retained; no fence or browser profile is reset.

```sh
.venv/bin/python -m tools.demo run close --run RUN_UUID
.venv/bin/python -m tools.demo run create --environment imp03-review --scenario manual-service
```

The detached operator maintains workload trust and restores temporary inputs from durable Keychain custody. If unavailable, restart it using the private descriptor, then run `doctor`:

```sh
CARE_LINK_IMP03_PROFILE=continuation-001 .venv/bin/python -m tools.imp03_shared.review_start \
  --descriptor "$HOME/Library/Application Support/CARE-Link Demo/environments/cont1-isolated/operator-bootstrap.json"
```

Verification: **738 Python tests, 81 web tests, separate TLS provisioning check, eight English/French WCAG scans, three complete Chrome cycles**, read-only database effect counts, actual credential rotation and operator restoration. Independent source review findings were corrected. Early live failures exposed provider SSO sharing, signed workspace-selection disagreement, deadline misclassification and orphaned view leases; setup/driver errors were also corrected. Raw diagnostics remain private.

The user separately approved both lab CA imports into the login keychain for TLS. Native certificate verification and all four native reviewer pages passed. System keychain and DNS were unchanged. Continuation transport certificates expire on **2026-11-20**; readiness checks enforce validity.

The original target and conversations are retained; its fence remains1 and continuation remains0. Participant admission and IMP-04 remain inactive. The user subsequently authorized commit, push and PR publication; the acceptance record and pre-acceptance evidence remain unchanged. Toolkit usage and custody details: [reference commands](../../../../../../tools/demo/README.md). Repeatable browser suite: [source](../../../../../../tests/e2e/imp03-review/live.spec.ts).
