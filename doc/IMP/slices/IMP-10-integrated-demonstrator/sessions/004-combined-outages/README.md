# Reproduce the combined outage test

Run this opt-in qualification from the demo repository root. Compare the application bytes against the [candidate manifest](../002-qualification/candidate-manifest.json). Use the exact [image evidence](../002-qualification/evidence/final-image-smoke.json) and the authenticated Qwen artifact recorded in the [cold-start follow-up](../003-cold-start/handoff.md). The test checks the model, tokenizer, template, catalog, and serving window through the current bridge. Use the pinned OPA executable from the earlier qualification.

Start the dedicated database using `.venv/bin/python -m tools.imp09_verification.database start`. It checks custody of the loopback fixture at port 35439. Export `CARE_LINK_OPA_BINARY`, `CARE_LINK_JOURNEY_MODEL_DIR`, `CARE_LINK_JOURNEY_MODEL_INDEX`, and `CARE_LINK_JOURNEY_TOKEN_FILE` using the admitted private paths. Use a fresh absolute receipt path for `CARE_LINK_IMP10_COMBINED_EVIDENCE`.

```bash
export CARE_LINK_JOURNEY_IMAGE_RECEIPT=doc/IMP/slices/IMP-10-integrated-demonstrator/sessions/002-qualification/evidence/final-image-smoke.json
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

from psycopg.conninfo import make_conninfo

path = Path('/private/tmp/care-link-imp09-001/database/connection.json')
settings = json.loads(path.read_text())
assert (settings['hostaddr'], settings['port'], settings['sslmode']) == (
    '127.0.0.1', '35439', 'verify-full',
)
dsn = make_conninfo(**settings)
run = subprocess.run(
    [sys.executable, '-m', 'pytest', '-q', '--tb=short',
     'services/data/tests/test_imp10_combined_outage.py'],
    env={**os.environ, 'CARE_LINK_MANUAL_TEST_DSN': dsn},
    capture_output=True,
    text=True,
)
output = (run.stdout + run.stderr).replace(dsn, '[private fixture DSN]')
print(output.replace(settings['password'], '[private fixture credential]'), end='')
sys.exit(run.returncode)
PY
```

Stop the owned database using `.venv/bin/python -m tools.imp09_verification.database stop`. The test manages its private TLS listeners, dynamic ports, and disposable app custody. The existing LM Studio process handles authenticated synthetic requests throughout the run.

The fixture checks current service applications over actual HTTPS with a private TLS 1.3 CA. It supplies synthetic internal peer credentials, actor and channel fixtures, a synthetic OIDC provider, and in-memory Identity custody. It uses real PostgreSQL over verified TLS, signed OPA, and a separate SQLite Help spool. The simultaneous service fault pauses owned listeners and disables the canonical audit relation inside the disposable database. The loopback service apps share the test Python process. The Kubernetes, workload policy, and host process layout still require deployment-level evidence.
