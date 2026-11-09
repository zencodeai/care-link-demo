# IMP-02 trust deployment candidate

Session001 supplied the initial source-only boundary; current live work and observations belong to the session002 execution records. The initial namespace policy denies every ingress and egress path. It deliberately has no permissive pod-label trust exceptions. Applying it alone yields no working login/help service and does not establish SPIFFE attestation, proxy, host-firewall or CNI enforcement.

Before rendering and creating the actual lab overlay, fill and review the actual provider, SPIRE, Envoy, CNI and host-route bindings in `config/demo/imp-02-admission.json`. Null values fail admission; they are not defaults. Do not mount issuer administration, business DB, application delegation credentials or Kubernetes API tokens into runtime. Backend Unix sockets require distinct proxy/app OS identities and verified ownership. Do not expose backend HTTP listeners as a workaround.

The route qualification requires a live allowed control to the exact tested target from a different declared caller. From the repository root, after the named lab exists:

```sh
python3 tools/probe_trust_routes.py --context EXACT_LAB_CONTEXT \
  --allowed-pod EXACT_ALLOWED_POD --forbidden-pod EXACT_RUNTIME_POD \
  --target EXACT_ACTIVE_TARGET --port EXACT_PORT
```

The command reads the named pods through existing kubectl access and opens bounded TCP connections. It creates no resources. It exits nonzero for bypass, missing probe Python, failed control, or connection refusal. A timeout after a successful same-target control establishes only the observed TCP drop. Run against each DB/model/backend/internet/alternate host port family with a known active control and retain target/source identity, configuration and timestamps. Separately verify mTLS SAN/issuer/expiry, unknown trust roots, workload attestation selectors, per-request current fence on open connections, issuer outage/rotation, IPv4/IPv6, host-VM routes and private browser ingress. TCP observations do not discharge these tests.

Account retention, real role provisioning, independently reviewed EN/FR fallback content and this workstation's trust/network observations remain admission inputs. No G-02 acceptance, participant use, model startup or host changes follow from source configuration.

## Session002 runnable lab

Session002 adds `python -m tools.imp02_lab` and the narrowly scoped
[infrastructure binding](INFRASTRUCTURE-DELTA.md). The coordinator owns live
resource actions and their evidence; this README is a reproducibility guide,
not a claim that every probe passed. The [product pins](products.json) record
verified upstream inputs and the private execution records bind actual local
builds and observations.

Use a private JSON input file outside git. It names session `imp02-002`, the
immutable `images` map, the downloaded `kind_binary` and its `kind_sha256`,
the pinned `calico_manifest` and its `calico_sha256`, and an empty temporary
`state_dir`. The dedicated cluster is `care-link-imp02-002`; every kubectl
operation uses its explicit private kubeconfig and context. Acquisitions and
state stay under temporary storage. The CLI verifies the actual named kind
container label before mutating an existing cluster; it never adopts another
cluster or updates the default kubeconfig.

```sh
python -m tools.imp02_lab create --inputs /ABS/PRIVATE/inputs.json --execute
python -m tools.imp02_lab render-dependencies --inputs /ABS/PRIVATE/inputs.json --output /ABS/PRIVATE/dependencies.json
python -m tools.imp02_lab apply-dependencies --inputs /ABS/PRIVATE/inputs.json --execute
python -m tools.imp02_lab apply-spire --inputs /ABS/PRIVATE/inputs.json --execute
```

The coordinator first supplies the generated PKI/password/init-SQL Secrets.
PostgreSQL uses its own PVC and TLS. Keycloak uses a locally built, pinned
optimized image; its fixed issuer is `https://id.localhost:20443`. The main,
help and static origins use distinct `main.localhost`, `help.localhost` and
`static.localhost` hosts with ports18443,19443 and21443. Port separation alone
would expose host-only cookies to static content, so it is insufficient.
Browser resolver configuration and the identity provider's pinned internal
transport do not modify workstation hosts/DNS settings.

After the server is ready, `spire_bootstrap.approve_kubelet_serving` approves
only the exact named node's signed serving CSR. Kubelet TLS verification stays
enabled. `publish_bundle` publishes the observed public bootstrap bundle;
`register_node_alias` binds the nonreserved `/node/imp02-002` alias through
PSAT cluster/namespace/service-account selectors. `register_proxy` binds the
actual admitted application image plus Envoy image, namespace, service account
and container name. The reserved `/spire/agent/...` namespace belongs to actual
attested agent IDs. The pinned SPIRE1.16 CLI uses `-x509SVIDTTL` in seconds for
workload entries; token bootstrap still uses `-ttl` in seconds.

The coordinator generates role configuration and starts the exact socket-seed
Job before application pods. Secret sources for this Job live in the trusted
infrastructure namespace. The application, proxy and authorizer see different
owner-only configuration and socket PVC directories; a writable common parent
is never shared. `proxy_config.identity`, `proxy_config.browser`,
`authorization_config` and `fence_config` supply the exact role routes. BFF
routes have a bounded40second mesh budget, browser45seconds; help's one-second
fresh-authority budget and ext_authz250ms budget remain unchanged.

```sh
python -m tools.imp02_lab apply-seed --inputs /ABS/PRIVATE/inputs.json --execute
python -m tools.imp02_lab apply-applications --inputs /ABS/PRIVATE/inputs.json --execute
python -m tools.imp02_lab render-host --inputs /ABS/PRIVATE/inputs.json --output /ABS/PRIVATE/host.json
```

`host_support.composition` keeps help outside kind. Its seed container receives
selected private files through `docker cp` into temporary memory, then
`host_support.seed_script()` writes only named Docker volumes with exact
ownership. No Mac filesystem bind or Docker administration socket is mounted.
The helper `generate_host_token` captures a one-use SPIRE token directly into
an owner-only file; `register_host_proxy` binds the admitted help proxy's Unix
UID. The help application has no network and no Workload API mount. Only its
separately attested Envoy proxy has the egress socket and Workload API. The
seed container should be removed after population; it is not a serving role.

An isolated active-control listener must exist before network qualification:

```sh
python -m tools.imp02_lab apply-network --inputs /ABS/PRIVATE/inputs.json --host-probe-ip EXACT_ACTIVE_IP --execute
python -m tools.imp02_lab probe-network --inputs /ABS/PRIVATE/inputs.json --host-probe-ip EXACT_ACTIVE_IP --output /ABS/PRIVATE/network-evidence.json
```

The harness proves an allowed runtime-to-broker route, then requires an active
allowed caller to each exact forbidden target before testing runtime denial.
A refusal, absent listener, command error or untested route fails the check.
The isolated fixtures are labelled and never advertised as product data/model
services. Real browser, SPIRE/Envoy, credential rotation/expiry, still-open
channel restriction, PostgreSQL restart, host-route and IPv6 observations stay
separate. The named Linux UID integration test proves kernel reader/writer
separation and a persistent socket spanning a live fence change; nonroot Mac
runs explicitly skip that positive test.

Outage browser tests use `OutageController`'s owner-only filesystem handshake.
Only the primary supervisor owns process/container stop and restore actions;
there is no browser control endpoint. Its `mock_used` acknowledgment reflects
what the injected action actually did, never an inferred success.

Stop named host processes/containers when a demonstration ends. A separate
explicit cleanup may run `destroy --execute`, which verifies and deletes only
this kind cluster. Host-support Docker volumes are distinct, retain private
state, and are never removed through a global prune. No cleanup or source file
constitutes G-02 acceptance or participant admission.

## Stable issuer before private qualification

The first prototype SPIRE manifest used an `emptyDir` datastore. This would
lose the CA and registrations when the server pod was removed, so a scale-down
could not honestly demonstrate recovery of the same issuer. Before any private
browser positive or lifecycle qualification, the coordinator selected an
explicit prototype rebootstrap onto the `spire-server-data` PVC with Recreate
strategy. The earlier prototype CA/registrations are discarded as prototype
state, not migrated or credited as recovery evidence. Node/host agents, public
bundle copies, exact registrations and authorizer trust must be rebound to the
new stable issuer before positive tests. Application browser TLS uses its
separate local CA. Subsequent issuer outage/renewal tests must retain this PVC;
issuer restoration cannot be inferred from recreating an empty datastore.

Proxy-only admin UDS volumes provide public certificate evidence through
separate maintenance fixtures, without mounting them into applications:

```sh
python -m tools.imp02_lab.certificates sample --inputs /ABS/PRIVATE/inputs.json --role help --output /ABS/PRIVATE/cert-before.json
python -m tools.imp02_lab.certificates renewal --inputs /ABS/PRIVATE/inputs.json --role help --output /ABS/PRIVATE/cert-renewal.json
python -m tools.imp02_lab.certificates ipv6 --inputs /ABS/PRIVATE/inputs.json --output /ABS/PRIVATE/runtime-ipv6.json
python -m tools.imp02_lab.certificates host-ipv6 --inputs /ABS/PRIVATE/inputs.json --output /ABS/PRIVATE/host-ipv6.json
```

The certificate observer reads Envoy's actual loaded `/certs` serial, URI SAN
and expiry plus bounded connection counters. It never exports Workload API
keys. SPIRE's default pretty `api fetch x509` is metadata-only; its JSON mode
contains key material and must not be captured as ordinary evidence. The
separate expiry observer requires the operator to stop the named stable
issuer, keeps a real help-to-identity HTTP1 connection active, and credits an
expiry rejection only after the observed leaf deadline with unchanged
connection count and advanced request count. Early failure or reconnection is
not a successful persistent-channel test. The observer does not stop or restore
resources itself. IPv6 outputs are interface observations; they never turn an
absent listener into a denial claim.
