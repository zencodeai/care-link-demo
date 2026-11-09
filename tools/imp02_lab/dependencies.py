"""TLS PostgreSQL and fixed-hostname Keycloak, with private generated secrets."""

from .model import LABELS, LabInputs, container_security, document, pod_security


def _password(name: str) -> dict[str, object]:
    return {"valueFrom": {"secretKeyRef": {"name": "imp02-passwords", "key": name}}}


def _service(name: str, port: int, target: int, node_port: int | None = None) -> dict[str, object]:
    endpoint = {"name": "tls", "port": port, "targetPort": target}
    if node_port is not None:
        endpoint["nodePort"] = node_port
    return document(
        "Service",
        name,
        spec={
            "selector": {"app": name},
            "ports": [endpoint],
            "type": "NodePort" if node_port else "ClusterIP",
        },
    )


def manifests(inputs: LabInputs) -> list[dict[str, object]]:
    postgres = {
        "name": "postgres",
        "image": inputs.image("postgres"),
        "args": [
            "postgres",
            "-c",
            "ssl=on",
            "-c",
            "ssl_cert_file=/cert/postgres.crt",
            "-c",
            "ssl_key_file=/cert/postgres.key",
            "-c",
            "ssl_min_protocol_version=TLSv1.3",
        ],
        "env": [
            {"name": "POSTGRES_PASSWORD", **_password("postgres_password")},
            {"name": "PGDATA", "value": "/var/lib/postgresql/18/docker"},
        ],
        "securityContext": container_security(),
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "512Mi"},
        },
        "volumeMounts": [
            {"name": "data", "mountPath": "/var/lib/postgresql"},
            {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108 - bounded per-pod tmpfs
            {"name": "socket", "mountPath": "/var/run/postgresql"},
            {"name": "cert", "mountPath": "/cert", "readOnly": True},
        ],
        "readinessProbe": {
            "exec": {"command": ["pg_isready", "-U", "postgres"]},
            "initialDelaySeconds": 3,
            "periodSeconds": 3,
        },
    }
    keycloak = {
        "name": "keycloak",
        "image": inputs.image("keycloak_runtime"),
        "imagePullPolicy": "Never",
        "args": [
            "start",
            "--optimized",
            "--hostname=https://id.localhost:20443",
            "--hostname-strict=true",
            "--http-enabled=false",
            "--https-certificate-file=/cert/keycloak.crt",
            "--https-certificate-key-file=/cert/keycloak.key",
        ],
        "env": [
            {"name": "KC_DB", "value": "postgres"},
            {
                "name": "KC_DB_URL",
                "value": "jdbc:postgresql://postgres:5432/keycloak?sslmode=verify-full&sslrootcert=/cert/ca.crt",
            },
            {"name": "KC_DB_USERNAME", "value": "keycloak"},
            {"name": "KC_DB_PASSWORD", **_password("keycloak_db_password")},
            {"name": "KC_BOOTSTRAP_ADMIN_USERNAME", "value": "imp02-owner-admin"},
            {"name": "KC_BOOTSTRAP_ADMIN_PASSWORD", **_password("keycloak_admin_password")},
        ],
        "securityContext": container_security(),
        "resources": {
            "requests": {"cpu": "250m", "memory": "384Mi"},
            "limits": {"cpu": "2", "memory": "1024Mi"},
        },
        "volumeMounts": [
            {"name": "data", "mountPath": "/opt/keycloak/data"},
            {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108 - bounded per-pod tmpfs
            {"name": "cert", "mountPath": "/cert", "readOnly": True},
        ],
        "readinessProbe": {
            "tcpSocket": {"port": 8443},
            "initialDelaySeconds": 5,
            "periodSeconds": 3,
        },
    }
    output: list[dict[str, object]] = [
        document(
            "PersistentVolumeClaim",
            "postgres-data",
            spec={
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "standard",
                "resources": {"requests": {"storage": "2Gi"}},
            },
        )
    ]
    for name, uid, container in [("postgres", 999, postgres), ("keycloak", 1000, keycloak)]:
        output.append(
            document(
                "Deployment",
                name,
                api="apps/v1",
                spec={
                    "replicas": 1,
                    "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": LABELS | {"app": name}},
                        "spec": {
                            "automountServiceAccountToken": False,
                            "securityContext": pod_security(uid) | {"fsGroup": uid},
                            "containers": [container],
                            "volumes": [
                                (
                                    {
                                        "name": "data",
                                        "persistentVolumeClaim": {"claimName": "postgres-data"},
                                    }
                                    if name == "postgres"
                                    else {"name": "data", "emptyDir": {"sizeLimit": "256Mi"}}
                                ),
                                {
                                    "name": "tmp",
                                    "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"},
                                },
                                {"name": "socket", "emptyDir": {}},
                                {
                                    "name": "cert",
                                    "secret": {
                                        "secretName": "imp02-pki",
                                        "defaultMode": 0o640,
                                        "items": [
                                            {"key": item, "path": item}
                                            for item in (f"{name}.crt", f"{name}.key", "ca.crt")
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                },
            )
        )
    postgres["volumeMounts"].append(
        {"name": "init", "mountPath": "/docker-entrypoint-initdb.d", "readOnly": True}
    )
    volumes = output[1]["spec"]["template"]["spec"]["volumes"]
    volumes.append(
        {"name": "init", "secret": {"secretName": "imp02-postgres-init", "defaultMode": 0o640}}
    )
    output.extend([_service("postgres", 5432, 5432), _service("keycloak", 20443, 8443, 30443)])
    output.extend(
        [
            document(
                "NetworkPolicy",
                "postgres-routes",
                api="networking.k8s.io/v1",
                spec={
                    "podSelector": {"matchLabels": {"app": "postgres"}},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [
                        {
                            "from": [
                                {"podSelector": {"matchLabels": {"app": app}}}
                                for app in ("identity", "keycloak")
                            ],
                            "ports": [{"protocol": "TCP", "port": 5432}],
                        }
                    ],
                    "egress": [],
                },
            ),
            document(
                "NetworkPolicy",
                "keycloak-routes",
                api="networking.k8s.io/v1",
                spec={
                    "podSelector": {"matchLabels": {"app": "keycloak"}},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [{"ports": [{"protocol": "TCP", "port": 8443}]}],
                    "egress": [
                        {
                            "to": [{"podSelector": {"matchLabels": {"app": "postgres"}}}],
                            "ports": [{"protocol": "TCP", "port": 5432}],
                        },
                        {
                            "to": [
                                {
                                    "namespaceSelector": {
                                        "matchLabels": {
                                            "kubernetes.io/metadata.name": "kube-system"
                                        }
                                    },
                                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                                }
                            ],
                            "ports": [
                                {"protocol": protocol, "port": 53} for protocol in ("UDP", "TCP")
                            ],
                        },
                    ],
                },
            ),
        ]
    )
    return output
