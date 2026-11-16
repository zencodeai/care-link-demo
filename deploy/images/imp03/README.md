# IMP-03 qualification source-workspace image

This image runs the current `tools.imp03_runtime` launcher and bounded `tools.imp03_shared` operator helpers from `/app`, with the locked environment at `/app/.venv` and built client at `/app/apps/web/dist`. The launcher composition imports multiple role packages, so this image includes all current Python workspace packages. **It does not establish per-role package/image isolation.** Role credentials, process UIDs, mounts, sockets, network controls and protected serving require separate deployment configuration and evidence.

The Python and uv defaults are immutable references matching `services/core/image-inputs.json`. The build runs `uv sync --locked --no-dev --all-packages`; editable package source remains beside its environment. The Dockerfile-specific deny-by-default context includes workspace manifests/source, identity/data migrations, public IMP-03 configuration, selected launcher/operator Python modules and the already built main client. The top-level test/documentation trees, Git metadata, local environments, caches and private fixtures are excluded. The actual serving-image inventory nevertheless contains co-located service tests admitted beneath workspace directories; this qualification artifact is not a minimal runtime distribution. See session003 `option-b-deployed-artifacts.json` for observed contents. No provider/runtime binding, certificate private key, password, token or OPA binary is supplied by this image.

Build from the repository root only after the actual client bundle exists and the coordinator has scoped the build/output. For the session003 qualification tag:

```sh
docker build --file deploy/images/imp03/Dockerfile \
  --tag care-link-imp03:qualification-003 \
  --iidfile /private/tmp/care-link-imp03-003-shared/image-id.txt .
```

The output directory must already exist with appropriate private operator custody. Record the resulting image ID and source binding before deployment. Building does not provision infrastructure or activate a protected listener.

The default nonroot UID/GID is `65532:65532`; the default command prints launcher help. An authorized supervisor must explicitly choose preparation/provisioning or a serving/trust role, assign that operation's Linux UID/groups and mount only its required inputs/state. No default serving configuration or live credentials exist. The PDP additionally needs the separately acquired, recorded and digest-verified Linux OPA executable mounted at its configured path (normally `/opt/opa`); the Dockerfile performs no OPA download. Supervisor privileges needed for fresh custody assignment are not application-role privileges.

This artifact supports the explicitly selected shared-infrastructure Option B. It does not itself amend an old guide, modify IMP-02, verify workload attestation, qualify browser TLS, admit participants or record G-03 acceptance.
