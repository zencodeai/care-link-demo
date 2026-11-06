# Technology-specific tooling and quality baseline

These are recommendations for this repository, not claims that a tool is universally best or installed. Choose the smallest compatible tool set that enforces the accepted design. IMP-00 pins supported versions/platforms and acquisition provenance; IMP-01 establishes locks/scripts. Tool recommendations do not replace actual workstation/container/model checks.

| Area | Recommended baseline | Purpose / trade-off |
|---|---|---|
| Python environment/build | uv, root pyproject.toml workspace, uv.lock, pinned interpreter and package src layout | One reproducible resolution across compatible Python packages; split only if concrete incompatible requirements justify it |
| Python lint/format | Ruff check + Ruff format | One linter/formatter; no parallel Black/isort/Flake8 configuration duplicating the same rules |
| Python types | Pyright strict, pinned official Node CLI through pnpm | Reuse Node tooling already required for web; point to uv .venv; do not add a second competing checker initially |
| Python behavior | pytest, pytest-asyncio where used, Hypothesis, HTTP client fixtures | Deterministic unit/contract/race properties; explicit async fixture lifetime and real DB integration |
| Python persistence | SQLAlchemy 2.x API, Psycopg, Alembic | Typed data adapter and reviewed migrations; exact compatible versions remain pins to verify |
| Web environment/build | Supported Node LTS pinned after compatibility check; pnpm workspace/lock; React/TypeScript and Vite | Private app build without introducing an unneeded SSR/full-stack framework |
| Web lint/format/types | tsc strict, ESLint flat config + typescript-eslint typed rules, Prettier | Separate type correctness, behavioral lint and formatting; disable overlapping stylistic lint |
| Web tests | Vitest + React Testing Library; Playwright + axe integration | Fast component tests and separate-account browser journeys; manual accessibility/language review still required |
| Contracts | Existing JSON Schema/OpenAPI validator; [AJV 2020-12](https://ajv.js.org/json-schema.html) + formats and explicit local semantic adapters for TS; pinned DTO generator if it proves parity | Schema/adapter differential fixtures, closed shapes and custom decimal semantics; generated types alone validate no runtime input |
| DB tests | Disposable real PostgreSQL via declared Docker fixture/Testcontainers candidate | Native lock/RLS/transaction behavior, independent DB/schema names and clean teardown; no SQLite substitution |
| Policy | OPA test/fmt/check with pinned Rego version and reviewed policy fixtures | Current decision/obligation/race semantics plus live enforcement tests; unit policy pass is not a deployed PEP |
| Containers/Kubernetes | Docker/BuildKit, kubectl + Kustomize; manifest/schema lint selected after host binding | Reproducible nonroot service images and small reviewed overlays; actual CNI/host denial probes still mandatory |
| Security/release | Gitleaks, pip-audit, pnpm audit, Trivy for relevant image/IaC/SBOM checks | Focused secret/dependency/artifact findings; no scanner is proof of runtime containment |
| CI/evidence | GitHub Actions, JUnit/test reports, browser traces, versioned evidence manifests | Read-only default tokens, actions pinned by commit, no secrets to untrusted PR code; local sensitive drills remain isolated |

The [tool catalog](tooling.json) records source URLs, scope, first stage and unresolved pins. Version fields remain null until observed/selected; no moving latest tags in accepted runtime builds. Existing project stack/workstation/model choices are not reconsidered just to adopt tooling.

## Command surface to implement in IMP-01

These are future native commands, not commands run or guaranteed available by this planning task:

```text
uv sync --locked --all-packages --all-groups
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -m "unit or contract"
pnpm install --frozen-lockfile
pnpm exec pyright --project pyrightconfig.json
pnpm exec tsc --build --pretty false
pnpm exec eslint . --max-warnings 0
pnpm exec prettier --check <owned frontend/config paths>
pnpm exec vitest run
pnpm exec playwright test
```

Pin Ruff in the uv development group and Pyright in root pnpm development dependencies. Workspace member/package names, test paths/markers and frontend project references are established before treating these recipes as runnable. CI asserts lockfiles exist and match manifests; `--frozen` options must not conceal stale resolution. Use an explicit controlled lock update for reviewed dependency changes. Do not run install scripts/acquisition from an arbitrary model/user-provided URL. [uv locking/sync](https://docs.astral.sh/uv/concepts/projects/sync/), [pnpm installs](https://pnpm.io/cli/install).

Initial Ruff rules cover errors, imports, modernization, bug-prone constructs, async misuse and relevant security rules. Test-only assertion exemptions are narrow; unsafe automated fixes and blanket suppressions require review. Pyright strict has no unexplained Any/type-ignore escape hatch at authority boundaries. Tests are behavioral and risk-based: no blanket coverage target or tests that merely repeat implementation/formatting. [Ruff linter](https://docs.astral.sh/ruff/linter/), [Ruff formatter](https://docs.astral.sh/ruff/formatter/), [Pyright config](https://github.com/microsoft/pyright/blob/main/docs/configuration.md).

## Container and operations practices

Use multi-stage builds, pinned image digests, nonroot/read-only runtime, minimal selected-package dependencies and secrets mounted outside images. A single developer uv/pnpm workspace does not mean ship all development packages in each image. Build-time dependency acquisition is a separate maintenance plane from restricted runtime egress. Host-only help/static/journal survive application-cluster loss under the LLD's documented dependencies. [uv container guidance](https://docs.astral.sh/uv/guides/integration/docker/), [Docker build practices](https://docs.docker.com/build/building/best-practices/), [Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/).

Do not add Kafka/Celery, LangChain/autonomous multi-agent runtime, service-per-class decomposition, Terraform/cloud hosting, Nx/Turborepo or a second formatter/type checker without a demonstrated need and architecture review. Simple DB work tables, explicit bounded coordinator, small packages and native commands are the initial baseline. An optional thin task runner may wrap stable commands later; it must not hide side effects or become another source of quality rules.
