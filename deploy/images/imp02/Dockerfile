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
COPY services/identity services/identity
COPY host/help host/help
COPY host/static host/static
COPY packages/workload-trust packages/workload-trust
RUN uv sync --locked --no-dev --no-editable --package care-link-core --package care-link-identity --package care-link-help --package care-link-static --package care-link-workload-trust
FROM build AS verification
RUN uv sync --locked --all-packages --all-groups
COPY packages/workload-trust/tests /tests/workload
COPY tests/integration/imp02_lab/test_fence_users.py /tests/test_fence_users.py
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "pytest", "-q", "/tests", "--rootdir", "/tests"]
FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY tools/imp02_application tools/imp02_application
COPY tools/imp02_lab/__init__.py tools/imp02_lab/trust_process.py tools/imp02_lab/
COPY apps/web/dist /app/web/main
COPY apps/web/dist-help /app/web/help
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
USER 21011:21011
ENTRYPOINT ["python", "-m", "tools.imp02_application"]
