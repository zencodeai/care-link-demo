# IMP-02 — approval requested for node-agent lifetime repair

The three approved fault tests ran. Main loss/whole-kind-node loss and same-session recovery passed. Expired workload admission was denied403 on the same existing TLS connection. Issuer recovery exposed a configuration defect: the SPIRE node agents inherited the same300second lifetime as workloads. The outside join-token agent's credential expired while the issuer was unavailable, its process exited, and its shared PID namespace stopped help/proxies.

The lab has been manually restored under the unchanged300second policy. Only the expired join-token node and its generated bootstrap alias were re-enrolled; existing logical host alias, workload registration objects, CA/PVC, help spool and generation1 restrictions were preserved. This manual repair is recorded, not called automatic recovery.

## Exact proposed change

Apply the single reviewed `agent_ttl = "1h"` line in `tools/imp02_lab/spire.py` to the existing `spire-config` ConfigMap's `server.conf`, then restart only `deployment/spire-server` in `care-link-imp02-002-trust` with its current PVC. The setting applies to SPIRE infrastructure-agent certificates in this named demo. `default_x509_svid_ttl` and all four workload registration helpers remain300seconds. Existing app identities, routes, permissions, trust roots and fences remain in place.

An agent credential could consequently remain cryptographically valid for up to one hour rather than five minutes. Workload certificates used by applications retain the five-minute limit and fresh deterministic authorization/fencing. This separates infrastructure enrollment lifetime from workload permission enforcement. A stolen agent credential could request eligible workload identities during that longer validity period; five-minute workload certificates alone do not cap total misuse at five minutes. Per-operation workload fences remain effective for denied IDs.

SPIRE1.16 documents that agent_ttl otherwise inherits the default workload TTL: https://github.com/spiffe/spire/blob/v1.16.0/doc/spire_server.md . The source regression checks the separate one-hour agent lifetime and unchanged300second workload defaults/helpers.

## Verification after approval

1. Verify the running server has only the intended configuration change; preserve CA/PVC/registration/fence snapshots.
2. Wait for normal node-agent certificate renewal and verify actual near-one-hour expiry before testing. Already-issued certificates do not gain time retroactively. Keep the current host agent running.
3. Repeat only the issuer-stop/workload-expiry/recovery test. Require403 after real workload expiry without reconnect, then restore the same issuer and observe fresh workload credentials/current admission with the infrastructure agent still alive. Record any proxy-only channel reconnect.
4. Reconcile final evidence and present G-02 for its separate human decision. Participant admission remainsdisabled.

Automatic approval review rejected applying this persistent security-lifetime change because the prior approval covered shutdown-and-restore tests. The change is proposed and tested in source, not applied live. No workaround to the rejected lifetime change was used; manual restoration kept the old policy.

The proposed one-hour agent lifetime covers this bounded420second issuer drill. It does not qualify longer issuer outages, agent process loss or host reboot recovery; manual re-enrollment can still be required after agent expiry/loss.
