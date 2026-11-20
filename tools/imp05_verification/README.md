# IMP-05 isolated source qualification

Run the existing local source lane with an explicit disposable PostgreSQL TLS configuration and pinned OPA executable:

```
.venv/bin/python -m tools.imp05_verification.run_checks --database-config /private/tmp/care-link-imp05-001/database/connection.json --opa /private/tmp/care-link-imp03-tools/opa --attempt attempt001
```

The runner refuses any database endpoint except the session's dedicated localhost/127.0.0.1 port35435 verified-TLS postgres fixture. It preserves each attempt under the current session and stops on a failing check. It does not create a database server, install tools, deploy, load a model, change host trust or publish anything. Pytest owns only the specifically named disposable sender/receiver databases it creates and removes. Treat the configuration file as secret; never copy it into evidence.

`tests/e2e/referral` separately drives an isolated existing browser server against the local Vite app and route-mocked synthetic API/provider responses. Its evidence distinguishes real Chromium/axe/keyboard/layout checks from backend authority qualification.

Create the dedicated fixture with `python -m tools.imp05_verification.database start` only when isolated local test execution is authorized; remove it with the same module's `stop` action. The module refuses existing resources and labels the container for owned cleanup. It reuses the established certificate generator with independent temporary custody and the pinned PostgreSQL image.

The final planning check runs the frozen canonical validator through `tools.imp05_verification.validate_plan`. The original validator, archive bytes and frozen inventory remain unchanged. Only Markdown historical-reference resolution uses the existing SHA256-bound relocation manifests; active broken links and altered retained bytes still fail. The earlier raw-validator failure is preserved in attempt003.
