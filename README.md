# CARE-Link Demo

CARE-Link Demo is an independent, Ottawa-based project for demonstrating mental-health crisis-support workflows with synthetic data, simulated services, human oversight and deterministic controls around an LLM.

The repository contains technical requirements, HLD and LLD, with accepted local design choices and unmeasured engineering parameters. The IMP-01 developer foundation is implemented; deployment and operational validation remain pending. It is not approved for real crisis use or production deployment.

## Project scope

- Closed access for authorized project participants, using fictional scenarios and non-clinical stub content.
- Separate credentials, sessions, interfaces and workflows for participants, crisis-worker role-players, supervisors and other authorized roles.
- Demonstrations of intake, service discovery, consent, referrals, human handoff, crisis planning, follow-up and audit.
- No police affiliation, partnership, police-facing role, connector, brief workflow or data-sharing arrangement. No autonomous emergency contact capability.
- Ottawa, Ontario context, `America/Toronto` time and English/French interfaces; fictional service jurisdictions remain separate from the implementor’s location.
- An independent static crisis-information path using verified real contact content, with content review required before participant use.

## Agentic AI supports the actors

Role-scoped assistants help participants express needs and help workers retrieve context, compare verified service options, prepare editable summaries/referrals and track authorized handoffs. A bounded agent workflow can plan, request permitted tools, observe results and propose recovery steps. Humans retain clinical and consequential service decisions; deterministic controls enforce security, consent and governance at each step. Authorized manual service workflows remain usable when AI is unavailable.

See the [agentic service model and comparable-system research](doc/REQ/10-agentic-ai-and-service-model.md) for actor responsibilities, evidence limits and acceptance requirements. Mission-critical service quality is the objective; the current synthetic demo does not establish clinical readiness.

## Planned technical direction

The selected deployment target is this workstation, using Docker images and Kubernetes with local LM Studio and `google/gemma-4-12b-qat`. The user reports that the model is already downloaded; artifact metadata, loaded identity and task capability remain to be verified. The model proposes content and actions; deterministic services control authorization, consent, committed state and execution. Human help must remain accessible when inference is unavailable.

The accepted local stack direction includes React/TypeScript, Python/FastAPI, PostgreSQL, Keycloak/OIDC and OPA/Rego. These are design selections awaiting implementation checks. Exact versions, model artifacts, host capacity and network enforcement must be verified. Changes follow human-reviewed GitHub PRs, with independent approval for the accepted baseline.

## Requirements and decisions

Start with the [technical requirements index](doc/REQ/README.md).

| Document | Contents |
|---|---|
| [Scope and sources](doc/REQ/01-scope-and-sources.md) | Source authority, demo boundaries and scope divergences |
| [Actors and workflows](doc/REQ/02-actors-and-workflows.md) | Role permissions, credentials and user journeys |
| [Architecture and interfaces](doc/REQ/03-architecture-and-interfaces.md) | Components, LLM boundaries and contracts |
| [Data, security and governance](doc/REQ/04-data-security-governance.md) | Persistence, consent, audit and review controls |
| [Deployment and operations](doc/REQ/05-deployment-and-operations.md) | Local hosting, recovery and observability requirements |
| [Acceptance and delivery](doc/REQ/06-acceptance-and-delivery.md) | Verification obligations and incremental milestones |
| [Source requirement trace](doc/REQ/07-source-requirements.md) | 114 inherited requirements and 16 invariants |
| [Decision answers](doc/REQ/08-open-decisions.md) | Answers to 53 inherited questions and local design decisions |
| [Demo parameters](doc/REQ/demo-parameters.json) | Proposed engineering defaults; not automatically loaded runtime configuration |

The decision answers record the current Ottawa context and police exclusions. Historical police-specific source requirements remain traceable as excluded scope; they are not implemented or claimed as satisfied. Clinical, legal, regulatory and community approvals remain distinct from engineering defaults.

## Implementation status

IMP-01 provides an isolated developer API, EN/FR role preview shell, closed contract adapters and a locked local check loop. Business operations remain unavailable and participant admission is disabled. The user validated G-00 and G-01 on 2026-11-07 for the current developer foundation. See the [slice handoff](doc/IMP/slices/IMP-01-repository-foundation/README.md) for acceptance records, evidence and remaining verification work.

### Prepare the local tools

Use Python `3.14.7`, Node `22.14.0`, uv `0.12.17` and pnpm `10.20.0`. These tested local developer pins are covered by the recorded G-00 validation. Further host/lab setup actions retain their own scope and authorization.

Run commands from **`care-link-demo`**, which contains `package.json` and `pyproject.toml`. On this workstation:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
uv sync --locked --all-packages --all-groups
pnpm install --frozen-lockfile
```

If `pnpm` is not found, use the pinned CLI through npm instead of the last command:

```sh
npm exec --yes --package=pnpm@10.20.0 -- pnpm install --frozen-lockfile
```

This may download pnpm into npm's cache; it does not install pnpm globally. If you see `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` mentioning `/Users/main/Workspace`, run the `cd` command above first. Dependency install scripts are disabled; reviewed dependency updates change the manifest and lock together.

### Start the developer demonstration

Open **two separate terminals**. Run the `cd` command in each terminal, and leave both commands running.

**Terminal 1 — API:**

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
uv run --locked care-link-core
```

The API listens at `http://127.0.0.1:8011`.

**Terminal 2 — web interface:**

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
npm exec --yes --package=pnpm@10.20.0 -- pnpm dev:web
```

If pnpm is already on your PATH, `pnpm dev:web` is equivalent to the last command.

Open **http://127.0.0.1:5173** in your browser. Under **API capabilities**, expect **Development API connected**. If it shows **API unconnected**, check that Terminal 1 is still running, then click **Check API again**. The web server proxies capability requests to the API. Change the language to check the EN/FR display and select a role preview to see its unavailable capabilities. Role preview changes display only.

Stop the demonstration with **Ctrl+C in each terminal** when finished.

### Validate the sample contracts

In **Contract demonstration**, choose the contract, replace the **JSON input**, and click **Validate locally**. This button runs the TypeScript adapter in the browser; it does not submit the input to the API or create a record. The API connection indicator is a separate check.

Copy only the JSON inside each code block. Do not include Markdown fences, backslashes after lines, or literal `&#x20;` text. The revision help text describes the rule; the result appears after clicking the button.

**RevisionCommand — accepted example:**

```json
{"expected_revision": "1"}
```

Expected: **Valid contract input. No operation was performed.** Revisions must be quoted decimal strings from `"0"` through `"9223372036854775807"`, with no leading zeros except `"0"` itself.

With **RevisionCommand** still selected, validate each of these separately:

| JSON input | Expected result | Reason |
|---|---|---|
| `{"expected_revision": "9223372036854775807"}` | Accepted | Maximum allowed revision |
| `{"expected_revision": "9223372036854775808"}` | Rejected | Above the maximum |
| `{"expected_revision": 1}` | Rejected | Number instead of a quoted string |
| `{"expected_revision": "01"}` | Rejected | Noncanonical leading zero |

For rejected input, expect **Input rejected. Check required fields, unknown keys, JSON syntax, and revision limits.** This is the expected result for each negative example.

**SessionCreate — accepted example:** select **SessionCreate** and validate:

```json
{
  "tags": {
    "environment": "demo",
    "population": "synthetic"
  },
  "participant_kind": "pid",
  "jurisdiction": null,
  "locale": "en-CA",
  "channel": "web",
  "persona_id": null,
  "fixture_id": null
}
```

Expected: **Valid contract input. No operation was performed.** No session is created.

To check nested unknown-key rejection, replace the input with this valid JSON containing an unsupported `extra` field:

```json
{
  "tags": {
    "environment": "demo",
    "population": "synthetic",
    "extra": true
  },
  "participant_kind": "pid",
  "jurisdiction": null,
  "locale": "en-CA",
  "channel": "web",
  "persona_id": null,
  "fixture_id": null
}
```

Expected: **Input rejected…** because `tags.extra` is unknown. Remove the `extra` line **and the comma after `"synthetic"`**; the corrected example should pass again. That accepted → rejected → accepted sequence checks the nested-key rule without introducing a JSON syntax error.

### Check the API and automated evidence

To exercise Python API validation separately, keep Terminal 1 running and use another terminal:

```sh
# Valid revision: expect HTTP 204 with no response body.
curl -i http://127.0.0.1:8011/dev/contracts/RevisionCommand \
  -H 'Content-Type: application/json' \
  --data '{"expected_revision":"1"}'

# Overflow: expect HTTP 422 with code INVALID_REQUEST.
curl -i http://127.0.0.1:8011/dev/contracts/RevisionCommand \
  -H 'Content-Type: application/json' \
  --data '{"expected_revision":"9223372036854775808"}'

# Unimplemented business route: expect HTTP 503 with code CAPABILITY_DISABLED.
curl -i http://127.0.0.1:8011/v1/sessions
```

`GET /dev/health` reports the developer capability, including `participant_admission: false`. Both API contract validation and the browser demonstration validate inputs without performing business operations.

For the automated checks, run from `care-link-demo`; the developer servers can be stopped:

```sh
python3 tools/check.py
```

If pnpm is not on your PATH, run the same check with the pinned CLI available to its child commands:

```sh
npm exec --yes --package=pnpm@10.20.0 -- pnpm exec python3 tools/check.py
```

The command checks locks, schema provenance, import boundaries, Ruff, strict Pyright/TypeScript, ESLint, Prettier, behavior/parity tests and the web build. It stops on the first failure and exits zero only when every check passes. Cross-language parity tests exercise Python and TypeScript against the same valid and invalid inputs. The recorded implementation run passed 52 Python tests and 32 TypeScript/UI/parity tests; see [checks.json](doc/IMP/slices/IMP-01-repository-foundation/sessions/001-implementation/checks.json) for evidence and unperformed checks.

`python3 tools/verify_clean.py` additionally repeats locked setup/checks offline in a temporary source copy using populated caches, then proves stale manifests and schema loosening fail. It requires git, uv and pnpm on PATH. If needed, use `npm exec --yes --package=pnpm@10.20.0 -- pnpm exec python3 tools/verify_clean.py`. Set `CARE_LINK_PNPM_STORE` only if your populated pnpm store is in a nondefault location.

Passing the examples or automated checks supplies engineering evidence. **G-00** records human acceptance of the concrete environment/tool/setup proposal; **G-01** records human acceptance of the exact foundation demonstration candidate. The user explicitly stated **“G-00 and G-01 validated”** on 2026-11-07. That decision is recorded for the current local developer scope in the [G-00 receipt](doc/IMP/executions/2026-11-07-IMP-01/decisions/G-00.json) and [G-01 receipt](doc/IMP/executions/2026-11-07-IMP-01/decisions/G-01.json), bound to the current candidate including these README clarifications.

The original implementation-run evidence remains historical. The user subsequently reported the browser/keyboard and independent EN/FR review complete and authorized finishing image verification and remote CI, naming this development workstation as the lab. [Session 002](doc/IMP/slices/IMP-01-repository-foundation/sessions/002-image-and-ci/handoff.md) records those follow-ups and their current results. The user-reported review is attributed to the user; it is not recorded as an agent browser execution. Participant admission, deployment and later-slice implementation retain their own authorization.

### Container verification on the workstation lab

The [core Dockerfile](services/core/Dockerfile) uses immutable official Python `3.14.7-slim-bookworm` and Astral uv `0.12.17` image inputs, with source tags and architecture manifests recorded in [image-inputs.json](services/core/image-inputs.json). With Docker Desktop running on the authorized development workstation, build and verify the image:

```sh
cd /Users/main/Workspace/projects/care-link/care-link-demo
python3 tools/build_core_image.py
python3 tools/smoke_core_image.py
```

The helper defaults to `care-link-core:imp-01`; use matching `--tag` and `--image` arguments to name a separate local candidate. Explicit `--python-image` and `--uv-image` overrides must contain immutable SHA-256 digests. The smoke helper tests the already-built local image with user `65532`, a read-only filesystem, all Linux capabilities dropped, no new privileges, no network attachment, no published ports and no host mounts. It checks contract behavior, disabled business routes and absence of development dependencies, then removes only the uniquely named container it created. The image and Docker build cache remain available.

The workstation Linux/ARM64 build and smoke passed, including a deliberately failed-startup cleanup check. [Foundation CI](.github/workflows/foundation.yml) also runs a Linux/AMD64 image build/smoke alongside the fast lane. [Remote run 42403688794](https://github.com/zencodeai/care-link-demo/actions/runs/42403688794) passed both jobs for source commit `69a387302335a8bf800325bb0ccfb1e66f97fee7` on `feat/imp-01-foundation`; logs and commit bindings are retained in session002. Image verification, remote CI and user-reported UI review are complete for this developer slice. No merge or production deployment was performed.

The sibling `care-link` repository supplies the source system model. The abandoned `care-link-prod` implementation is historical reference only; its credentials, deployment approvals and readiness claims are not inherited here.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.

See the [LLD](doc/LLD/README.md) and [choice/workstation/model acceptance](doc/LLD/decisions/2026-11-06-implementation-choices-and-model.md) for implementation detail and the scope of local approval.
