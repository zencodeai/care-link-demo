# Protected IMP-03 runtime

This is the source launcher for five independent processes: `core`, `data`, `identity`, `pdp` and host `journal`. It uses the existing kernel-verified Unix backend, SPIRE/Envoy mTLS and live restrictive fence interfaces. It does not mutate the retained IMP-02 lab, install trust roots, create a fake SVID, provision an OIDC provider, or infer human G-03 acceptance. The default core image remains developer-only. This launcher currently uses the locked development workspace distribution; per-role package/image builds and deployed isolation must be separately qualified.

`bindings.example.json` is the exact binding shape, with illustrative independent addresses and **unissued credential placeholders**. Copy it to an owner-only file outside the repository and replace every `ISSUED_*` value with the independently issued synthetic target value. It is not a deployed environment or a credential generator. `validate_binding` is the executable binding validator; it rejects unknown top-level/custody/outbound fields, overlapping credentials, wrong database names, absent actor roles and unsafe paths. `check` also constructs each real role's dependencies; it never reports live trust as verified.

## External target and custody contract

The target is a separately leased Linux runtime (including an isolated Linux VM/container target on the accepted macOS ARM64 workstation), with its own SPIRE deployment, role-attested Envoy sidecars, independent PostgreSQL instance, OIDC realm/client and named actor accounts. Do not point this configuration at IMP-02 credentials, sockets, databases, volumes, namespaces, SPIRE registrations, provider realm or processes. A cluster/host supervisor must supply these resources; this source launcher does not provision them.

Use the sample's distinct non-root application UIDs 22011–22015, proxy UID 22002 and fence UID 22000, or explicit disjoint replacements. No application UID may equal **any** proxy/fence UID. Fixed shared fence-reader GID22999 is reserved and must differ from every application, proxy, fence and authorization UID; this prevents shared readers from entering another role’s egress custody. Each role receives only its own `ROOT/<role>` directory and the specifically listed sockets/mounted public artifacts. Application processes need supplementary groups 22002 (socket group assignment only; kernel UID checks still enforce trust) and 22999 (read-only authenticated fence transport). Runtime directories are 0700; the prepared root becomes 0711 only when the privileged supervisor assigns ownership. Configuration and private keys are 0600. The operator binding/admin files remain privileged 0600. The privileged supervisor can read all custodians, as expected; application processes cannot.

Each `backend_socket` parent is application-owned mode 0710, group proxy UID; egress socket parents are proxy-owned mode 0710, group originating application UID, and sockets mode 0660. Ext-authz socket is authorization-custodian owned and proxy-only. SPIRE Workload API access belongs only to the assigned proxy and authorization custody. Do not expose an unprotected TCP application listener. Each backend request requires kernel `SocketPeer` provenance from the proxy UID; private routes additionally require exact SPIFFE peer/route, current fence generation and current certificate deadline.

SPIRE must issue `spiffe://care-link.demo/demo/{core,data,identity,pdp,journal}` to the respective independently attested workloads. Register exact pod/service account/container image selectors using the pinned Envoy image; registration content is supplied by the target supervisor. The fence allows only those identities, and its authenticated Unix service is owned by configured `fence_uid`. Envoy ext-authz uses the existing `WorkloadEnforcer`/`AuthorizationServer` against that fence with exact rules returned by `tools.imp03_runtime.config.routes(role)`. Attestation, renewal and route/fence fault behavior require deployed evidence, not merely rendered config.

Only core's private browser TLS listener publishes `main_origin`; its certificate must match that origin. The provider must issue distinct participant/worker/supervisor subjects, current account mappings and privileged MFA. OIDC access audience differs from client ID and matches independently configured provider issuance. Browser/provider CA trust and local DNS are target inputs. Identity owns provider credentials and its own DB login. Data alone owns business DB credentials, content/cursor keys and remote journal/channel adapters. PDP owns admitted policy source/signature and an explicitly digest-pinned platform OPA executable. Journal alone owns its private signing key and filesystem state. Machine duties remain capability-disabled by default; this launcher exposes no unsigned duty endpoints.

## Exact preparation and startup

The commands below run inside the separately leased Linux target with the repository at `/app`, locked environment `/app/.venv`, built client `/app/apps/web/dist`, and private operator inputs `/operator/imp03-bindings.json` and `/operator/imp03-admin.json`. No command addresses IMP-02. The binding file contains the exact addresses/UIDs/paths of the already provisioned independent target.

```sh
set -eu
cd /app
umask 077
test ! -e /run/care-link-imp03-002
install -d -m 0711 /run/care-link-imp03-002
while read -r role app_uid auth_uid; do
  install -d -m 0711 /run/care-link-imp03-002/"$role"
  install -d -o "$app_uid" -g 22002 -m 0710 /run/care-link-imp03-002/"$role"/backend
  install -d -o 22002 -g "$app_uid" -m 0710 /run/care-link-imp03-002/"$role"/outbound
  install -d -o "$auth_uid" -g 22002 -m 0710 /run/care-link-imp03-002/"$role"/authorization
  install -d -o 22002 -g 22002 -m 0700 /run/care-link-imp03-002/"$role"/proxy
done <<'ROLES'
identity 22011 22031
core 22012 22032
data 22013 22033
pdp 22014 22034
journal 22015 22035
ROLES
install -d -o 22000 -g 22999 -m 0710 /run/care-link-imp03-002/fence
install -d -o 22000 -g 22000 -m 0700 /run/care-link-imp03-002/fence/ledger
/app/.venv/bin/python -m tools.imp03_runtime prepare \
  --bindings /operator/imp03-bindings.json \
  --output /run/care-link-imp03-002/configuration --assign-ownership
/app/.venv/bin/python -m tools.imp03_runtime render-mesh \
  --bindings /operator/imp03-bindings.json \
  --output /operator/imp03-rendered-mesh
/app/.venv/bin/python -m tools.imp03_runtime provision \
  --root /run/care-link-imp03-002/configuration \
  --admin-config /operator/imp03-admin.json
while read -r role auth_uid; do
  install -o "$auth_uid" -g "$auth_uid" -m 0600 /operator/imp03-rendered-mesh/"$role"-authorization.json /run/care-link-imp03-002/"$role"/authorization/config.json
  install -o 22002 -g 22002 -m 0600 /operator/imp03-rendered-mesh/"$role"-envoy.json /run/care-link-imp03-002/"$role"/proxy/envoy.json
done <<'ROLES'
identity 22031
core 22032
data 22033
pdp 22034
journal 22035
ROLES
install -o 22000 -g 22000 -m 0600 /operator/imp03-rendered-mesh/fence.json /run/care-link-imp03-002/fence/config.json
```

`prepare --assign-ownership` and `provision` run as the specifically authorized privileged Linux custody supervisor. They do not create socket parents or external dependencies. Provisioning is **initial-only**, refuses existing named databases/logins, applies reviewed migrations, then creates exact identity account and business principal bindings and journal/bootstrap state. Partial failures are retained for inspection; there is no automatic reset/drop/reuse. Do not retry provision against partial existing resources. Admin JSON has exactly `identity_admin_dsn` and `data_admin_dsn`, each a verify-full admin DSN to the corresponding **independent** PostgreSQL endpoint. Runtime DBs/logins are pinned:

| Role | DB | Login |
|---|---|---|
| identity | `imp03_identity_002` | `imp03_identity_runtime_002` |
| data | `imp03_runtime_002` | `imp03_data_runtime_002` |

The supervisor installs each rendered `<role>-envoy.json` into that role's `mesh.<role>.proxy_config`, sets socket ownership, starts the independently attested proxies, their ext-authz services, SPIRE and the live fence. It then runs these exact checks under each role's assigned UID (for example Linux `setpriv`):

```sh
setpriv --reuid=22011 --regid=22011 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime check --root /run/care-link-imp03-002/configuration --role identity
setpriv --reuid=22012 --regid=22012 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime check --root /run/care-link-imp03-002/configuration --role core
setpriv --reuid=22013 --regid=22013 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime check --root /run/care-link-imp03-002/configuration --role data
setpriv --reuid=22014 --regid=22014 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime check --root /run/care-link-imp03-002/configuration --role pdp
setpriv --reuid=22015 --regid=22015 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime check --root /run/care-link-imp03-002/configuration --role journal
```

Start each in its **own supervisor process/container**, preserving these exact argv and assigned UIDs (run in separate terminals/process definitions, not sequentially in one blocking shell):

```sh
setpriv --reuid=22011 --regid=22011 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime serve --root /run/care-link-imp03-002/configuration --role identity
setpriv --reuid=22012 --regid=22012 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime serve --root /run/care-link-imp03-002/configuration --role core
setpriv --reuid=22013 --regid=22013 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime serve --root /run/care-link-imp03-002/configuration --role data
setpriv --reuid=22014 --regid=22014 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime serve --root /run/care-link-imp03-002/configuration --role pdp
setpriv --reuid=22015 --regid=22015 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime serve --root /run/care-link-imp03-002/configuration --role journal
```

Identity runs restriction-only expired credential/proof cleanup every five seconds. No account cleanup authority is inferred. Core's current channel endpoint is only callable by data and never reenters data. This avoids recursive SSE authorization. The remote journal binds every signed response to a fresh caller nonce, including live serving generation; final service checks independently verify barrier freshness. Core signs body/path/key/evidence/deadline-bound envelopes, obtains genuine metadata and preliminary PDP results; data resolves current identity and repeats final policy/guard/audit checks independently.

## Deterministic dependency barriers

The Linux supervisor may pause **only** a receipt-bound owned dependency process. The command validates exact session, root, role, `/proc` UID and executable argv before signaling. Runtime deadlines/timeouts remain enforced while a dependency is stopped.

```sh
/app/.venv/bin/python -m tools.imp03_runtime fault --root /run/care-link-imp03-002/configuration --role pdp --action pause
# Run the live PDP-loss G-03 check in another browser process.
/app/.venv/bin/python -m tools.imp03_runtime fault --root /run/care-link-imp03-002/configuration --role pdp --action resume
```

Repeat with `journal` and `identity` for their declared adverse checks. These commands never locate processes by broad name or touch IMP-02. Always resume the exact paused dependency in the operator's cleanup. A removed/stale receipt or PID mismatch fails closed. Application shutdown uses its ordinary supervisor; no broad process/container cleanup command is provided.

`render-mesh` also emits `<role>-authorization.json` and `fence.json`. Install authorization configs mode 0600 to the corresponding role's authorization custodian UID 22031–22035; install fence config to UID22000. The private `trust_bundle` path is the independent SPIRE bundle, and `authorization_uid` must differ from every application/proxy/fence UID. The supervisor creates mode0700 authorization config and ledger directories and mode0710 proxy-group socket parents. The fence socket parent is UID22000:GID22999 mode0710; its ledger is UID22000 mode0700. It gives authorization processes supplementary GID22999 and proxy process GID22002. Start each trust process in its own supervisor entry:

```sh
setpriv --reuid=22000 --regid=22000 --groups=22999 /app/.venv/bin/python -m tools.imp03_runtime trust --role fence --config /run/care-link-imp03-002/fence/config.json
setpriv --reuid=22031 --regid=22031 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime trust --role authorization --config /run/care-link-imp03-002/identity/authorization/config.json
setpriv --reuid=22032 --regid=22032 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime trust --role authorization --config /run/care-link-imp03-002/core/authorization/config.json
setpriv --reuid=22033 --regid=22033 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime trust --role authorization --config /run/care-link-imp03-002/data/authorization/config.json
setpriv --reuid=22034 --regid=22034 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime trust --role authorization --config /run/care-link-imp03-002/pdp/authorization/config.json
setpriv --reuid=22035 --regid=22035 --groups=22002,22999 /app/.venv/bin/python -m tools.imp03_runtime trust --role authorization --config /run/care-link-imp03-002/journal/authorization/config.json
```

Each exact pinned Envoy sidecar starts as UID/GID22002 with its generated configuration, for example `/usr/local/bin/envoy --config-path /run/care-link-imp03-002/core/proxy/envoy.json --log-level critical --disable-hot-restart`. Give only that sidecar its SVID socket and role backend/egress/authorization socket mounts. The generated node cluster is `care-link-imp03-002`. Do not reuse the IMP-02 SPIRE Workload API socket or authorization trust configuration. PID fault barriers use Linux pidfds plus birth-time/argv/UID checks to avoid signaling a recycled PID.

Restriction authority has a separate fixed UID22001 (`FENCE_RESTRICT_UID`); it is never the UID22000 fence ledger owner or an ordinary reader/application/proxy/authorization custodian. Bindings reject both reserved UID22001 and shared reader GID22999 for runtime custodians. An explicitly authorized supervisor may run a one-way restriction in that separate identity, with the exact current fence generation and a fresh UUID command. There is no unfence/reset command:

```sh
setpriv --reuid=22001 --regid=22001 --groups=22999 /app/.venv/bin/python -m tools.imp03_runtime restrict --fence-socket /run/care-link-imp03-002/fence/fence.sock --fence-uid 22000 --peer core --command-id 03000000-0000-4000-8000-000000000099 --expected-generation 0
```
