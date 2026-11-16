# G-03 step-by-step closure and validation guide

Follow this sequence to close IMP-03. **The first remaining engineering task is to create the independent runtime environment.** The launcher exists, but its examples still contain unissued infrastructure and account placeholders. Infrastructure provisioning and live qualification remain unexecuted against an actual IMP-03 target.

Expanded at the user's request on 2026-11-10. Previously executed session002 results below are historical evidence; this documentation update does not rerun tests, deploy services or record acceptance. The existing IMP-02 lab remains outside the mutation scope. Use synthetic stories and service data only. Preserve the no-police-integration and no-autonomous-emergency-contact constraints. Participant admission remains disabled.

Command locations:

- **Mac workstation:** repository at `/Users/main/Workspace/projects/care-link/care-link-demo`.
- **Linux target:** independent IMP-03 environment on this workstation, repository at `/app`, environment at `/app/.venv`, built client at `/app/apps/web/dist`.
- **Linux supervisor:** the target's privileged operator, responsible for UIDs, mounts, directories and service processes.

## 1. Start a dedicated IMP-03 qualification session

Use a new chat and dedicated session folder, such as:

```text
doc/IMP/slices/IMP-03-protected-manual-service/sessions/003-live-qualification/
```

Read the [current handoff](handoff.md), [slice index](../../README.md), [runtime runbook](../../../../../../tools/imp03_runtime/README.md), canonical [IMP workflow](../../../../../../.codex/IMP_WORKFLOW.md) and [human-decision procedure](../../../../06-demonstrations-and-human-decisions.md).

Record the authorized resources, ports, directories and actions in the qualification work packet. Confirm the accepted G-02 dependency binding still applies. Keep the existing IMP-02 lab outside that resource scope. This guide does not itself activate host setup or deployment.

**Completion condition:** the qualification session has a concrete scope and resource owner; no acceptance has been inferred.

## 2. Record the candidate you will qualify

On the Mac workstation:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
git status --short
git branch --show-current
git rev-parse HEAD
```

Compare current source/input hashes with the session002 [candidate manifest](candidate-manifest.json). Preserve existing uncommitted changes. Record source and dirty-diff hashes, including untracked implementation files, for the qualification candidate.

A clean commit is optional for candidate binding. Commit, push, merge and deployment remain separate actions requiring their applicable authorization. Material source/configuration changes require rechecking affected behavior and updating its binding.

**Completion condition:** the candidate is identifiable and its differences from the recorded candidate are understood.

## 3. Reproduce complete local verification

Source-only, with the already installed locked environment:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
UV_CACHE_DIR=/private/tmp/care-link-uv-cache .venv/bin/python tools/check.py
```

This deliberately skips opt-in PostgreSQL/OPA/provisioning and Linux-only checks when their fixtures are absent. The full executed lane is reproducible with:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
UV_CACHE_DIR=/private/tmp/care-link-uv-cache .venv/bin/python -m tools.imp03_verification.run_checks \
  --output /private/tmp/care-link-imp03-g03-check-001 \
  --opa /private/tmp/care-link-imp03-tools/opa
```

Use a fresh output path each time. Prerequisites: Docker, uv, pnpm, Node, existing locked Python dependencies, the digest-pinned PostgreSQL image, and repository-pinned OPA1.22.2 for macOS ARM64. If absent, use the existing [session001 acquisition command](../001-implementation/G-03-validation-guide.md#3-run-the-full-postgresql--opa--journal--capture-verification); no installer or download runs implicitly. The runner verifies OPA's SHA before execution, refuses an existing `care-link-imp03-001-postgres`, archives old owner-only fixture files, starts only that loopback25433/tmpfs fixture, runs the full checker, then runs provisioning separately to avoid global-role collisions. Cleanup verifies the exact container ownership label. It never connects to the accepted IMP-02 database.

Historical session002 result: **505 Python passed, 2 declared skips; 56 TS/UI/parity passed**, followed by **1 provisioning/audit-barrier test passed**. The two full-lane skips are the Linux-only UID harness and the separately invoked provisioning test. Real PostgreSQL TLS1.3, OPA, canonical audit, signed host journal, consistent encrypted capture/import, new signed metadata/final HTTP adapters and current identity callbacks were exercised. Provider and workload provenance in adapter tests are explicitly fixtures. This is not deployed trust/browser evidence.

The isolated developer core artifact also builds and smokes with the signing dependency while excluding business/identity packages and database drivers:

```sh
.venv/bin/python tools/build_core_image.py --tag care-link-core:imp03-runtime-002
.venv/bin/python tools/smoke_core_image.py --image care-link-core:imp03-runtime-002
```

It still defaults to the developer app. The new source launcher uses the locked development workspace; per-role deployment-image isolation is a separate qualification.

Investigate any new failure before proceeding and retain the sanitized logs.

**Completion condition:** relevant current checks pass, declared skips are explained and evidence is bound to the candidate.

## 4. Create the independent Linux infrastructure

This setup is still required; the source launcher does not provision it. Supply these resources independently of IMP-02:

| Component | Required result |
|---|---|
| Linux runtime | Isolated IMP-03 processes/containers, networking and storage on the accepted workstation |
| SPIRE | Independent trust deployment and actual workload attestation |
| Envoy | Separate role proxies using issued SVIDs and exact peer routes |
| PostgreSQL | Independent TLS endpoint and migration authority |
| OIDC provider | Independent realm/client and separately issued synthetic actor accounts |
| OPA | Linux executable with a verified, recorded digest |
| Browser TLS | Certificate matching the private manual-service hostname |
| Help/static | Independently available surfaces for dependency-loss checks |
| Host journal | Separate credential and filesystem custody |

Record actual addresses, ports, image digests, mounts, storage and ownership. Configure network restrictions for the intended service paths. Do not reuse IMP-02 credentials, sockets, databases, volumes, namespaces, SPIRE registrations, provider realm or fences. Keep machine duties capability-disabled unless separately in scope and admitted.

**Completion condition:** the independent resources exist and their actual bindings are known. Rendered examples alone do not satisfy this step.

## 5. Issue actor accounts and configure OIDC

Create separate synthetic participant, worker and supervisor accounts. Configure MFA for all three accounts used by the supplied browser demonstration, including the participant's fresh recovery ceremony.

Record each actual provider subject and its application account UUID. Configure the exact callback URL, provider endpoints, client credentials, access-token audience and MFA profile. The access-token audience must differ from the browser client ID. Browser/provider certificate trust and DNS/address mapping must match the actual target.

**Completion condition:** accounts are actually issued and their UUIDs, subjects and allowed roles match the intended registry. Illustrative UUIDs and `ISSUED_*` values do not establish issuance.

## 6. Complete the private runtime input files

On the Linux target, copy the [binding example](../../../../../../tools/imp03_runtime/bindings.example.json) to:

```text
/operator/imp03-bindings.json
```

Replace every `ISSUED_*` placeholder and every illustrative address/path with the actual target value. Supply `/operator/imp03-admin.json` with exactly these fields:

```json
{
  "identity_admin_dsn": "ACTUAL_PRIVATE_VERIFY_FULL_ADMIN_DSN",
  "data_admin_dsn": "ACTUAL_PRIVATE_VERIFY_FULL_ADMIN_DSN"
}
```

Both files must be owner-only, mode `0600`, outside the repository. Verify:

- Identity and data use different runtime passwords and their separately assigned logins/databases.
- Database TLS uses `sslmode=verify-full` and the correct CA.
- Actor subjects and UUIDs match step 5.
- Browser/provider hostnames and certificates agree.
- Role socket paths, mounts and UIDs match the deployment.
- Linux OPA's digest matches the actual executable.
- No IMP-02 credential, socket, provider realm or database is referenced.

**Completion condition:** inputs describe actual issued target resources; private material remains outside source and evidence.

## 7. Prepare custody, generate configuration and initialize state

Follow the [exact runtime startup/custody commands](../../../../../../tools/imp03_runtime/README.md#exact-preparation-and-startup) as the Linux supervisor.

Execute the complete runbook block once. It creates fresh directories with the required custody and mode0711 ancestors, runs the three launcher operations below, then installs the generated trust/proxy configurations. This excerpt identifies the operations already included in that block:

```sh
set -eu
cd /app
umask 077
/app/.venv/bin/python -m tools.imp03_runtime prepare --bindings /operator/imp03-bindings.json --output /run/care-link-imp03-002/configuration --assign-ownership
/app/.venv/bin/python -m tools.imp03_runtime render-mesh --bindings /operator/imp03-bindings.json --output /operator/imp03-rendered-mesh
/app/.venv/bin/python -m tools.imp03_runtime provision --root /run/care-link-imp03-002/configuration --admin-config /operator/imp03-admin.json
```

Provision is fresh-only: `imp03_identity_002` / `imp03_identity_runtime_002` and `imp03_runtime_002` / `imp03_data_runtime_002`; existing DBs/logins/global roles/journal are refused before creation. Partial resources are retained for inspection. Runtime role configs never receive admin DSNs.

Expected database bindings:

| Role | Database | Runtime login |
|---|---|---|
| Identity | `imp03_identity_002` | `imp03_identity_runtime_002` |
| Data | `imp03_runtime_002` | `imp03_data_runtime_002` |

If provisioning fails after creating partial resources, preserve them for inspection. Do not repeatedly rerun it or broadly delete resources.

**Completion condition:** migrations, exact account/principal bindings, initial control state and journal are initialized; private configuration belongs to its assigned role.

## 8. Start and verify trust services and proxies

Start the independent SPIRE infrastructure and issue these workload identities:

```text
spiffe://care-link.demo/demo/identity
spiffe://care-link.demo/demo/core
spiffe://care-link.demo/demo/data
spiffe://care-link.demo/demo/pdp
spiffe://care-link.demo/demo/journal
```

Use the [runbook's exact trust commands](../../../../../../tools/imp03_runtime/README.md#deterministic-dependency-barriers) to start the fence as UID22000, role authorization services as UIDs22031–22035, and role Envoy proxies as UID22002 within their independently attested workload isolation. Keep restriction authority separate at UID22001 and preserve reserved reader GID22999. Register actual workload selectors and pinned images; do not synthesize SVID claims.

Capture evidence that:

- Correct workload/route combinations succeed, while wrong or absent workload identities deny.
- Spoofed browser headers cannot provide workload authority.
- SVID renewal works; expired certificates and current fences deny.
- Applications cannot read another role's credentials or reuse its egress socket.
- Deployed network and per-role process/container isolation enforce the intended boundaries.

Do not expose unprotected TCP application listeners.

**Completion condition:** actual current trust, renewal, custody and route enforcement have been observed. Configuration rendering alone does not satisfy this step.

## 9. Check and start all five application roles

Use this mapping:

| Role | Application UID |
|---|---:|
| Identity | 22011 |
| Core | 22012 |
| Data | 22013 |
| PDP | 22014 |
| Journal | 22015 |

For each role, first run its configuration check. For example, on the Linux supervisor:

```sh
setpriv --reuid=22011 --regid=22011 --groups=22002,22999 \
  /app/.venv/bin/python -m tools.imp03_runtime check \
  --root /run/care-link-imp03-002/configuration --role identity
```

Then start it in its own supervisor process/container:

```sh
setpriv --reuid=22011 --regid=22011 --groups=22002,22999 \
  /app/.venv/bin/python -m tools.imp03_runtime serve \
  --root /run/care-link-imp03-002/configuration --role identity
```

Repeat with the corresponding UID and role from the table. The [runtime runbook](../../../../../../tools/imp03_runtime/README.md#exact-preparation-and-startup) contains all five exact commands. Run blocking service commands in separate supervisor processes, not sequentially in one shell. The journal remains a separate host authority.

**Completion condition:** all roles serve through protected listeners. Configuration checks explicitly report live trust as unchecked; step 8 supplies that evidence. Identity's restriction-only expired-credential/proof maintenance must also be running.

## 10. Create the private browser-test configuration

On the Mac workstation, copy [browser.example.json](../../../../../../tests/e2e/imp03/browser.example.json) to:

```text
/private/tmp/care-link-imp03-browser.json
```

Set mode `0600`. Replace illustrative origins, UUIDs, usernames, passwords and TOTP secrets. Verify that account UUIDs match provisioning; main, provider, help and static use separate cookie hostnames; the browser can reach the target's published origins; existing Playwright Chromium is available; and browser certificate verification works.

Keep `ignoreHTTPSErrors` false for certificate-trust qualification. Record any temporary-CA exception explicitly; it does not qualify browser CA trust. These commands acquire no browser or dependency automatically. See the [live-browser notes](../../../../../../tests/e2e/imp03/README.md).

**Completion condition:** private test inputs identify real issued actors and reachable independent origins, with certificate-trust status recorded.

## 11. Run the normal live browser demonstration

On the Mac workstation:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
umask 077
CARE_LINK_IMP03_E2E_CONFIG=/private/tmp/care-link-imp03-browser.json \
CARE_LINK_IMP03_E2E_OUTPUT=/private/tmp/care-link-imp03-live-normal-001 \
CARE_LINK_IMP03_PHASE=normal \
pnpm exec playwright test --config tests/e2e/imp03/playwright.config.ts
```

The executable test signs in through the actual provider in three separate browser contexts, verifies exact current roles/UUIDs, creates through UI, opens real SSE streams, confirms two-party connection, sends a manual message, checks disconnect truth, takes over and rejects the old owner, drops a real committed rotation response, reconciles its original key and completes fresh exact recovery. Missing prerequisites/failures fail the test; none are replaced with mock success. `observations.json` is written only after all assertions pass. Trace/screenshots/video remain off; keep result files private. This covers browser/transport behavior and selected UI actions, not full human accessibility/content acceptance.

Manual service must operate with AI unavailable. Retain `results.json` and `observations.json`.

**Completion condition:** the deployed normal scenario passes and observations are retained against the candidate.

## 12. Run reversible dependency-loss phases individually

Run these phases separately, each with a fresh output directory:

| Browser phase | Dependency role |
|---|---|
| `pdp-loss` | `pdp` |
| `identity-loss` | `identity` |
| `journal-loss` | `journal` |

Example browser command in terminal A on the Mac workstation:

```sh
CARE_LINK_IMP03_E2E_CONFIG=/private/tmp/care-link-imp03-browser.json \
CARE_LINK_IMP03_E2E_OUTPUT=/private/tmp/care-link-imp03-live-pdp-001 \
CARE_LINK_IMP03_PHASE=pdp-loss \
pnpm exec playwright test --config tests/e2e/imp03/playwright.config.ts
```

Start a fresh test run in terminal A with `CARE_LINK_IMP03_PHASE=pdp-loss` and `CARE_LINK_IMP03_E2E_OUTPUT=/private/tmp/care-link-imp03-live-pdp-001`, keeping the same executable command. Wait for that directory's `barrier-ready.json`. It is emitted only after real sign-in and successful protected session creation.

Then terminal B, on the Linux custody target:

```sh
/app/.venv/bin/python -m tools.imp03_runtime fault --root /run/care-link-imp03-002/configuration --role pdp --action pause
```

On the browser workstation, acknowledge the applied barrier:

```sh
.venv/bin/python -m tools.imp03_verification.live_barrier --output /private/tmp/care-link-imp03-live-pdp-001 --phase pdp-loss
```

The test now checks actual protected read **and** mutation denial while independent help/static surfaces remain available. After the test, resume on the Linux target, including on failure:

```sh
/app/.venv/bin/python -m tools.imp03_runtime fault --root /run/care-link-imp03-002/configuration --role pdp --action resume
```

Repeat using phase `identity-loss` / role `identity`, then phase `journal-loss` / role `journal`, always with a fresh output directory and matched acknowledgement phase. Pause commands verify exact lease/root/UID/argv/process birth and use a held Linux pidfd; there is no broad process-name signal or teardown.

The acknowledgement wait is bounded at 120 seconds; prepare the operator terminal beforehand. Readiness must precede fault application. A matching acknowledgement file alone is not a passing result; actual HTTP denials determine the test result.

**Completion condition:** every dependency barrier denies protected success, surviving surfaces behave truthfully, evidence is retained and every paused process is resumed.

## 13. Run the audit-loss phase

For `audit-loss`, start its browser phase and wait for readiness. On the independent target supervisor:

```sh
/app/.venv/bin/python -m tools.imp03_verification.audit_fault --root /run/care-link-imp03-002/configuration --admin-config /operator/imp03-admin.json --action pause
```

Acknowledge `--phase audit-loss` against that browser output directory, then run the same command with `--action resume` in cleanup. The helper verifies the exact DB/runtime login/TLS endpoint and journal lease, revokes only the narrow audit append grant, verifies the effective denial, and restores that same grant. This helper was verified with actual PostgreSQL; no live runtime audit outage is claimed in this session.

For example, use fresh browser output `/private/tmp/care-link-imp03-live-audit-001` and this Mac acknowledgement:

```sh
.venv/bin/python -m tools.imp03_verification.live_barrier \
  --output /private/tmp/care-link-imp03-live-audit-001 --phase audit-loss
```

Restore the grant on the Linux supervisor, including on test failure:

```sh
/app/.venv/bin/python -m tools.imp03_verification.audit_fault \
  --root /run/care-link-imp03-002/configuration \
  --admin-config /operator/imp03-admin.json --action resume
```

Inspect durable state as well as HTTP results.

**Completion condition:** actual audit loss releases no protected success or prohibited durable effect, and the narrow grant is restored.

## 14. Run the workload-fence phase last

For `fenced`, start that phase and wait for readiness. On the fresh target (fence generation 0), run the exact restriction command below, then acknowledge `--phase fenced`. Choose a new canonical UUID for any separately authorized later command:

```sh
setpriv --reuid=22001 --regid=22001 --groups=22999 /app/.venv/bin/python -m tools.imp03_runtime restrict --fence-socket /run/care-link-imp03-002/fence/fence.sock --fence-uid 22000 --peer core --command-id 03000000-0000-4000-8000-000000000099 --expected-generation 0
```

The fence is restriction-only; no automatic unfence or reset is provided. Preserve its evidence and use a separately reviewed fresh runtime for subsequent tests. This runbook does not authorize modifying the retained IMP-02 fence.

Use the actual observed current generation and a fresh canonical UUID if the target differs. For example, acknowledge fresh browser output `/private/tmp/care-link-imp03-live-fenced-001` on the Mac workstation:

```sh
.venv/bin/python -m tools.imp03_verification.live_barrier \
  --output /private/tmp/care-link-imp03-live-fenced-001 --phase fenced
```

**Completion condition:** the current workload fence demonstrably denies the affected protected path, with its durable restriction receipt and observations retained.

## 15. Close remaining demonstration coverage gaps

Map every G-03 requirement to current evidence. The supplied live test does not yet demonstrate every stage requirement. Demonstrate or provide sufficient current evidence for:

- Exact disclosure acknowledgement and fictional intake/attributed turns.
- Two workers competing for ownership, with one resulting owner.
- Old output paused across takeover, with no stale future delivery.
- Lost database acknowledgement producing one logical durable effect.
- Current identity/ACL revocation preventing subsequent disclosure.
- Audit integrity and absence of prohibited durable effects during failures.
- Backup/capture and restore-to-quarantine behavior, preserving the explicit limit on trusted serving recovery.

Extend live scripts where fixture evidence does not establish deployed behavior. Preserve explicit distinctions between real infrastructure and test doubles. A denial log is insufficient if prohibited bytes or effects were still delivered. Full trusted serving recovery remains IMP-09.

**Completion condition:** every declared normal/adverse G-03 obligation has current reproducible evidence, with no unresolved critical authority/control defect.

## 16. Complete human usability and operational review

Review the actual participant, worker and supervisor interfaces in English and French. Check keyboard operation, focus/error handling, screen-reader announcements, unsent-text preservation and truthful pending/disconnected/unknown states.

Measure bounded resource use and latency on this workstation. Record conditions and results; do not invent numerical acceptance thresholds after observing a run. Demonstrate scoped shutdown/rollback without rewinding rights or erasing unresolved support.

**Completion condition:** human and operational observations are recorded, defects are resolved or explicitly carried within the proposed bounded acceptance scope, and rollback is reviewable.

## 17. Assemble the final G-03 evidence packet

In the qualification session, record:

- Exact source and dirty-diff binding.
- Actual deployment artifact and configuration digests.
- Environment, contract and fixture bindings.
- Normal and adverse observations, with evidence paths/digests and actual failures/skips.
- Public SVID/renewal/fence evidence.
- Relevant database, audit and network evidence.
- Human review results, remaining limitations and rollback procedure.

Exclude credentials, private keys, cookies and continuation tokens. The session002 [DemoPacket](demo-packet.json) is a draft local-engineering record; create the qualification packet with actual target observations and bindings. Update its state only when demonstrations support it. Resolve critical control defects before presenting the candidate.

**Completion condition:** a reviewer can identify the exact candidate, reproduce its results and distinguish executed evidence from remaining obligations.

## 18. Present the human G-03 decision and record closure

Present the working demonstration, failures, residuals, exact acceptance scope and packet digest. Follow the [human-decision procedure](../../../../06-demonstrations-and-human-decisions.md).

The actual human decision can be `accept_stage`, `request_changes`, `defer` or `reject`. Record the decision, attribution, timestamp, evidence reviewed, constraints and exact candidate binding. If no decision exists, leave the candidate awaiting human review.

If accepted, update the execution ledger and qualification-session handoff/slice index with the evidence and decision reference. Preserve the canonical planning baseline. Human acceptance of this bounded manual-service stage does not establish full-demo, production or clinical readiness.

**IMP-03 is closed when the integrated demonstration, adverse evidence, current candidate binding and explicit G-03 acceptance are all recorded.** Participant admission and IMP-04 activation require their own applicable authority.
