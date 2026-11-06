# Sources, provenance and planning validation

Sources reviewed on 2026-11-06. Local accepted requirements/HLD/LLD take precedence over generic tool suggestions; official references establish tool capabilities, not CARE-Link safety or suitability. No latest-version number or installation is inferred from a website. Exact compatible pins are IMP-00/01 work.

## Official references used

| Topic | Source |
|---|---|
| Codex custom agents / inherited settings | [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) |
| Codex repo instructions | [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) |
| uv workspace / locked environment | [Workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/), [sync](https://docs.astral.sh/uv/concepts/projects/sync/), [Docker](https://docs.astral.sh/uv/guides/integration/docker/) |
| Ruff lint and formatting | [Linter](https://docs.astral.sh/ruff/linter/), [formatter](https://docs.astral.sh/ruff/formatter/) |
| Python typing/API/DB | [Pyright](https://github.com/microsoft/pyright/blob/main/docs/configuration.md), [FastAPI](https://fastapi.tiangolo.com/tutorial/bigger-applications/), [Pydantic](https://docs.pydantic.dev/latest/concepts/models/), [SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) |
| JS workspace/build/quality | [AJV schema](https://ajv.js.org/json-schema.html), [pnpm workspace](https://pnpm.io/workspaces), [install](https://pnpm.io/cli/install), [Vite](https://vite.dev/guide/), [TS strict](https://www.typescriptlang.org/tsconfig/strict.html), [typed lint](https://typescript-eslint.io/getting-started/typed-linting/), [Prettier](https://prettier.io/docs/) |
| Behavioral/browser testing | [pytest fixtures](https://www.pytest.org/en/latest/how-to/fixtures.html), [Hypothesis](https://hypothesis.readthedocs.io/en/latest/), [Vitest](https://vitest.dev/guide/), [Testing Library](https://testing-library.com/docs/react-testing-library/intro/), [Playwright/axe](https://playwright.dev/docs/accessibility-testing) |
| Deployment/policy/CI | [Docker](https://docs.docker.com/build/building/best-practices/), [Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/), [OPA tests](https://www.openpolicyagent.org/docs/policy-testing), [Actions security](https://docs.github.com/en/actions/reference/security/secure-use) |
| Security tools | [pip-audit](https://github.com/pypa/pip-audit), [Gitleaks](https://github.com/gitleaks/gitleaks), [Trivy](https://trivy.dev/docs/latest/guide/) |

The source inventory hashes current local input files; it is not refreshed silently when inputs drift. New findings that change architecture or authority require a scoped design amendment before dependent implementation. The plan remains separate from the LLD so planning metadata does not rewrite accepted technical semantics.

## Checks on this planning package

The planning validator checks JSON Schema/fixtures, native TOML syntax/required fields, unique role/task/stage/gate identities, acyclic dependencies, complete operation and local-requirement allocation, allowed evidence/decision semantics, documented review gates, local links and frozen source hashes. It rejects placeholder/example human acceptance as an actual accepted stage. These checks do not discover Codex roles, enforce a sandbox, install tools, run app code or establish implementation correctness.

Current review method: coordinator performed sequential baseline/tooling/modularity, ordering/human-gate and contract/evidence consistency passes. No IMP subagents or human approval were claimed. Templates are dormant. Machine status and the exact checks run are recorded in [planning inventory](planning-inventory.json).

[TypeScript indexed access](https://www.typescriptlang.org/tsconfig/noUncheckedIndexedAccess.html) and [optional property semantics](https://www.typescriptlang.org/tsconfig/exactOptionalPropertyTypes.html) support the selected strict options. [Testcontainers Python](https://github.com/testcontainers/testcontainers-python) is a candidate integration fixture, not an installed requirement; choose it only if it simplifies the declared Docker-based PostgreSQL harness.
