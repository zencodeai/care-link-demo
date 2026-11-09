"""Private application routes; mesh identity still authorizes every operation."""

from .model import document


def manifests() -> list[dict[str, object]]:
    dns = {
        "to": [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                },
                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
            }
        ],
        "ports": [{"protocol": protocol, "port": 53} for protocol in ("UDP", "TCP")],
    }
    output: list[dict[str, object]] = []
    for role in ("main", "identity"):
        egress = [dns]
        if role == "main":
            egress.append(
                {
                    "to": [{"podSelector": {"matchLabels": {"app": "identity"}}}],
                    "ports": [{"protocol": "TCP", "port": 8443}],
                }
            )
        else:
            egress.extend(
                [
                    {
                        "to": [{"podSelector": {"matchLabels": {"app": "keycloak"}}}],
                        "ports": [{"protocol": "TCP", "port": port} for port in (8443, 20443)],
                    },
                    {
                        "to": [{"podSelector": {"matchLabels": {"app": "postgres"}}}],
                        "ports": [{"protocol": "TCP", "port": 5432}],
                    },
                ]
            )
        output.append(
            document(
                "NetworkPolicy",
                role + "-private-routes",
                api="networking.k8s.io/v1",
                spec={
                    "podSelector": {"matchLabels": {"app": role}},
                    "policyTypes": ["Ingress", "Egress"],
                    "egress": egress,
                    "ingress": [
                        {"ports": [{"protocol": "TCP", "port": 8444 if role == "main" else 8443}]}
                    ],
                },
            )
        )
    return output
