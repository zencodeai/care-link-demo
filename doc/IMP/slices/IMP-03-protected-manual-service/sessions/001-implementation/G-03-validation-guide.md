# G-03 validation — executable commands

This guide targets the accepted development workstation: macOS ARM64, Python3.14.7, Node22.14.0, uv0.12.17 and pnpm10.20.0. Commands run from `care-link-demo`.

**The commands below reproduce source and local mechanism verification. Full live G-03 acceptance is not runnable yet.** There is no G-03 service launcher/browser URL in this candidate. `HttpManualGateway` still requires an injected `EnvelopeFactory`; the repository provides its protocol, not a complete remote composition. The default `care-link-core` command starts the developer API and deliberately denies `/v1` business routes. Do not interpret successful tests or the developer page as a live G-03 demonstration.

This document adds a command reference only. It does not change the frozen candidate, claim a new test run, deploy anything or record a human decision.

## 1. Prepare dependencies and verify the current source

Start Docker Desktop, then run:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo

uv --version
node --version
pnpm --version
docker info >/dev/null

uv sync --locked --all-packages --all-groups
pnpm install --frozen-lockfile --ignore-scripts
```

The expected pins are listed above. If a command fails, resolve that failure before continuing. If pnpm is missing, use the pinned npm package to install workspace dependencies:

```sh
npm exec --yes --package=pnpm@10.20.0 -- pnpm install --frozen-lockfile --ignore-scripts
```

Later commands invoke `pnpm` through the normal check runner. If it is not on PATH, open a shell with the pinned executable available, then run steps2–5 inside that shell:

```sh
npm exec --yes --package=pnpm@10.20.0 -- pnpm exec bash
```

Run `exit` when finished to leave that shell. This does not install pnpm globally.

Check that the current runtime source still matches the recorded candidate:

```sh
.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path

path = Path('doc/IMP/slices/IMP-03-protected-manual-service/sessions/001-implementation/candidate-manifest.json')
manifest = json.loads(path.read_text())
changed = [item['path'] for item in manifest['source_files'] + manifest['source_inputs']
           if not Path(item['path']).is_file()
           or hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']]
if changed:
    print('Recorded candidate differs at:')
    print('\n'.join(changed))
    raise SystemExit('Prepare an updated candidate binding before requesting G-03 acceptance.')
print('Recorded candidate source/input hashes match.')
PY
```

This verifies the recorded files. Any additional implementation files or configuration also need inclusion in a new candidate binding before acceptance.

## 2. Run source checks without live fixtures

```sh
.venv/bin/python tools/check.py
```

Without explicit PostgreSQL and OPA fixture variables this run skips those opt-in tests. The recorded source-only baseline is **410 Python passed,54 skipped;56 TS/UI/parity passed**. It does not prove live identity, workload attestation or a browser handoff.

For pnpm supplied through npm:

```sh
npm exec --yes --package=pnpm@10.20.0 -- pnpm exec .venv/bin/python tools/check.py
```

## 3. Run the full PostgreSQL / OPA / journal / capture verification

This block creates only `care-link-imp03-001-postgres`, publishes loopback25433, uses tmpfs database storage and owner-only temporary secrets, and removes that container on exit. Tests create/drop `imp03_manual`, test roles and `imp03_quarantine_*` targets inside that container. It does not touch the IMP-02 cluster or start the manual browser service.

The block refuses an existing container with the same name. If a previous owned fixture remains, first inspect it and use the label-checking cleanup command in step5. Old private fixture files are archived into a new owner-only temporary directory so each run generates fresh TLS certificates.

Run the entire block, including both `G03RUN` lines:

```sh
bash <<'G03RUN'
set -euo pipefail
umask 077
cd /Users/main/Workspace/projects/care-link/care-link-demo

for executable in docker uv pnpm node curl; do
  command -v "$executable" >/dev/null
done
docker info >/dev/null
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo 'This runbook is pinned for the accepted macOS ARM64 workstation.' >&2
  exit 1
fi

fixture_name=care-link-imp03-001-postgres
if docker container inspect "$fixture_name" >/dev/null 2>&1; then
  echo 'Named fixture already exists. Use step5 to inspect/clean the owned fixture, then retry.' >&2
  exit 1
fi

# Download a fixed OPA binary; verify its repository-pinned SHA before execution.
mkdir -p /private/tmp/care-link-imp03-tools
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/open-policy-agent/opa/releases/download/v1.22.2/opa_darwin_arm64 \
  --output /private/tmp/care-link-imp03-tools/opa
.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path
path = Path('/private/tmp/care-link-imp03-tools/opa')
pins = json.loads(Path('config/demo/imp03/products.json').read_text())
if hashlib.sha256(path.read_bytes()).hexdigest() != pins['opa']['darwin_arm64_sha256']:
    raise SystemExit('OPA checksum mismatch; binary was not executed.')
path.chmod(0o700)
PY
/private/tmp/care-link-imp03-tools/opa version

docker pull postgres@sha256:80630f83606d8db77d30b3851b16a9f78be2d0d4dda6f7b82a1fdca5ebe3acba
if [ -d /private/tmp/care-link-imp03-001/database ]; then
  g03_archive=$(mktemp -d /private/tmp/care-link-imp03-previous-db.XXXXXX)
  mv /private/tmp/care-link-imp03-001/database "$g03_archive/database"
  printf 'Archived prior private fixture files under %s\n' "$g03_archive"
fi

g03_started=0
g03_cleanup() {
  g03_status=$?
  trap - EXIT
  if [ "$g03_started" = 1 ]; then
    if ! .venv/bin/python -m tools.imp03_verification.database stop; then
      echo 'Owned fixture cleanup failed; use step5. No other resource was removed.' >&2
      if [ "$g03_status" = 0 ]; then g03_status=1; fi
    fi
  fi
  exit "$g03_status"
}
trap g03_cleanup EXIT
.venv/bin/python -m tools.imp03_verification.database start
g03_started=1

# Read the secret connection settings only in Python. Never print/export the DSN.
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import psycopg
from psycopg.conninfo import make_conninfo

settings = json.loads(Path('/private/tmp/care-link-imp03-001/database/connection.json').read_text())
deadline = time.monotonic() + 60
while True:
    try:
        with psycopg.connect(**settings, connect_timeout=1) as connection:
            tls = connection.execute('SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()
            if tls != (True, 'TLSv1.3'):
                raise SystemExit('Fixture TLS qualification failed.')
            print('PostgreSQL ready with verified TLSv1.3.', flush=True)
        break
    except psycopg.Error:
        if time.monotonic() >= deadline:
            raise SystemExit('PostgreSQL fixture did not become ready within60seconds.') from None
        time.sleep(0.5)

environment = {
    **os.environ,
    'CARE_LINK_MANUAL_TEST_DSN': make_conninfo(**settings),
    'CARE_LINK_OPA_BINARY': '/private/tmp/care-link-imp03-tools/opa',
    'CARE_LINK_IMP03_CAPTURE': '1',
}
evidence = Path(tempfile.mkdtemp(prefix='care-link-g03-validation-', dir='/private/tmp'))
print('Running complete checks; sanitized output will be retained in:', evidence, flush=True)
result = subprocess.run([sys.executable, 'tools/check.py'], env=environment,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
output = result.stdout.replace(settings['password'], '[REDACTED]')
output = re.sub(r"password=[^\s'\"]+", 'password=[REDACTED]', output)
log = evidence / 'full-check.log'
log.write_text(output)
log.chmod(0o600)
print('\n'.join(output.splitlines()[-90:]))
print('Complete sanitized evidence:', log)
raise SystemExit(result.returncode)
PY
G03RUN
```

Expected unchanged-candidate baseline: **463 Python passed,1 Linux-only skip;56 TS/UI/parity passed**, with no opt-in PostgreSQL/OPA tests skipped. The Linux UID harness skip is explicitly declared. The browser bundle warning and existing TestClient deprecation warning were present in the recorded run.

The existing tests exercise these observations:

| Behavior | Tests |
|---|---|
| Manual session, two-party connection, message, canonical audit | `test_real_policy_journal_database_and_bff_manual_journey` |
| Two-worker race, takeover fencing, one-party/dead-channel denial | `test_racing_reservations_leave_exactly_one_owner_candidate`, `test_takeover_fences_old_owner_and_requires_new_handshake`, `test_one_party_and_dead_channel_never_connect` |
| Lost committed DB acknowledgement, one logical effect | `test_real_database_commit_then_lost_ack_reconciles_one_operation` |
| Continuation initial issue, lost reply and fresh recovery | `test_additive_public_continuation_issuance_is_once_only_and_own_session`, `test_lost_recovery_response_allows_new_fresh_ancestor_bound_recovery` |
| ACL/principal revocation after ACK, current disconnect state | `test_participant_revoked_after_both_acks_cannot_be_connected`, `test_disconnected_endpoint_is_not_reported_as_current_connection` |
| Missing audit/PDP/journal prevents protected success | `test_audit_failure_rolls_back_private_state_and_result`, `test_pdp_and_journal_failures_release_no_private_success`, `test_journal_success_db_failure_fences_every_subsequent_read` |
| Machine duties, rejected keys and canonical DENY | `services/data/tests/test_duties.py` |
| Consistent encrypted capture and actual quarantine import | `test_actual_consistent_capture_and_role_quarantined_database_import` |

Real PostgreSQL, OPA, cryptography and journal/capture mechanisms are exercised. Current identity/provider/workload callbacks in the composition tests remain explicitly labelled fixtures. These commands do not replace live trust/browser qualification.

## 4. Check the isolated core image, if needed

This verifies the developer-only artifact and package isolation; it does not launch G-03.

```sh
.venv/bin/python tools/build_core_image.py --tag care-link-core:g03-verification
.venv/bin/python tools/smoke_core_image.py --image care-link-core:g03-verification
```

Expected: restricted-container smoke succeeds and `/v1/sessions` still returns503 in this default developer image. The helper removes its own test container. The local image/build cache remain.

## 5. Inspect or clean a leftover owned fixture

```sh
docker ps -a --filter 'name=^/care-link-imp03-001-postgres$' \
  --format '{{.Names}} {{.Status}}'
.venv/bin/python -m tools.imp03_verification.database stop
```

The stop helper verifies the exact ownership label before removing the named container. If no container exists, there is nothing to clean; do not run broad Docker prune or remove the IMP-02 lab.

## 6. Full live G-03 validation — implementation work still required

There is currently no honest copy/paste server-start or browser-validation command for this step. Required work is concrete:

1. Implement/configure the remote BFF→core/data request envelope factory and fresh identity evidence resolution. The existing in-process identity adapter is a verification bridge.
2. Supply independently credentialled identity/data/PDP/host-journal composition, admitted policy/duty artifacts and current TLS/SVID/certificate/fence verification.
3. Add a reproducible named deployment/launcher, private origins, separately issued actor accounts and real browser fault-barrier scripts.
4. Run normal participant→worker→supervisor journeys and real continuation-recovery/dependency-loss cases; capture actual observations and candidate/config/environment bindings.
5. Present the completed DemoPacket for the actual human G-03 decision. Keep it draft until those observations exist.

A separate IMP-03 completion chat is the project workflow for that implementation/qualification. No deployment, G-03 approval, participant admission or next-slice activation follows from running steps1–5 above.
