# Extended G-03 live observations

These checks use the actual continuation target and issued provider accounts. They do not create accounts, mutate databases directly, inject a cookie/token, fabricate API success or infer human acceptance. The primary coordinator owns target creation, scoped fault/revocation application and durable observations. Trace, screenshots and video stay off; raw outputs remain in the owner-only directory.

Use the original private browser configuration fields plus `worker2: { username, password, totpSecret }` and a fourth distinct `accounts.worker2`. Both workers have actual role `worker`, with separate provider subjects, account UUIDs and MFA credentials. `ignoreHTTPSErrors` must be false. The suite refuses a browser-trust bypass. An unused security provider account may exist, but has no application registry binding: the current BFF has no public identity-restriction endpoint.

Set `CARE_LINK_IMP03_E2E_CONFIG` and `CARE_LINK_IMP03_E2E_OUTPUT` as in the base suite, then run with this directory's `playwright.config.ts`. Existing output is operator-owned; observations use exclusive creation. `CARE_LINK_IMP03_BROWSER_RESOLVER` optionally supplies the exact Chromium host-resolver rules needed by the scoped Linux browser. It changes no host DNS. `CARE_LINK_IMP03_EXTENDED_LOCALE` accepts `en-CA` or `fr-CA`.

`CARE_LINK_IMP03_EXTENDED_CASE` selects:

- `ui`: actual disclosure text and exact template/digest/locale acknowledgement, disabled UI intake plus server pre-disclosure denial, fictional UI turn and actual participant attribution. Run once per locale. This is automated artifact/interaction evidence, not human language approval.
- `race`: the UI/intake case, concurrent real reservations by two separately issued workers, loser acceptance denial, sole winner acceptance, real two-party SSE handshake, one accountable owner and attributed message delivery. `case-binding.json` identifies only the exact synthetic rows for separate coordinator durable inspection.
- `buffered`: the race case followed by a real already-authorized message GET held by Playwright's transport across actual takeover. It observes the old worker's real SSE authority-loss/error, releases the actual response (or verifies independent client cancellation), and watches DOM mutations for previously undisplayed stale content. No API body/status is manufactured. This covers one browser-transport/UI interleaving, not every server or OS buffering boundary.
- `revocation`: UI/intake followed by the operator barrier below, actual read and prepared-CSRF POST denial, an already-open channel's authority-loss signal and a fresh page's denied messages read. This targets the participant's exact session support ACL; it does not claim whole-account identity revocation.
- `commit-ack`: real intended POST after the operator arms an exact one-shot driver marker; real commit then lost acknowledgement produces COMMIT_UNKNOWN, followed by original-key reconcile/replay. The coordinator must separately prove exactly one queue row, committed operation and canonical PERMIT audit. The capability is disabled afterward.
- `operations`: protected reads and an active stream across exact supervised core stop/start; unavailable/private-content behavior, independent help/static, restored current rights and previous ACL restriction are checked. This is not arbitrary crash recovery or capacity acceptance.
- `all` (default): all of the above on one fresh conversation, with scoped ACL revocation last.

## Operator ACL barrier

The browser obtains current access and a valid CSRF proof before writing owner-only `extended-revocation-ready.json`:

```text
{ session: "imp03-002", phase: "acl-revocation", nonce, session_id, principal_id }
```

The primary must validate these fields against the fresh target/journal binding, apply the exact current participant/session support-ACL restriction and inspect its actual effect. Only then write `extended-revocation-applied.json` with exactly the same fields, owner-only. The script waits up to120 seconds, then sends the actual intended POST using the already acquired CSRF proof. A receipt alone cannot pass: the HTTP requests, fresh-page read and existing stream must deny/observe scope loss. The coordinator must separately compare relevant durable state/audit/output effects. There is no automatic ACL restoration or rights rewind in this browser script.

The original retained core fence is already generation1 and must never be reset for these cases. Use only the separately scoped continuation target. The original one-way fence evidence is retained separately; no fence reset or automatic final fence is invoked here.

The login helper exercises the actual **Main account → Requested sign-in role → Sign in** controls, including the deployed approved-origin configuration. It never calls the login API to bypass a disabled visible sign-in button. Actual provider password/TOTP and server-role verification follow that UI navigation.

The `stability` case selects two additional live tests. One aborts actual access
reads before an intended command, requires zero intended POSTs, then reopens the
same conversation under restored current authority with its in-memory draft.
The other observes a real active participant for six minutes, samples current
authorization every15s, requires authorized projection recovery within the
existing5s request bound and reopens the same conversation/draft. Its explicit
90s mode is a shorter diagnostic only. These tests create separate synthetic
conversations; raw outputs stay private and no successful authority response is
fabricated. They do not establish arbitrary-crash/full serving recovery.
