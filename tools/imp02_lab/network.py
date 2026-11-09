"""Real CNI active-control fixtures, labelled separately from product services."""

from typing import cast

from .model import LABELS, NAMESPACE, LabInputs, container_security, document, pod_security

LISTENER = """import socket,threading,time
def serve(port):
 s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 s.bind(('0.0.0.0',port));s.listen(16)
 while True:
  c,_=s.accept()
  with c:c.sendall(b'IMP02_ACTIVE_CONTROL\\n')
for p in [8443,5432,8011,1234,18443]:
 threading.Thread(target=serve,args=(p,),daemon=True).start()
while True:time.sleep(60)
"""


def _peer(app: str) -> dict[str, object]:
    return {"podSelector": {"matchLabels": {"app": app}}}


def _rule(
    app: str, *, ingress: list[object] | None = None, egress: list[object] | None = None
) -> dict[str, object]:
    return document(
        "NetworkPolicy",
        app + "-routes",
        api="networking.k8s.io/v1",
        spec={
            "podSelector": {"matchLabels": {"app": app}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": ingress or [],
            "egress": egress or [],
        },
    )


def manifests(inputs: LabInputs, host_probe_ip: str) -> list[dict[str, object]]:
    import ipaddress

    address = ipaddress.ip_address(host_probe_ip)
    if address.version != 4 or not address.is_private:
        raise ValueError("explicit isolated active control IPv4 required")
    output = [
        document(
            "NetworkPolicy",
            "default-deny",
            api="networking.k8s.io/v1",
            spec={
                "podSelector": {},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [],
                "egress": [],
            },
        )
    ]
    for app in ("runtime-probe", "allowed-probe", "broker-fixture", "denied-fixture"):
        listener = app.endswith("fixture")
        output.append(
            document(
                "Pod",
                app,
                spec={
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "securityContext": pod_security(),
                    "containers": [
                        {
                            "name": "probe",
                            "image": inputs.image("python"),
                            "command": [
                                "python",
                                "-u",
                                "-c",
                                LISTENER if listener else "import time;time.sleep(86400)",
                            ],
                            "securityContext": container_security(),
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "24Mi"},
                                "limits": {"cpu": "100m", "memory": "64Mi"},
                            },
                        }
                    ],
                },
            )
        )
        metadata = cast(dict[str, object], output[-1]["metadata"])
        metadata["labels"] = LABELS | {"app": app, "care-link.fixture": "network-control"}
    output.extend(
        [
            _rule(
                "runtime-probe",
                egress=[
                    {"to": [_peer("broker-fixture")], "ports": [{"protocol": "TCP", "port": 8443}]}
                ],
            ),
            _rule(
                "allowed-probe",
                egress=[
                    {
                        "to": [_peer("broker-fixture"), _peer("denied-fixture")],
                        "ports": [
                            {"protocol": "TCP", "port": p} for p in (8443, 5432, 8011, 1234, 18443)
                        ],
                    },
                    {
                        "to": [{"ipBlock": {"cidr": host_probe_ip + "/32"}}],
                        "ports": [{"protocol": "TCP", "port": 18443}],
                    },
                ],
            ),
            _rule(
                "broker-fixture",
                ingress=[
                    {
                        "from": [_peer("allowed-probe"), _peer("runtime-probe")],
                        "ports": [{"protocol": "TCP", "port": 8443}],
                    }
                ],
            ),
            _rule(
                "denied-fixture",
                ingress=[
                    {
                        "from": [_peer("allowed-probe")],
                        "ports": [
                            {"protocol": "TCP", "port": p} for p in (8443, 5432, 8011, 1234, 18443)
                        ],
                    }
                ],
            ),
        ]
    )
    return output


def namespace() -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": NAMESPACE,
            "labels": LABELS | {"pod-security.kubernetes.io/enforce": "restricted"},
        },
    }
