"""SPIFFE CSI mount only; Kubernetes application pods need no direct hostPath."""

from .model import LABELS, LabInputs
from .spire import SOCKET_PATH, TRUST_NAMESPACE


def manifests(inputs: LabInputs) -> list[dict[str, object]]:
    plugin = "/var/lib/kubelet/plugins/csi.spiffe.io"
    output: list[dict[str, object]] = [
        {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "CSIDriver",
            "metadata": {"name": "csi.spiffe.io", "labels": LABELS},
            "spec": {
                "attachRequired": False,
                "podInfoOnMount": True,
                "fsGroupPolicy": "None",
                "volumeLifecycleModes": ["Ephemeral"],
            },
        }
    ]
    output.append(
        {
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "metadata": {"name": "spiffe-csi", "namespace": TRUST_NAMESPACE, "labels": LABELS},
            "spec": {
                "selector": {"matchLabels": {"app": "spiffe-csi"}},
                "template": {
                    "metadata": {"labels": LABELS | {"app": "spiffe-csi"}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "tolerations": [{"operator": "Exists"}],
                        "containers": [
                            {
                                "name": "driver",
                                "image": inputs.image("spire_csi"),
                                "args": [
                                    "-workload-api-socket-dir",
                                    "/spire-agent-socket",
                                    "-csi-socket-path",
                                    "/spiffe-csi/csi.sock",
                                ],
                                "env": [
                                    {
                                        "name": "MY_NODE_NAME",
                                        "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}},
                                    }
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "agent",
                                        "mountPath": "/spire-agent-socket",
                                        "readOnly": True,
                                    },
                                    {"name": "plugin", "mountPath": "/spiffe-csi"},
                                    {
                                        "name": "pods",
                                        "mountPath": "/var/lib/kubelet/pods",
                                        "mountPropagation": "Bidirectional",
                                    },
                                ],
                                "securityContext": {
                                    "privileged": True,
                                    "readOnlyRootFilesystem": True,
                                },
                                "resources": {"limits": {"cpu": "250m", "memory": "128Mi"}},
                            },
                            {
                                "name": "registrar",
                                "image": inputs.image("csi_registrar"),
                                "args": [
                                    "-csi-address",
                                    "/spiffe-csi/csi.sock",
                                    "-kubelet-registration-path",
                                    plugin + "/csi.sock",
                                ],
                                "volumeMounts": [
                                    {"name": "plugin", "mountPath": "/spiffe-csi"},
                                    {"name": "registration", "mountPath": "/registration"},
                                ],
                                "resources": {"limits": {"cpu": "100m", "memory": "64Mi"}},
                            },
                        ],
                        "volumes": [
                            {"name": name, "hostPath": {"path": path, "type": "DirectoryOrCreate"}}
                            for name, path in [
                                ("agent", SOCKET_PATH),
                                ("plugin", plugin),
                                ("pods", "/var/lib/kubelet/pods"),
                                ("registration", "/var/lib/kubelet/plugins_registry"),
                            ]
                        ],
                    },
                },
            },
        }
    )
    return output
