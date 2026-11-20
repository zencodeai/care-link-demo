# IMP-04 qualification workspace; independent runtime credentials enforce roles.
# Immutable upstream inputs match services/core/image-inputs.json.
ARG PYTHON_IMAGE=docker.io/library/python@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
ARG UV_IMAGE=ghcr.io/astral-sh/uv@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# Qualification workspace and migrations; inspect the artifact inventory for
# the actual admitted files. This is not a minimal per-role distribution.
COPY packages/ packages/
COPY services/ services/
COPY host/ host/
RUN uv sync --locked --no-dev --all-packages
COPY tools/ tools/
COPY config/demo/imp03/ config/demo/imp03/
COPY config/demo/imp04/ config/demo/imp04/
COPY deploy/k8s/imp-02/products.json deploy/k8s/imp-02/products.json
COPY doc/IMP/slices/IMP-04-plans-consent-directory/sessions/002-deployment-qualification-preparation/target-proposal.json doc/IMP/slices/IMP-04-plans-consent-directory/sessions/002-deployment-qualification-preparation/target-proposal.json
COPY apps/web/dist/ apps/web/dist/
# The verification runner intentionally uses umask077. These selected assets
# are public; normalize their image permissions for every assigned role UID.
RUN test -f /app/apps/web/dist/index.html \
    && test -f /app/apps/web/dist/qualification-origins.json \
    && chmod -R a+rX /app/apps/web/dist

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
# The editable workspace needs its source alongside .venv at the same paths.
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
# Serving requires an explicit role, private configuration and external custody.
# Linux OPA is separately digest-verified and mounted; it is not downloaded here.
CMD ["python", "-m", "tools.imp04_deployment.deploy", "--help"]
