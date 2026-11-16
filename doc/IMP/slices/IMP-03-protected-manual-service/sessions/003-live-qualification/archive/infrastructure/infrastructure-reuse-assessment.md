# IMP-02 infrastructure reuse for IMP-03

2026-11-13. User confirmed there is no independent IMP-03 infrastructure and asked whether existing IMP-02 infrastructure can be reused. This is a read-only feasibility assessment, not authorization to provision or change the retained lab. The primary collected selected public live metadata; `imp_platform` reviewed source and returned findings without edits or live commands.

**Yes. The existing workstation, Docker/kind cluster, Kubernetes/Calico/storage facilities and pinned product images can support IMP-03. A separate workstation or second full cluster is not technically necessary.** Sharing the running SPIRE, Keycloak and PostgreSQL instances is also technically plausible, with separate IMP-03 identities and state, but requires an explicit revision of the current guide's independence assumptions and fresh qualification. Neither option is deployed or qualified by this assessment.

## What was actually checked

All Kubernetes commands used `/private/tmp/care-link-imp02-002/cluster/kubeconfig`, context `kind-care-link-imp02-002`. No default context was changed, manifests applied, tokens issued, registrations created or provider accounts read/modified.

- The single node is Ready. SPIRE server/agent/CSI, Keycloak, PostgreSQL, main, identity and fence-custodian pods are Running with ready containers. Host help/static containers remain present outside kind. Kubernetes advertises 14 CPUs and 8,124,000 KiB memory; these are capacity values, not measured spare capacity or an IMP-03 performance qualification.
- Existing PostgreSQL is 18.3 with `ssl=on` and minimum TLS1.3 configured. Its non-template databases are `identity`, `keycloak`, `postgres`. The two IMP-03 databases, two runtime logins and three business group roles do not currently exist. This was a metadata SELECT in an explicit read-only transaction over the pod-local admin socket, not a new TLS connection qualification or application-data inspection.
- SPIRE lists six public IMP-02 node/host/workload registration entries, including `/lab/identity`, `/lab/main`, `/lab/help` and `/lab/identity_provider`. None of the five `/demo/{identity,core,data,pdp,journal}` workload IDs exists. Public registration metadata does not establish that new workloads would attest successfully.
- Live PostgreSQL ingress permits only `identity` and `keycloak` pods in its own namespace. An IMP-03 namespace would require a separate, narrowly scoped permission on the shared destination plus matching source egress; copying a connection string cannot establish reachability.
- Existing published browser ports are main18443, provider20443, help19443 and static21443. The example manual28443 is distinct from these observed bindings; no claim is made that it is free from every other host process. The kind node's configured host mappings do not publish manual28443, so a deliberate ingress arrangement is needed.

Evidence: [selected inventory](evidence/imp02-reuse-inventory.json), [read-only PostgreSQL metadata](evidence/imp02-reuse-postgres.json), [public SPIRE registrations](evidence/imp02-reuse-spire.json). Exact command arguments and observation timestamps are retained. Secrets, database rows and workload private keys were not exported.

## Reuse matrix

| Component | Can it be reused? | Required IMP-03 separation or change |
|---|---|---|
| Workstation/Docker engine | Yes | New named resources and leases; acknowledge common host/VM failure domain. |
| Existing kind/Kubernetes/Calico cluster | Yes | New IMP-03 application namespace/service accounts, exact policies, separate storage/configuration; do not overwrite IMP-02 objects or cluster-wide components. |
| Storage provisioner and cached product images | Yes | New claims/volumes and credential custody. Do not attach existing identity DB, help spool, fence ledger or SPIRE state as IMP-03 application state. |
| Running PostgreSQL instance | Feasible under a revised shared-service profile | Fresh `imp03_identity_002`, `imp03_runtime_002`, `imp03_identity_runtime_002`, `imp03_data_runtime_002` and noncolliding business group roles; new passwords and scoped grants. Same server/PVC remains a shared availability/administration boundary. Current guide calls for an independent instance. |
| Running Keycloak instance | Feasible under a revised shared-service profile | New `care-link-imp03` realm, browser client, audience, callback and three separately issued synthetic MFA accounts. Preserve `care-link-imp02` realm/clients/actors. Actual issuer may use existing `id.localhost:20443` with the new realm path; it need not retain the example hostname/port. Verify certificate/hostname and separate browser cookie hosts. |
| Running SPIRE server / platform attestation facilities | Feasible under a revised shared-service profile | New exact `/demo/*` registrations/selectors and an explicit node/agent/mount plan. Preserve old registrations, issuer policy, keys and restriction state. Kubernetes namespace/service-account/image selectors must distinguish IMP-03 workloads; host journal needs its own correctly scoped attestation/custody. Shared issuer failure affects both stages. |
| Existing Envoy product image | Yes | Generate new proxies, role-specific backend/egress/authz sockets, certificate identities and exact routes. Existing IMP-02 proxy processes/configuration do not implement the new graph. |
| IMP-02 application image/processes | No direct substitution | It has the old entrypoint and lacks the IMP-03 data/PDP/journal composition. Build current role artifacts and qualify their isolation. The successful developer core smoke is not that deployment. |
| Host help/static | Potential bounded reuse | Existing independent origins can support appropriately scoped availability checks without changing accepted content. HTTP200 shell availability does not establish IMP-03 account/help-service integration or truthful protected-help behavior. Keep their off-cluster boundary. |
| New PDP, host journal and restrictive fence | New resources required | Independent IMP-03 policy/admission, journal key/state and fence/socket/ledger. Keep host recovery history outside application-cluster custody; never reset or reuse the IMP-02 fence. |

## Two concrete options

**A — Reuse the substrate, add separate IMP-03 service instances.** Recommended when retaining the current guide's service independence and minimizing changes to accepted IMP-02 state are the priority. Use the current cluster/Docker/images/provisioner, with fresh IMP-03 application/trust resources, DB/provider instances and separate host journal/custody. Record the shared host/control-plane limitations. This still needs deployment manifests and resource measurement; it is not accomplished by a namespace rename.

There are two specific trust-deployment collisions to resolve before choosing A. `tools/imp02_lab/spire.py` uses host-network/host-PID agents and fixed health port8080. `tools/imp02_lab/csi.py` defines the cluster-wide `csi.spiffe.io` driver and a fixed kubelet plugin path. An unchanged second copy may collide or replace existing mounts. A separate trust deployment needs a disjoint agent/socket/health/mount integration or another isolated node/container arrangement. Do not reinstall the existing cluster-wide CNI/CSI to add IMP-03.

**B — Reuse the running infrastructure services with isolated IMP-03 tenants/state.** Feasible and potentially less resource-intensive: share cluster/Calico/SPIRE server/Keycloak/PostgreSQL, add new IMP-03 application workloads and identities, fresh realm/accounts, fresh databases/logins, new role proxies and new off-cluster journal/fence custody. The checked database/registration names currently leave room for this. It requires a deliberate shared-infrastructure profile replacing the guide's independent-instance restrictions, exact scoped additions and regression checks of affected IMP-02 controls. It does not permit old credentials, subjects, workload identities or fences to stand in for IMP-03 issuance.

The architecture does not inherently require duplicating a full stack for every implementation stage: `doc/HLD/07-deployment-and-delivery.md` explicitly permits separate identity credentials/databases sharing a PostgreSQL instance (line51), and a phased compatible rollout rather than duplicate full stacks (line73). That supports evaluating B; it does not itself authorize live changes or establish their safety. Namespace/database/realm separation isolates selected privileges, not the shared administrator, issuer or outage boundary.

## Required work before either option can serve

1. Bind the chosen shared/dedicated components, exact write ownership, ports, storage and rollback. Reconcile the guide/runbook explicitly; preserve current source and G-02 evidence, with fresh checks for any affected behavior.
2. Add bounded IMP-03 deployment/issuance tooling. `tools/imp02_lab/model.py` fixes the old session/cluster/namespace; its create command refuses an existing cluster. The old provider bootstrap fixes its realm/clients, and SPIRE helpers accept only old roles. Do not rerun these tools with superficially renamed inputs.
3. Build and pin actual role artifacts; publish only protected ingress, establish role custody/attestation, verify OPA for Linux, issue actors/MFA and browser TLS, then prepare/provision the fresh IMP-03 state. Provisioning refuses existing target names and global business-role collisions; do not bypass that protection.
4. For shared services, make only exact new network/registration/realm/database additions. Role-loss tests should stop only new IMP-03 identity/PDP/journal processes; the audit fault should alter only the new data-runtime grant; fence only the new workload. Do not inject a shared issuer/provider/database outage while claiming IMP-02 is unaffected. Renewal/expiry observations need a fault scope that preserves the accepted lab or a separately scoped disruptive test.
5. Resolve Q-01 and complete target-bound normal/adverse/coverage evidence. Reusing a provider or host surface does not discharge the fresh-account, current-authority, human usability, operational or G-03 decision obligations.

No infrastructure, source implementation, guide constraint or acceptance state was changed. The existing G-03 packet remains a draft local-engineering record.
