# Immutable inputs and tag provenance are recorded in image-inputs.json.
ARG PYTHON_IMAGE=docker.io/library/python@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
ARG UV_IMAGE=ghcr.io/astral-sh/uv@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages/contracts/python packages/contracts/python
COPY services/core services/core
COPY packages/domain packages/domain
COPY packages/policy-input/pyproject.toml packages/policy-input/pyproject.toml
COPY services/data/pyproject.toml services/data/pyproject.toml
COPY host/recovery-control/pyproject.toml host/recovery-control/pyproject.toml
# Resolve the workspace from all manifests without shipping unrelated service source.
COPY services/identity/pyproject.toml services/identity/pyproject.toml
COPY host/help/pyproject.toml host/help/pyproject.toml
COPY host/static/pyproject.toml host/static/pyproject.toml
COPY packages/workload-trust/pyproject.toml packages/workload-trust/pyproject.toml
RUN uv sync --locked --no-dev --no-editable --package care-link-core
FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
EXPOSE 8011
CMD ["uvicorn", "care_link_core.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8011"]
