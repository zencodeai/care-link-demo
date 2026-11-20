# Immutable inputs inherited from the existing reviewed image-inputs.json.
ARG PYTHON_IMAGE=docker.io/library/python@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
ARG UV_IMAGE=ghcr.io/astral-sh/uv@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages/ packages/
COPY services/ services/
COPY host/ host/
RUN uv sync --locked --no-dev --all-packages
COPY tools/ tools/
COPY config/demo/imp03/ config/demo/imp03/
COPY config/demo/imp04/ config/demo/imp04/
COPY config/demo/imp05/ config/demo/imp05/
COPY apps/web/dist/ apps/web/dist/
RUN test -f apps/web/dist/index.html && chmod -R a+rX apps/web/dist
FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
# Qualification artifact, not minimal per-role production distribution.
# Runtime requires externally provisioned role-exclusive credentials and mesh.
CMD ["python", "-m", "tools.imp05_runtime", "--help"]
