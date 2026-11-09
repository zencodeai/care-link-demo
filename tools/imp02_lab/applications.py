"""Restricted application pods with separately owned native socket/config volumes."""

from .model import CLUSTER, LABELS, SESSION, LabInputs, container_security, document
from .spire import TRUST_NAMESPACE

BASE = "/var/lib/care-link/" + SESSION
ROLE_UID = {"identity": 21011, "main": 21012}


def locations() -> list[tuple[str, str, int, int, int]]:
    values = [
        ("fence-channel", "fence/channel", 21000, 21999, 0o710),
        ("fence-ledger", "fence/ledger", 21000, 21000, 0o700),
        ("fence-config", "config/fence", 21000, 21000, 0o700),
    ]
    for role, uid in ROLE_UID.items():
        values.extend(
            [
                (role + "-backend", f"sockets/{role}/backend", uid, 21002, 0o710),
                (role + "-outbound", f"sockets/{role}/outbound", 21002, uid, 0o710),
                (role + "-application-config", f"config/{role}/application", uid, uid, 0o700),
                (role + "-proxy-config", f"config/{role}/proxy", 21002, 21002, 0o700),
                (role + "-admin", f"admin/{role}", 21002, 21002, 0o700),
            ]
        )
    values.extend(
        [
            ("identity-authorization", "sockets/identity/authorization", 21003, 21002, 0o710),
            ("identity-authorization-config", "config/identity/authorization", 21003, 21003, 0o700),
        ]
    )
    return values


def volumes() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for name, path, _uid, _gid, _mode in locations():
        volume_name = CLUSTER + "-" + name
        output.extend(
            [
                {
                    "apiVersion": "v1",
                    "kind": "PersistentVolume",
                    "metadata": {"name": volume_name, "labels": LABELS},
                    "spec": {
                        "capacity": {"storage": "16Mi"},
                        "accessModes": ["ReadWriteMany"],
                        "persistentVolumeReclaimPolicy": "Retain",
                        "storageClassName": "",
                        "hostPath": {"path": BASE + "/" + path, "type": "Directory"},
                        "nodeAffinity": {
                            "required": {
                                "nodeSelectorTerms": [
                                    {
                                        "matchExpressions": [
                                            {
                                                "key": "kubernetes.io/hostname",
                                                "operator": "In",
                                                "values": [CLUSTER + "-control-plane"],
                                            }
                                        ]
                                    }
                                ]
                            }
                        },
                    },
                },
                document(
                    "PersistentVolumeClaim",
                    name,
                    spec={
                        "volumeName": volume_name,
                        "storageClassName": "",
                        "accessModes": ["ReadWriteMany"],
                        "resources": {"requests": {"storage": "16Mi"}},
                    },
                ),
            ]
        )
    return output


def seed(inputs: LabInputs) -> dict[str, object]:
    # Only this trusted infrastructure job sees the node directory. Application
    # pods receive the exact PVC subdirectory, never the writable common parent.
    sources = [("imp02-fence-config", "config/fence", 21000)]
    for role, uid in ROLE_UID.items():
        sources.extend(
            [
                (f"imp02-{role}-config", f"config/{role}/application", uid),
                (f"imp02-{role}-proxy", f"config/{role}/proxy", 21002),
            ]
        )
    sources.append(("imp02-identity-authorization", "config/identity/authorization", 21003))
    script = "\n".join(
        [
            "import os,pathlib,shutil",
            "base=pathlib.Path('/seed')",
            f"locations={locations()!r}",
            "for name,relative,uid,gid,mode in locations:",
            " p=base/relative;p.mkdir(parents=True,exist_ok=True)",
            " os.chown(p,uid,gid);p.chmod(mode)",
            f"sources={sources!r}",
            "for name,relative,uid in sources:",
            " for source in pathlib.Path('/sources',name).iterdir():",
            "  if source.name.startswith('.') or not source.is_file():continue",
            "  target=base/relative/source.name",
            "  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)",
            "  with os.fdopen(fd,'wb') as out:",
            "   out.write(source.read_bytes());out.flush();os.fsync(out.fileno())",
            "  os.chown(target,uid,uid);target.chmod(0o600)",
        ]
    )
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": "imp02-socket-seed", "namespace": TRUST_NAMESPACE, "labels": LABELS},
        "spec": {
            "backoffLimit": 0,
            "template": {
                "metadata": {"labels": LABELS},
                "spec": {
                    "nodeName": CLUSTER + "-control-plane",
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "seed",
                            "image": inputs.image("python"),
                            "command": ["python", "-c", script],
                            "securityContext": {
                                "runAsUser": 0,
                                "allowPrivilegeEscalation": False,
                                "capabilities": {
                                    "drop": ["ALL"],
                                    "add": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
                                },
                            },
                            "volumeMounts": [{"name": "seed", "mountPath": "/seed"}]
                            + [
                                {
                                    "name": "source-" + str(i),
                                    "mountPath": "/sources/" + name,
                                    "readOnly": True,
                                }
                                for i, (name, _relative, _uid) in enumerate(sources)
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "seed", "hostPath": {"path": BASE, "type": "DirectoryOrCreate"}}
                    ]
                    + [
                        {"name": "source-" + str(i), "secret": {"secretName": name}}
                        for i, (name, _relative, _uid) in enumerate(sources)
                    ],
                },
            },
        },
    }


def _mount(volume: str, target: str, readonly: bool = False) -> dict[str, object]:
    return {"name": volume, "mountPath": target, "readOnly": readonly}


def _container(
    inputs: LabInputs, name: str, uid: int, command: list[str], mounts: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "name": name,
        "image": inputs.image("application"),
        "imagePullPolicy": "Never",
        "command": command,
        "securityContext": container_security()
        | {"runAsUser": uid, "runAsGroup": uid, "runAsNonRoot": True},
        "volumeMounts": mounts,
        "resources": {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "1", "memory": "256Mi"},
        },
    }


def manifests(inputs: LabInputs) -> list[dict[str, object]]:
    output = volumes()
    for role, uid in ROLE_UID.items():
        output.append(document("ServiceAccount", role, automountServiceAccountToken=False))
        claims = [
            role + "-backend",
            role + "-outbound",
            role + "-application-config",
            role + "-proxy-config",
            role + "-admin",
        ]
        application = _container(
            inputs,
            "application",
            uid,
            [
                "python",
                "-m",
                "tools.imp02_application",
                "--role",
                role,
                "--config",
                "/config/" + role + ".json",
            ],
            [
                _mount(role + "-backend", "/run/care-link/backend"),
                _mount(role + "-outbound", "/run/care-link/outbound", True),
                _mount(role + "-application-config", "/config", True),
                _mount("fence-channel", "/run/care-link/fence", True),
            ],
        )
        proxy: dict[str, object] = {
            "name": "proxy",
            "image": inputs.image("envoy"),
            "args": ["-c", "/config/envoy.json", "--disable-hot-restart", "--log-level", "warning"],
            "securityContext": container_security()
            | {"runAsUser": 21002, "runAsGroup": 21002, "runAsNonRoot": True},
            "volumeMounts": [
                _mount(role + "-backend", "/run/care-link/backend", True),
                _mount(role + "-outbound", "/run/care-link/outbound"),
                _mount(role + "-proxy-config", "/config", True),
                _mount(role + "-admin", "/run/care-link/admin"),
                _mount("spire", "/run/spire/sockets", True),
            ],
            "resources": {
                "requests": {"cpu": "50m", "memory": "48Mi"},
                "limits": {"cpu": "1", "memory": "192Mi"},
            },
        }
        containers = [application, proxy]
        if role == "identity":
            claims.extend(["identity-authorization", "identity-authorization-config"])
            proxy["volumeMounts"].append(
                _mount("identity-authorization", "/run/care-link/authorization", True)
            )
            containers.append(
                _container(
                    inputs,
                    "authorization",
                    21003,
                    [
                        "python",
                        "-m",
                        "tools.imp02_lab.trust_process",
                        "authorization",
                        "--config",
                        "/config/authorization.json",
                    ],
                    [
                        _mount("identity-authorization", "/run/care-link/authorization"),
                        _mount("identity-authorization-config", "/config", True),
                        _mount("fence-channel", "/run/care-link/fence", True),
                    ],
                )
            )
        claims.append("fence-channel")
        output.append(
            document(
                "Deployment",
                role,
                api="apps/v1",
                spec={
                    "replicas": 1,
                    "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": {"app": role}},
                    "template": {
                        "metadata": {"labels": LABELS | {"app": role}},
                        "spec": {
                            "serviceAccountName": role,
                            "automountServiceAccountToken": False,
                            "securityContext": {
                                "runAsNonRoot": True,
                                "supplementalGroups": [21002, uid, 21999],
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": containers,
                            "volumes": [
                                {"name": name, "persistentVolumeClaim": {"claimName": name}}
                                for name in claims
                            ]
                            + [
                                {
                                    "name": "spire",
                                    "csi": {"driver": "csi.spiffe.io", "readOnly": True},
                                }
                            ],
                        },
                    },
                },
            )
        )
        port, target, nodeport = (18443, 8444, 30441) if role == "main" else (8443, 8443, 30444)
        output.append(
            document(
                "Service",
                role,
                spec={
                    "type": "NodePort",
                    "selector": {"app": role},
                    "ports": [
                        {"name": "tls", "port": port, "targetPort": target, "nodePort": nodeport}
                    ],
                },
            )
        )
    output.append(
        document(
            "Deployment",
            "fence-custodian",
            api="apps/v1",
            spec={
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": "fence-custodian"}},
                "template": {
                    "metadata": {"labels": LABELS | {"app": "fence-custodian"}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "supplementalGroups": [21999],
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            _container(
                                inputs,
                                "custodian",
                                21000,
                                [
                                    "python",
                                    "-m",
                                    "tools.imp02_lab.trust_process",
                                    "fence",
                                    "--config",
                                    "/config/fence.json",
                                ],
                                [
                                    _mount("fence-channel", "/run/care-link/fence"),
                                    _mount("fence-ledger", "/run/care-link/ledger"),
                                    _mount("fence-config", "/config", True),
                                ],
                            )
                        ],
                        "volumes": [
                            {"name": name, "persistentVolumeClaim": {"claimName": name}}
                            for name in ("fence-channel", "fence-ledger", "fence-config")
                        ],
                    },
                },
            },
        )
    )
    return output
