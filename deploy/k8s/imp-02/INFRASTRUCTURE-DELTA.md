# Disposable lab infrastructure binding — session 002

The completion task requires actual identity, proxy and network enforcement.
LLD11's application restriction remains: no privileged, hostNetwork or direct
hostPath application pod; no runtime service-account token or issuer/admin key.

The coordinator selected a narrow infrastructure exception for this private
synthetic workstation lab. Calico, SPIRE node attestation and the SPIFFE CSI
driver may use the required node PID/network interfaces and named node socket,
kubelet and CNI paths **inside the disposable kind node**. These are trusted
infrastructure, outside application containment. They receive no Mac host
filesystem, Docker administration socket, host account or global firewall
mutation. The kind node itself is the standard privileged Kubernetes-in-Docker
boundary. A compromised node or Docker/host root remains outside the guarantee.

Application pods retain the restricted Pod Security profile. SPIRE Workload API
is injected only into admitted Envoy containers through the read-only SPIFFE
CSI volume. The restriction custodian's channel uses an exact statically bound
PV/PVC; its ledger is a different volume never mounted into readers. Kernel UID
ACLs distinguish identity's restriction duty from read-only application/authz
duties. Shared numeric application UIDs would break that distinction, so the
local roles use identity21011, main21012, help21013, proxy21002, authz21003,
custodian21000 and channel group21999. These are process IDs inside containers,
not newly created workstation accounts.

The separately running host-help Docker group uses pinned application/Envoy
images admitted by its supervisor, a separately registered one-use join-token
SPIRE agent and Unix UID workload attestation in its isolated shared PID
namespace. Only Envoy receives the Workload API socket; neither application nor
browser receives the bootstrap token or SVID keys. Host image lineage admission
is an operator/supervisor binding, distinct from the Kubernetes attestor's image
selectors. This local binding was explicitly selected by the coordinator; it
does not establish production-grade host attestation.

Primary implementation references: [kind release](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0),
[Calico kind installation](https://docs.tigera.io/calico/latest/getting-started/kubernetes/kind),
[SPIRE Kubernetes quickstart](https://spiffe.io/docs/latest/try/getting-started-k8s/),
[SPIRE1.16 Kubernetes workload attestor](https://github.com/spiffe/spire/blob/v1.16.0/doc/plugin_agent_workloadattestor_k8s.md),
[SPIFFE CSI](https://github.com/spiffe/spiffe-csi).
These references describe interfaces and infrastructure duties; only retained
live observations can qualify this candidate's actual enforcement.

The actual runtime probe later showed an enabled IPv6 interface and link-local
address despite single-stack IPv4 Kubernetes. Single-stack addressing was
therefore insufficient evidence. The pinned Calico CNI template now appends
`tuning` with only `net.ipv6.conf.all.disable_ipv6=1` and
`net.ipv6.conf.default.disable_ipv6=1`. The tuning binary was observed on the
named node; these sysctls execute after CNI enters each new pod's network
namespace. No Mac or node-global sysctl/firewall setting is changed. Existing
namespaces must be recreated under the named resource lease and checked for
actual disabled interface flags/no IPv6 addresses; this source change alone is
not credited as runtime rejection. PVC state remains intact across that
recreation. See the [CNI tuning implementation](https://github.com/containernetworking/plugins/blob/v1.9.0/plugins/meta/tuning/tuning.go)
for namespace/allowlist semantics; the installed Calico-packaged binary reported
version3.33.0 and the actual post-creation interface observation is authoritative.
