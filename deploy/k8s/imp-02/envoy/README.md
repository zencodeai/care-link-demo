# Envoy/SPIRE configuration source

Use `care_link_workload_trust.ProxyInputs`, `build_envoy` and
`spire_registration` from the owned workload package to prepare the exact
candidate. The builder produces JSON accepted for review, without starting a
proxy or registering a workload. It requires actual immutable image/version
pins, local identity, peer routes, protected socket paths and a measured SVID TTL;
none is supplied as an invented installed default.

The configuration binds SPIRE SDS to its protected agent socket, exact client
URI SANs to the mTLS listener, every route to the fail-closed Unix ext_authz
listener, and the application to a separate Unix socket. Group/UID custody must
permit only the distinct authorized proxy and enforcer/application identities.
Run the backend with the package's pinned ProtectedUnixH11Protocol so the
identity workload-verifier receives kernel socket facts rather than public
headers. No public admin/health bypass is added here.

Before any deployment, bind the candidate to actual Envoy/SPIRE versions, validate
it with that Envoy binary, observe namespace/service-account/image selectors,
verify issuer/bootstrap custody and test rotation/outage. Prove default-deny
CNI/host routes using active permitted controls and explicit direct-backend,
alternate-host-port, IPv6 and compromised-existing-channel cases. This directory
contains source guidance, not deployed manifests or passed route evidence.
