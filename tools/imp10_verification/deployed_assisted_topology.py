"""Independent release custody and protected assisted roles on the owned Kind lease."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from care_link_workload_trust.verification import UUID_PATTERN

from tools.imp02_lab.model import pod_security
from tools.imp03_runtime.config import spiffe
from tools.imp10_runtime.mesh import configurations

from .deployed_fixtures import STATE, Record, encode, secret
from .deployed_roles import (
    APPS,
    ASSETS,
    BACKEND,
    CLUSTER,
    FENCE,
    IMAGE,
    NAMESPACE,
    PROXY,
    SCOPE,
    SPIRE,
    UID,
    k,
    mount,
    network,
    outbound_path,
    part,
    pod,
    ports,
    private_roles,
    resource,
    role_inputs,
    selector,
    trust_config,
)

RELEASE_PVC = "imp10-qualification-release-replay"
RELEASE_OWNER = 23201
ASSISTED = ("core", "data", "inference", "runtime")
BRIDGE_ROLE = "host-inference-bridge"
BRIDGE_ADDRESS = "172.23.255.238"
PYTHON = """
import json, os, runpy, sys, time
from pathlib import Path
from care_link_domain import ManualError
from tools.imp03_runtime.config import load
from tools.imp06_runtime.release_custody import ReleaseDenied
from tools.imp06_runtime.resources import load_knowledge_resources
sys.path.insert(0,'/config')
path = Path('/config/config.json')
cfg = load(path)
observation = json.loads(Path(cfg['role_observation']).read_text())
assert os.geteuid() == cfg['uid']
assert load_knowledge_resources().catalog.digest == observation['catalog_digest']
Path('/state/qualification-ready.json').write_text(json.dumps({
    'role': cfg['role'], 'boot_id': cfg['boot_id'], 'uid': cfg['uid'],
    'catalog_digest': observation['catalog_digest'],
}))
module = runpy.run_path('/config/deployed_assistance.py')
end = time.monotonic() + 600
while True:
    try:
        module['run'](path)
        break
    except (ReleaseDenied, FileNotFoundError):
        if time.monotonic() >= end:
            raise
        time.sleep(.5)
    except ManualError as error:
        if error.code != 'assistance.function_disabled' or time.monotonic() >= end:
            raise
        time.sleep(.5)
"""
SNAPSHOT = ("trust.json", "observation.json", "release.sqlite")


def release_writer() -> None:
    names = k("get", "pod", "-l", "app=" + RELEASE_PVC, "-o", "name")
    if names:
        if names != "pod/" + RELEASE_PVC:
            raise ValueError("Unexpected release writer in the owned namespace")
        return
    container = part(
        "writer",
        RELEASE_OWNER,
        IMAGE,
        [
            "python",
            "-c",
            "from pathlib import Path; from threading import Event; "
            "p=Path('/release/shared'); p.mkdir(mode=0o750,exist_ok=True); "
            "p.chmod(0o750); Path('/release/provider-stops').mkdir(mode=0o750,exist_ok=True); "
            "Event().wait()",
        ],
        [mount("release", "/release")],
    )
    pvc = resource(
        "PersistentVolumeClaim",
        RELEASE_PVC,
        spec={
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "standard",
            "resources": {"requests": {"storage": "10Mi"}},
        },
    )
    writer = resource(
        "Pod",
        RELEASE_PVC,
        spec={
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "securityContext": {**pod_security(RELEASE_OWNER), "fsGroup": PROXY},
            "containers": [container],
            "volumes": [
                {
                    "name": "release",
                    "persistentVolumeClaim": {"claimName": RELEASE_PVC},
                }
            ],
        },
    )
    writer["metadata"]["labels"]["app"] = RELEASE_PVC
    k("create", "-f", "-", payload={"apiVersion": "v1", "kind": "List", "items": [pvc, writer]})
    k("wait", "--for=condition=Ready", f"pod/{RELEASE_PVC}", "--timeout=60s", timeout=65)


def publish_release(shared: Path) -> None:
    payload = {name: base64.b64encode((shared / name).read_bytes()).decode() for name in SNAPSHOT}
    code = """
import base64, json, os, sys
from pathlib import Path
directory = Path('/release/shared')
values = json.load(sys.stdin)
assert set(values) == {'trust.json','observation.json','release.sqlite'}
for name in ('trust.json','observation.json','release.sqlite'):
    blob = base64.b64decode(values[name],validate=True)
    assert 1 <= len(blob) <= 2 * 1024 * 1024
    dest = directory / name
    if name != 'release.sqlite' and dest.exists():
        assert dest.read_bytes() == blob
        continue
    candidate = directory / ('.' + name + '.incoming')
    with candidate.open('xb') as stream:
        candidate.chmod(0o640)
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    candidate.replace(dest)
"""
    command = [
        "kubectl",
        "--kubeconfig",
        str(ASSETS / "kubeconfig"),
        "--context",
        "kind-" + CLUSTER,
        "--namespace",
        NAMESPACE,
        "exec",
        "-i",
        RELEASE_PVC,
        "--",
        "python",
        "-c",
        code,
    ]
    proc = subprocess.run(  # noqa: S603 - scoped writer and fixed command
        command,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode:
        raise RuntimeError("Exact owned release writer rejected signed snapshot")


def _sources() -> dict[str, bytes]:
    files = {
        name: Path(__file__).with_name(name).read_bytes()
        for name in ("deployed_assistance.py", "deployed_release.py")
    }
    files["deployed_assistance.py"] = files["deployed_assistance.py"].replace(
        b"from .deployed_release import", b"from deployed_release import"
    )
    return files


def _actor_event_stream(configuration: Record) -> None:
    """Keep authenticated SSE alive while it emits current-authority observations."""
    [browser] = [
        listener
        for listener in configuration["static_resources"]["listeners"]
        if listener["name"] == "browser_tls"
    ]
    manager = browser["filter_chains"][0]["filters"][0]["typed_config"]
    [host] = manager["route_config"]["virtual_hosts"]
    default = host["routes"][-1]
    host["routes"].insert(
        -1,
        {
            **default,
            "match": {
                "safe_regex": {
                    "google_re2": {},
                    "regex": "^/v1/sessions/" + UUID_PATTERN + "/events$",
                },
                "headers": [{"name": ":method", "string_match": {"exact": "GET"}}],
            },
            "route": {**default["route"], "timeout": "0s", "idle_timeout": "15s"},
        },
    )


def _mesh() -> Record:
    binding = private_roles()
    roles = binding["roles"]
    binding["features"]["assisted"] = True
    for name in (*APPS, "inference"):
        if name == "inference":
            roles[name] = {
                **roles["data"],
                "dial_address": f"inference.{NAMESPACE}.svc.cluster.local",
                "outbound": {
                    "data": outbound_path("data"),
                    BRIDGE_ROLE: outbound_path(BRIDGE_ROLE),
                },
            }
        roles[name]["spire_socket"] = SPIRE
    roles["core"]["outbound"]["inference"] = outbound_path("inference")
    roles["core"]["dial_address"] = k("get", "service", "core", "-o", "jsonpath={.spec.clusterIP}")
    roles["runtime"] = {"spire_socket": SPIRE, "outbound": {"core": outbound_path("core")}}
    roles[BRIDGE_ROLE] = {
        **roles["identity"],
        "dial_address": BRIDGE_ADDRESS,
        "outbound": {},
    }
    rendered = configurations(binding)
    _actor_event_stream(rendered["core-envoy.json"])
    return rendered


def _configuration(
    role: str, settings: Record, boots: dict[str, str], observation: bytes
) -> dict[str, bytes]:
    if role in {"core", "data"}:
        files = role_inputs(role, settings, "unused")
        cfg = json.loads(files["config.json"])
    else:
        files = {}
        cfg = {
            "session": "imp10-protected",
            "role": role,
            "uid": UID.get(role, 23121 if role == "runtime" else 23120),
            "proxy_uid": PROXY,
            "fence_uid": FENCE,
            "fence_socket": "/sockets/fence/owned/fence.sock",
            "backend_socket": BACKEND,
        }
    files.update(_sources(), **{"release-observation.json": observation})
    cfg.update(
        release_owner=RELEASE_OWNER,
        shared_release="/release/shared",
        role_observation="/config/release-observation.json",
        boot_id=boots[role],
    )
    if role == "core":
        # The fixed broker coordinator uses this exact logical authority.
        cfg["outbound"]["data"]["origin"] = "https://data:8443"
        cfg["inference_socket"] = outbound_path("inference")
    elif role == "data":
        cfg.update(
            stop_receipts="/release/provider-stops",
            stop_public_key="/config/host-stop.pub",
            stop_issuer="imp10-008-host-stop",
            stop_owner_uid=RELEASE_OWNER,
            bridge_generation=boots[BRIDGE_ROLE],
        )
        files["host-stop.pub"] = (STATE / "host-stop.pub").read_bytes()
    elif role == "inference":
        cfg.update(data_socket=outbound_path("data"), bridge_socket=outbound_path(BRIDGE_ROLE))
    else:
        cfg["core_socket"] = outbound_path("core")
    files["config.json"] = encode(cfg)
    return files


def _ready_tree(role: str, spec: Record) -> Record:
    app = next(c for c in spec["containers"] if c["name"] == "app")
    app["command"] = ["python", "-c", PYTHON]
    app["volumeMounts"].append(mount("release", "/release", readonly=True))
    spec["volumes"].append(
        {
            "name": "release",
            "persistentVolumeClaim": {"claimName": RELEASE_PVC, "readOnly": True},
        }
    )
    if role == "runtime":
        for field in ("initContainers", "containers", "volumes"):
            spec[field] = [
                item
                for item in spec[field]
                if not any(word in item["name"] for word in ("authorization", "fence", "trust"))
            ]
        for item in [*spec["containers"], *spec["initContainers"]]:
            item["volumeMounts"] = [
                m
                for m in item["volumeMounts"]
                if m["name"] not in {"authorization", "fence", "trust"}
            ]
        app.pop("readinessProbe", None)
        next(c for c in spec["containers"] if c["name"] == "proxy").pop("ports", None)
    return spec


def _deployment(role: str, boot: str) -> Record:
    custom = role in {"runtime", "inference"}
    if custom:
        UID[role] = 23121 if role == "runtime" else 23120
    try:
        spec = _ready_tree(role, pod(role))
    finally:
        if custom:
            UID.pop(role)
    labels = {"app": role, "care-link.session": SCOPE}
    return resource(
        "Deployment",
        role,
        api="apps/v1",
        spec={
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": role}},
            "template": {
                "metadata": {
                    "labels": labels,
                    "annotations": {"care-link.demo/qualification-boot": boot},
                },
                "spec": spec,
            },
        },
    )


def _policy(role: str) -> Record:
    if role in {"core", "data"}:
        existing = network(role)
        if role == "core":
            existing["spec"]["ingress"][0]["from"].append(selector("runtime"))
            existing["spec"]["egress"].append({"to": [selector("inference")], "ports": ports(8443)})
        else:
            existing["spec"]["ingress"][0]["from"].append(selector("inference"))
        return existing
    private_peer = "runtime" if role == "runtime" else "inference"
    ingress = [] if role == "runtime" else [{"from": [selector("core")], "ports": ports(8443)}]
    egress = [{"to": [selector("core" if role == "runtime" else "data")], "ports": ports(8443)}]
    if role == "inference":
        egress.extend(
            [
                {"to": [{"ipBlock": {"cidr": BRIDGE_ADDRESS + "/32"}}], "ports": ports(8443)},
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                            },
                            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                        }
                    ],
                    "ports": [{"protocol": p, "port": 53} for p in ("UDP", "TCP")],
                },
            ]
        )
    return resource(
        "NetworkPolicy",
        private_peer + "-mesh",
        api="networking.k8s.io/v1",
        spec={
            "podSelector": selector(private_peer)["podSelector"],
            "policyTypes": ["Ingress", "Egress"],
            "ingress": ingress,
            "egress": egress,
        },
    )


def rollout(
    settings: Record,
    boots: dict[str, str],
    observation: bytes,
    *,
    existing_roles: bool = True,
    new_roles: bool = True,
    replace_new: bool = False,
    only: frozenset[str] = frozenset(ASSISTED),
) -> None:
    if not only or not only <= frozenset(ASSISTED):
        raise ValueError("Exact assisted deployment roles required")
    mesh = _mesh()
    existing = []
    additions = [
        resource(
            "Service",
            "inference",
            spec={
                "selector": {"app": "inference"},
                "ports": [{"port": 8443, "targetPort": 8443}],
            },
        ),
    ]
    all_fences = [spiffe(r) for r in (*APPS, "help")] + [
        f"spiffe://care-link.demo/demo/{r}" for r in ("runtime", "inference", BRIDGE_ROLE)
    ]
    for role in ASSISTED:
        custom = role not in {"core", "data"}
        if role not in only or (custom and not new_roles) or (not custom and not existing_roles):
            continue
        group = additions if custom else existing
        group.extend(
            [
                secret(role + "-app", _configuration(role, settings, boots, observation)),
                secret(role + "-proxy", {"envoy.json": encode(mesh[role + "-envoy.json"])}),
                _policy(role),
                _deployment(role, boots[role]),
            ]
        )
        if role != "runtime":
            if custom:
                UID[role] = 23120
            try:
                fence = json.loads(trust_config(role))
            finally:
                if custom:
                    UID.pop(role)
            fence["allowed"] = all_fences
            group.extend(
                [
                    secret(role + "-fence", {"config.json": encode(fence)}),
                    secret(
                        role + "-authorization",
                        {"config.json": encode(mesh[role + "-authorization.json"])},
                    ),
                ]
            )
        if custom:
            group.append(resource("ServiceAccount", role, automountServiceAccountToken=False))
    if new_roles:
        k(
            "replace" if replace_new else "create",
            "-f",
            "-",
            payload={"apiVersion": "v1", "kind": "List", "items": additions},
        )
    if existing_roles:
        k("replace", "-f", "-", payload={"apiVersion": "v1", "kind": "List", "items": existing})
