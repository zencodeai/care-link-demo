# Workload trust source candidate

The package implements a local Unix HTTP authorization listener and the selected
Envoy/SPIRE family configuration builder. Imports create no files, sockets,
credentials, registrations or deployments. Participant admission stays disabled
until the actual environment is qualified.

`WorkloadEnforcer` accepts only an exact kernel-verified proxy UID, a single
SANITIZE_SET XFCC certificate/URI entry, a trusted current client certificate,
and an exact configured SPIFFE/method/path rule. It verifies the X.509 client
chain with pinned cryptography, checks certificate validity again after the live
fence read, and rereads the complete restrictive fence on every operation. It
rejects multi-entry/duplicate XFCC, URI/hash mismatch, alternate methods and
noncanonical paths. An existing TLS connection does not preserve permission
after expiry or a restrictive fence; local tests exercise reuse of identical
certificate bytes, without claiming a live Envoy TLS drill.

`AuthorizationServer(path, enforcer, owner_uid, proxy_gid)` is Unix-only. The
parent must already be mode 0710, owned by the distinct authorization-service UID
and exact proxy access GID. The created socket is 0660 with that GID. Linux
SO_PEERCRED or macOS getpeereid supplies the caller UID; unsupported APIs deny.
Group access permits connection, while only the exact proxy UID permits an
operation. Actual group membership/ACLs and isolation from application identities
must be verified on the lab. There is no same-UID production shortcut, TCP
listener, public peer-header parser, cached-positive permission, HTTP unfence or
public admin endpoint.

`FenceStore` uses an operator-created 0700 directory and 0600 file under one
explicit OS custodian shared by the local enforcer and direct backend reader. `initialize()` is exclusive-create provisioning, never an
existing-ledger repair; `restrict()` can only append restrictive records with
expected-generation and stable command checks. Writes fsync before returning.
Reads take a shared lock, loop over the entire bounded fstat length, check
concurrent size/mtime changes, and verify the complete hash chain. Missing,
partial, corrupt or unsafe files deny. This is a narrow OS-custodied local ledger,
not the business recovery journal or protection against host rollback/root.
Current negative restrictions cannot be released by any API in this package.
The authorized operator invokes the restrictive administrative method under that
service identity; no HTTP write route exists. This shares custody and does not
isolate a compromised backend/enforcer OS identity from ledger modification.
A different-UID reader cannot use this strict private-file adapter directly; it
requires a separately authenticated read protocol or reviewed immutable view.
That cross-custodian binding remains unfinished integration. The proxy stays a
distinct UID and receives only the narrowly scoped Unix socket access group.

`BackendVerifier` is the callable for the identity factory's `workload_verifier`
port. Construction requires the declared backend UID to equal the current
process's effective UID and differ from the configured proxy UID. It accepts
forwarded identity headers only when a kernel-derived
`SocketPeer` capsule exists in the trusted ASGI scope, then checks exact peer
role/method/path, current fence generation and certificate deadline again.
`ProtectedUnixH11Protocol`, pinned to Uvicorn 0.38.0, supplies that capsule from the
actual accepted AF_UNIX socket in `connection_made`; it replaces any pre-existing
scope value and closes TCP/unknown sockets. Configure the backend with this H11
class, `proxy_headers=False`, `ws="none"`, and no alternate TCP listeners. Use an
already bound, permission-restricted backend Unix socket passed to
`uvicorn.Server(...).serve(sockets=[listener])`; do not rely on Uvicorn's default
Unix-socket chmod policy. The backend socket's parent/UID/GID constraints must
permit the distinct proxy while preventing application/runtime bypass. No raw
HTTP header can manufacture a Python scope capsule.

`ProxyInputs` requires immutable Envoy/SPIRE image digests, exact versions,
measured SVID TTL, local/peer SPIFFE IDs, private IPv4 listener, routes and three
distinct absolute Unix paths. `build_envoy()` emits Envoy v3 configuration with
SPIRE SDS on its protected workload socket, mandatory client certificate and
exact URI SAN matching, TLS 1.3, SANITIZE_SET XFCC, spoofable identity removal
before ext_authz, fail-closed authorization, and a Unix backend. It has no admin
listener, per-route authorization bypass, route-cache clearing, arbitrary
upstream, permissive destination or unchecked environment default.
`spire_registration()` returns a candidate entry with exact namespace, service
account, proxy container/image digest and admitted workload image digest
selectors. The actual SPIRE API/CLI binding and observed selectors must be checked
against the selected pinned product version. No labels/IP substitute for
attestation. Host workload attestation is a separate unresolved binding.

Tests cover real local kernel peer retrieval and a temporary Unix listener
rejecting the current unauthorized UID despite spoofed headers; certificate,
route, expiry, ledger and protected-ASGI checks use explicit fixtures. The actual
Unix bind test needs native socket permission; it is not skipped in the sandbox.
The H11 hook test combines real Unix/TCP sockets with a fake asyncio transport,
showing kernel capsule creation, forged-scope replacement and TCP/unknown denial.
Distinct-user positive proxy access, actual Envoy schema validation/operation,
SPIRE registration/rotation/outage, host firewall/CNI/IPv6 bypass, compromised
open TLS channel and fsync durability under host failure remain unrun. Signed
workload UUID→SPIFFE mapping and ordered restrictive signal→ledger
acknowledgement/reconciliation are unfinished source integration; account
signals explicitly reject workload-compromise events rather than mutating a
coincident account. No complete credential lifecycle or deployed containment is
claimed.

Primary references: [Envoy ext_authz](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter),
[SPIRE SDS integration](https://spiffe.io/docs/latest/microservices/envoy-x509/readme/),
[SPIRE Kubernetes selectors](https://github.com/spiffe/spire/blob/main/doc/plugin_agent_workloadattestor_k8s.md),
[cryptography verification](https://cryptography.io/en/latest/x509/verification/).

## Cross-custodian fence channel

`FenceServer` owns the private ledger under its own UID. Its0710 channel
and0660 socket grant filesystem access to the declared group; the kernel's
peer UID still distinguishes read-only callers from the sole restriction
caller on every request. `UnixFenceClient` verifies the server's kernel UID
before sending a command, obtains fresh state for every read, and provides
`current`, `restrict` and `receipt` through the public `RestrictiveFence`
protocol. There is no release/reset/initialize HTTP route. An unknown command
has no receipt; a conflicting command or stale generation denies. A previously
uncertain complete ledger append is fsynced under its file lock before a fresh
durable receipt is returned. Identity can therefore retain pending state and
reconcile the exact command without inventing an acknowledged restriction.

`SocketCustody` holds an exclusive owner-only file lease. It removes only an
owned socket in a verified parent directory after an actual refused connect
and unchanged-inode check. An active, ambiguous, symlink or ordinary file is
preserved. Both listener classes clean up only their own created inode on
failed startup or close. The append-only ledger is never replaced to recover
a listener.

`operation_path` permits query parameters only on the exact GET BFF callback
and step-up proof adapters. It validates a canonical unencoded pathname,
finite field/count/length bounds, no duplicate/unknown parameters and exact
proof UUIDs. Policy matching uses the path; the original query reaches the
identity protocol validator unchanged. Every other private query denies.

Browser TLS and protected local-egress builders sanitize forwarded authority
headers, restrict exact BFF/internal routes and use SPIRE SDS with an explicit
Envoy node ID/cluster. The destination URI SAN is pinned. Bounded BFF exchange
budgets do not extend help-proof deadlines or ext_authz fail-closed behavior.

Deployed authorizers and backend verifiers also bind their own exact local
SPIFFE identity. Every protected operation checks caller **and destination**
against the same fresh fence snapshot. Fencing the destination stops later
operations on existing connections even when the caller remains valid and the
forwarded generation is current. The reusable classes allow an omitted local
identity only for generic construction; the lab authorization entrypoint
requires it explicitly and the identity backend supplies it explicitly. All
TLS builders pin both minimum and maximum to TLS1.3, avoiding the invalid
TLS1.3-minimum/TLS1.2-default-client-maximum range observed during qualification.
