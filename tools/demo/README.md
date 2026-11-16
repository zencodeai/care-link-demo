# Demo reference toolkit

`python -m tools.demo --help` manages explicit synthetic environments and review runs. State defaults to the durable OS user-state directory, outside Git and temporary runtime files. No command defaults to the retained original target.

Register an already-owned environment with `environment register --manifest FILE`. The strict v1 manifest binds `environment_id`, `core_protocol: care.review.v1`, `scenario_version: "1"`, base domain/port, four exact actor slots, an ownership receipt and a private operator socket. Registration verifies existing ownership; it does not provision resources or grant authority.

- `environment inspect`, `doctor --environment ID`: recorded binding and actual operator readiness/credential availability.
- `run list --environment ID`: discover the persisted current run and retained history after a terminal/chat restart. Use `run resume` to reconcile authoritative state.
- `run create --environment ID --scenario manual-service`, `run resume --run UUID`, `run close --run UUID`: stable persisted operation identities and checked runtime receipts.
- `actors list --run UUID`, `run open --run UUID --actor SLOT`: non-secret actor URLs in ordinary browser tabs.
- `credentials import --environment ID --actor SLOT --stdin`: explicit JSON `{password,totp_secret,revision}` via stdin only.
- `credentials reveal --environment ID --actor SLOT --reveal-password`, `credentials otp ...`: explicit local password/code output; seeds are never displayed. Use `credentials otp ... --fresh` to wait for the next OTP window (at most31seconds), especially after password verification or a recent login. This does not retry rejected codes.
- `credentials rotate --environment ID --actor SLOT`: provider-confirmed password-only revision change, preserving the existing TOTP seed. TOTP re-enrollment is a separate ceremony. Resume a pending rotation with its original `--operation-id`; old metadata is not retired before confirmation.

The default secret adapter uses macOS Keychain without secret command arguments. An explicit `--vault-key-file /absolute/private/key` selects encrypted fallback; the existing 32-byte key and its directory must be owner-only. Never store that key in the repository or alongside public artifacts. The toolkit does not create a replacement key when one is missing.

The operator socket is owner/private-path checked and its connected peer UID is verified by the OS. The operator process, not this CLI, owns provider/database administration credentials. Business actions stay in the protected application gateway. The toolkit does not reset fences, erase unresolved conversations or purge old runs.

`run inspect` reads durable local state; `run resume` rechecks the authoritative runtime with the original operation identity. An unavailable/unverified adapter remains pending and returns a redacted error, never success. One active or partial run is allowed per environment. Toolkit registry schema, scenario version and runtime protocol must agree before mutation.
