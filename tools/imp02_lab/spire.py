"""Pinned SPIRE PSAT/Kubernetes attestation with a separate trusted namespace."""

from .model import CLUSTER, LABELS, NAMESPACE, SESSION, LabInputs

TRUST_NAMESPACE = NAMESPACE + "-trust"
SOCKET_PATH = "/run/care-link/" + SESSION + "/spire"


def _doc(kind: str, name: str, *, api: str = "v1", **fields: object) -> dict[str, object]:
    return {
        "apiVersion": api,
        "kind": kind,
        "metadata": {"name": name, "namespace": TRUST_NAMESPACE, "labels": LABELS},
        **fields,
    }


def configurations() -> dict[str, str]:
    server = f'''server {{
  bind_address = "0.0.0.0"
  bind_port = "8081"
  socket_path = "/run/spire/data/api.sock"
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  log_level = "WARN"
  default_x509_svid_ttl = "300s"
  agent_ttl = "1h"
}}
plugins {{
  DataStore "sql" {{ plugin_data {{
    database_type = "sqlite3"
    connection_string = "/run/spire/data/server.sqlite"
  }} }}
  KeyManager "disk" {{ plugin_data {{ keys_path = "/run/spire/data/keys.json" }} }}
  NodeAttestor "k8s_psat" {{ plugin_data {{ clusters = {{
    "{CLUSTER}" = {{ service_account_allow_list = ["{TRUST_NAMESPACE}:spire-agent"] }}
  }} }} }}
  NodeAttestor "join_token" {{ plugin_data {{ }} }}
}}
health_checks {{ listener_enabled = true bind_address = "0.0.0.0" bind_port = "8080" }}
'''
    agent = f'''agent {{
  data_dir = "/run/spire/data"
  log_level = "WARN"
  server_address = "spire-server.{TRUST_NAMESPACE}.svc.cluster.local"
  server_port = "8081"
  socket_path = "/run/spire/sockets/agent.sock"
  trust_bundle_path = "/run/spire/bundle/bundle.crt"
  trust_domain = "care-link.demo"
}}
plugins {{
  NodeAttestor "k8s_psat" {{ plugin_data {{ cluster = "{CLUSTER}" }} }}
  KeyManager "memory" {{ plugin_data {{ }} }}
  WorkloadAttestor "k8s" {{ plugin_data {{
    node_name_env = "MY_NODE_NAME"
    kubelet_ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    skip_kubelet_verification = false
  }} }}
  WorkloadAttestor "unix" {{ plugin_data {{ }} }}
}}
health_checks {{ listener_enabled = true bind_address = "0.0.0.0" bind_port = "8080" }}
'''
    return {"server.conf": server, "agent.conf": agent}


def manifests(inputs: LabInputs) -> list[dict[str, object]]:
    configs = configurations()
    output: list[dict[str, object]] = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": TRUST_NAMESPACE,
                "labels": LABELS | {"pod-security.kubernetes.io/enforce": "privileged"},
            },
        },
        _doc("ConfigMap", "spire-config", data=configs),
        _doc("ConfigMap", "spire-bundle", data={"bundle.crt": ""}),
        _doc(
            "PersistentVolumeClaim",
            "spire-server-data",
            spec={
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "standard",
                "resources": {"requests": {"storage": "1Gi"}},
            },
        ),
        _doc("ServiceAccount", "spire-server"),
        _doc("ServiceAccount", "spire-agent"),
    ]
    roles = {
        "spire-server": [
            {"apiGroups": [""], "resources": ["pods", "nodes"], "verbs": ["get"]},
            {
                "apiGroups": ["authentication.k8s.io"],
                "resources": ["tokenreviews"],
                "verbs": ["create"],
            },
        ],
        "spire-agent": [
            {"apiGroups": [""], "resources": ["nodes", "nodes/proxy", "pods"], "verbs": ["get"]}
        ],
    }
    for name, rules in roles.items():
        output.extend(
            [
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRole",
                    "metadata": {"name": CLUSTER + "-" + name, "labels": LABELS},
                    "rules": rules,
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRoleBinding",
                    "metadata": {"name": CLUSTER + "-" + name, "labels": LABELS},
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole",
                        "name": CLUSTER + "-" + name,
                    },
                    "subjects": [
                        {"kind": "ServiceAccount", "name": name, "namespace": TRUST_NAMESPACE}
                    ],
                },
            ]
        )
    output.extend(
        [
            _doc(
                "Deployment",
                "spire-server",
                api="apps/v1",
                spec={
                    "replicas": 1,
                    "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": {"app": "spire-server"}},
                    "template": {
                        "metadata": {"labels": LABELS | {"app": "spire-server"}},
                        "spec": {
                            "serviceAccountName": "spire-server",
                            "securityContext": {
                                "runAsUser": 1000,
                                "runAsGroup": 1000,
                                "fsGroup": 1000,
                            },
                            "containers": [
                                {
                                    "name": "spire-server",
                                    "image": inputs.image("spire_server"),
                                    "args": ["-config", "/run/spire/config/server.conf"],
                                    "resources": {"limits": {"cpu": "500m", "memory": "256Mi"}},
                                    "volumeMounts": [
                                        {
                                            "name": "config",
                                            "mountPath": "/run/spire/config",
                                            "readOnly": True,
                                        },
                                        {"name": "data", "mountPath": "/run/spire/data"},
                                    ],
                                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080}},
                                }
                            ],
                            "volumes": [
                                {"name": "config", "configMap": {"name": "spire-config"}},
                                {
                                    "name": "data",
                                    "persistentVolumeClaim": {"claimName": "spire-server-data"},
                                },
                            ],
                        },
                    },
                },
            ),
            _doc(
                "Service",
                "spire-server",
                spec={
                    "selector": {"app": "spire-server"},
                    "type": "NodePort",
                    "ports": [
                        {"name": "attestation", "port": 8081, "targetPort": 8081, "nodePort": 30881}
                    ],
                },
            ),
            _doc(
                "DaemonSet",
                "spire-agent",
                api="apps/v1",
                spec={
                    "selector": {"matchLabels": {"app": "spire-agent"}},
                    "template": {
                        "metadata": {"labels": LABELS | {"app": "spire-agent"}},
                        "spec": {
                            "serviceAccountName": "spire-agent",
                            "hostPID": True,
                            "hostNetwork": True,
                            "dnsPolicy": "ClusterFirstWithHostNet",
                            "tolerations": [{"operator": "Exists"}],
                            "containers": [
                                {
                                    "name": "spire-agent",
                                    "image": inputs.image("spire_agent"),
                                    "args": ["-config", "/run/spire/config/agent.conf"],
                                    "env": [
                                        {
                                            "name": "MY_NODE_NAME",
                                            "valueFrom": {
                                                "fieldRef": {"fieldPath": "status.hostIP"}
                                            },
                                        }
                                    ],
                                    "resources": {"limits": {"cpu": "500m", "memory": "256Mi"}},
                                    "volumeMounts": [
                                        {
                                            "name": "config",
                                            "mountPath": "/run/spire/config",
                                            "readOnly": True,
                                        },
                                        {"name": "data", "mountPath": "/run/spire/data"},
                                        {
                                            "name": "bundle",
                                            "mountPath": "/run/spire/bundle",
                                            "readOnly": True,
                                        },
                                        {"name": "socket", "mountPath": "/run/spire/sockets"},
                                        {
                                            "name": "token",
                                            "mountPath": "/var/run/secrets/tokens",
                                            "readOnly": True,
                                        },
                                    ],
                                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080}},
                                }
                            ],
                            "volumes": [
                                {"name": "config", "configMap": {"name": "spire-config"}},
                                {"name": "bundle", "configMap": {"name": "spire-bundle"}},
                                {
                                    "name": "socket",
                                    "hostPath": {"path": SOCKET_PATH, "type": "DirectoryOrCreate"},
                                },
                                {"name": "data", "emptyDir": {}},
                                {
                                    "name": "token",
                                    "projected": {
                                        "sources": [
                                            {
                                                "serviceAccountToken": {
                                                    "path": "spire-agent",
                                                    "audience": "spire-server",
                                                    "expirationSeconds": 600,
                                                }
                                            }
                                        ]
                                    },
                                },
                            ],
                        },
                    },
                },
            ),
        ]
    )
    return output
