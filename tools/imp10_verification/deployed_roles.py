"""Render the owned IMP-10 qualification roles using product launchers and mesh."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

from care_link_data.training_replay import training_bundle
from care_link_domain import canonical_training

from tools.imp02_application.config import private_key
from tools.imp02_lab.model import container_security, pod_security
from tools.imp10_runtime.mesh import configurations

from .deployed_fixtures import (
    CLUSTER,
    HELP_ORIGIN,
    IDENTITY_KEY,
    MAIN_ORIGIN,
    SCOPE,
    STATE,
    Record,
    artifact,
    dsn,
    encode,
    file_pin,
    merge_policy,
    oidc,
    product_pins,
    secret,
    signed_mapping,
)

PRODUCTS = product_pins()
NAMESPACE = CLUSTER
ASSETS = Path("/private/tmp/care-link-imp10-008-assets")
IMAGE = "care-link-imp10:protected-008-replay-final"
OPA_IMAGE = "care-link-imp10:protected-008-opa"
PROXY = 23002
AUTHORIZATION = 23003
FENCE = 23004
APPS = ("core", "identity", "data", "pdp", "journal", "receiver", "training")
UID = {role: 23110 + i for i, role in enumerate(APPS)}
SOCKET_BASE = "/sockets"
BACKEND = f"{SOCKET_BASE}/backend/owned/service.sock"
AUTH = f"{SOCKET_BASE}/authorization/owned/authority.sock"
FENCE_PATH = f"{SOCKET_BASE}/fence/owned/fence.sock"
SPIRE = "/run/spire/agent.sock"
HELP_IP = "172.23.255.239"
ROUTES = {
    "core": ("data", "identity", "pdp", "receiver", "training"),
    "identity": (),
    "data": ("core", "identity", "pdp", "journal", "receiver"),
    "journal": (),
    "pdp": (),
    "training": ("identity",),
    "receiver": ("identity",),
    "help": ("identity",),
}

OPA_SEED = """
import hashlib, os
from pathlib import Path
source = Path('/installed-opa')
target = Path('/opa/opa')
expected = hashlib.sha256(source.read_bytes()).hexdigest()
if not target.exists():
    pending = target.with_suffix('.incoming')
    with pending.open('xb') as stream:
        stream.write(source.read_bytes())
    pending.chmod(0o500)
    pending.replace(target)
assert not target.is_symlink() and target.stat().st_uid == os.geteuid()
assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
"""

SOCKET_SEED = """
import ipaddress, json, os, shutil, sys
from pathlib import Path

mode = sys.argv[1]
if mode == 'proxy':
    source = json.loads(Path('/seed/envoy.json').read_text())
    addr = str(ipaddress.IPv4Address(os.environ['POD_IP']))
    if not ipaddress.ip_address(addr).is_private or addr == '127.0.0.11':
        raise ValueError('private leased pod address required')
    for listener in source['static_resources']['listeners']:
        address = listener.get('address', {}).get('socket_address')
        if address and address['address'] == '127.0.0.11':
            address['address'] = addr
    Path('/proxy/envoy.json').write_text(json.dumps(source))
    directory = Path('/sockets/outbound/owned')
    directory.mkdir(exist_ok=True, mode=0o710)
    directory.chmod(0o710)
else:
    shared = Path('/sockets') / ('backend' if mode == 'app' else mode)
    owned = shared / 'owned'
    owned.mkdir(exist_ok=True, mode=0o710)
    owned.chmod(0o710)
    if mode == 'fence':
        state = shared / 'state'
        state.mkdir(exist_ok=True, mode=0o700)
        state.chmod(0o700)
    if mode != 'app':
        shutil.copyfile('/seed/config.json', '/config/config.json')
        Path('/config/config.json').chmod(0o600)
    else:
        for source in Path('/seed').iterdir():
            if source.name.startswith('.'):
                continue
            target = Path('/config') / source.name
            shutil.copyfile(source, target)
            target.chmod(0o600)
        if Path('/config/journal-origin.json').exists():
            state = Path('/state/journal')
            state.mkdir(exist_ok=True, mode=0o700)
            for name in ('head.json', 'origin.json', 'records.jsonl', 'writer.lock'):
                target = state / name
                if not target.exists():
                    shutil.copyfile('/config/journal-' + name, target)
                    target.chmod(0o600)
"""


def k(*args: str, payload: object | None = None, timeout: int = 40) -> str:
    command = [
        "kubectl",
        "--kubeconfig",
        str(ASSETS / "kubeconfig"),
        "--context",
        "kind-" + CLUSTER,
        "--namespace",
        NAMESPACE,
        *args,
    ]
    result = subprocess.run(  # noqa: S603 - explicit leased context and operation
        command,
        input=None if payload is None else json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        # Never return input, configs, or credential-bearing values from exec.
        detail = result.stderr.splitlines()[-1:] if payload is None else []
        raise RuntimeError(f"Scoped kubectl {args[0]} failed ({result.returncode}) {detail}")
    return result.stdout.strip()


def metadata(name: str) -> Record:
    return {"name": name, "namespace": NAMESPACE, "labels": {"care-link.session": SCOPE}}


def resource(kind: str, name: str, *, api: str = "v1", **fields: object) -> Record:
    return {"apiVersion": api, "kind": kind, "metadata": metadata(name), **fields}


def private_roles() -> Record:
    roles: Record = {}
    for role in (*APPS, "help"):
        roles[role] = {
            "spire_socket": SPIRE,
            "outbound": {dest: outbound_path(dest) for dest in ROUTES[role]},
            "backend_socket": BACKEND,
        }
        if role != "help":
            roles[role].update(
                {
                    "address": "127.0.0.11",
                    "dial_address": f"{role}.{NAMESPACE}.svc.cluster.local",
                    "port": 8443,
                    "authorization_socket": AUTH,
                    "authorization_uid": AUTHORIZATION,
                    "trust_bundle": "/trust/bundle.crt",
                    "proxy_uid": PROXY,
                    "fence_socket": FENCE_PATH,
                    "fence_uid": FENCE,
                }
            )
        if role in {"core", "help"}:
            roles[role]["browser"] = {
                "origin": MAIN_ORIGIN if role == "core" else HELP_ORIGIN,
                "address": "127.0.0.11",
                "port": 9443,
                "certificate": "/tls/browser.crt",
                "private_key": "/tls/browser.key",
            }
    pins = PRODUCTS["images"]
    versions = PRODUCTS["selected_versions"]
    return {
        "session": "imp10-protected",
        "features": {"assisted": False, "training": True, "referral": True, "help": True},
        "pins": {
            "envoy_image": pins["envoy"],
            "envoy_version": versions["envoy"],
            "spire_image": pins["spire_agent"],
            "spire_version": versions["spire"],
            "svid_ttl_seconds": 300,
        },
        "roles": roles,
    }


def outbound_path(role: str) -> str:
    return f"{SOCKET_BASE}/outbound/owned/{role}.sock"


def config_path(name: str) -> str:
    return "/config/" + name


def role_inputs(role: str, settings: Record, keycloak_ip: str) -> dict[str, bytes]:
    cfg: Record = {
        "session": "imp10-protected",
        "role": role,
        "uid": UID[role],
        "proxy_uid": PROXY,
        "fence_uid": FENCE,
        "fence_socket": FENCE_PATH,
        "backend_socket": BACKEND,
        "training_enabled": True,
        "referral_enabled": True,
        "outbound": {
            dest: {"socket": outbound_path(dest), "origin": f"https://{dest}.mesh:8443"}
            for dest in ROUTES[role]
        },
    }
    files: dict[str, bytes] = {}

    def file(name: str, content: bytes) -> str:
        files[name] = content
        return config_path(name)

    def owned(name: str) -> str:
        return file(name, (STATE / name).read_bytes())

    if role in {"identity", "data", "receiver", "training"}:
        cfg.update(store_dsn=dsn(settings, role))
        owned("browser-ca.pem")
        files["ca.pem"] = files.pop("browser-ca.pem")
    if role in {"core", "data", "receiver", "training"}:
        cfg["identity_public_key"] = owned("identity.pub")
    if role in {"data", "receiver", "training"}:
        cfg["core_public_key"] = owned("core-signing.pub")
    if role in {"core", "data", "receiver"}:
        cfg.update(
            simulator_mapping_file=file("receiver-mapping.json", signed_mapping(settings)),
            simulator_trusted_keys={"imp10-008-mapping": owned("receiver-mapping.pub")},
        )
    if role == "identity":
        cfg.update(
            oidc=oidc(settings, "main"),
            provider_address=keycloak_ip,
            provider_ca=config_path("ca.pem"),
            main_origin=MAIN_ORIGIN,
            custody_key=owned("identity-custody"),
            signing_key=owned("identity.sign"),
            signing_key_id=IDENTITY_KEY,
            help_identity={"origin": HELP_ORIGIN, "oidc": oidc(settings, "help")},
        )
    elif role == "core":
        cfg.update(core_signing_key=owned("core-signing.sign"), web_directory="/app/apps/web/dist")
    elif role == "pdp":
        policy = merge_policy()
        cfg.update(
            executable="/opa/opa",
            executable_digest=json.loads(artifact("config/demo/imp03/products.json"))["opa"][
                "linux_arm64_static_sha256"
            ],
            policy={
                "source": file("manual.rego", policy),
                "signature": base64.b64encode(
                    private_key(str(STATE / "policy.sign")).sign(policy)
                ).decode(),
                "public_key": owned("policy.pub"),
            },
        )
    elif role == "journal":
        cfg.update(
            signing_key=owned("journal.sign"),
            journal_directory="/state/journal",
            signing_key_id=f"{SCOPE}-journal",
            journal_id=settings["journal_id"],
        )
        for item in (STATE / "journal").iterdir():
            file("journal-" + item.name, item.read_bytes())
    elif role == "receiver":
        cfg.update(
            content_key=owned("receiver-content"),
            actor_services={
                a["account_id"]: settings["service_id"]
                for a in settings["accounts"]
                if a["role"] == "receiver"
            },
        )
    elif role in {"data", "training"}:
        training = artifact("config/demo/imp10/training-artifact.json")
        cfg["training_artifact"] = file_pin(file("training-artifact.json", training), training)
        if role == "data":
            cfg.update(
                content_key=owned("data-content"),
                cursor_key=owned("data-cursor"),
                journal_public_key=owned("journal.pub"),
                disclosures=json.loads(artifact("config/demo/imp03/disclosures.json")),
            )
            bundle = training_bundle(
                {
                    "artifact": training,
                    "runner": artifact("packages/domain/src/care_link_domain/training.py"),
                    "contracts": artifact(
                        "packages/contracts/python/src/care_link_contracts/schema.json"
                    ),
                }
            )
            catalog = canonical_training(
                {
                    "version": 1,
                    "artifact_digest": hashlib.sha256(training).hexdigest(),
                    "bundle_digest": bundle,
                    "captures": [],
                }
            )
            prepared = STATE / "replay"
            if prepared.is_dir():
                catalog = (prepared / "replay-catalog.json").read_bytes()
                for name in ("capture-manifest.json", "capture-observations.json"):
                    file(name, (prepared / name).read_bytes())
            cfg["replay_catalog"] = file_pin(file("replay-catalog.json", catalog), catalog)
        else:
            cfg["content_key"] = owned("training-content")
            policy = encode(
                {
                    "version": 1,
                    "grants": [
                        {
                            "trainer_id": a["account_id"],
                            "actions": ["scenario_create", "scenario_read", "scenario_stop"],
                        }
                        for a in settings["accounts"]
                        if a["role"] == "trainer"
                    ],
                }
            )
            cfg["training_policy"] = file_pin(file("training-policy.json", policy), policy)
    files["config.json"] = encode(cfg)
    return files


def mount(name: str, path: str, *, readonly: bool = False) -> Record:
    return {"name": name, "mountPath": path, "readOnly": readonly}


def part(
    name: str,
    uid: int,
    image: str,
    command: list[str],
    mounts: list[Record],
    *,
    memory: str = "128Mi",
) -> Record:
    return {
        "name": name,
        "image": image,
        "imagePullPolicy": "Never",
        "command": command,
        "securityContext": {**container_security(), "runAsUser": uid, "runAsGroup": PROXY},
        "env": [{"name": "TMPDIR", "value": "/tmp"}],  # noqa: S108 - bounded per-pod volume
        "resources": {
            "requests": {"cpu": "20m", "memory": "16Mi"},
            "limits": {"cpu": "1", "memory": memory},
        },
        "volumeMounts": mounts,
    }


def trust_config(role: str) -> bytes:
    return encode(
        {
            "session": "imp03-002",
            "uid": FENCE,
            "socket": FENCE_PATH,
            "ledger_directory": "/sockets/fence/state",
            "access_gid": PROXY,
            "read_uids": [UID[role], AUTHORIZATION],
            "restrict_uid": 23199,
            "allowed": [f"spiffe://care-link.demo/demo/{name}" for name in (*APPS, "help")],
        }
    )


def pod(role: str) -> Record:
    config_names = ["app", "authorization", "fence"]
    path_for = {"app": "backend", "authorization": "authorization", "fence": "fence"}
    sockets = ["backend", "authorization", "fence", "outbound"]
    app_mounts = [
        mount("app-config", "/config"),
        mount("backend", "/sockets/backend"),
        mount("outbound", "/sockets/outbound", readonly=True),
        mount("fence", "/sockets/fence", readonly=True),
        mount("app-state", "/state"),
        mount("app-temp", "/tmp"),  # noqa: S108 - bounded per-pod volume
    ]
    volumes: list[Record] = [
        {"name": name, "emptyDir": {"medium": "Memory", "sizeLimit": "8Mi"}}
        for name in [*sockets, "app-config", "authorization-config", "fence-config", "proxy-config"]
    ]
    volumes += [
        {"name": "app-state", "emptyDir": {"sizeLimit": "200Mi"}},
        {"name": "app-temp", "emptyDir": {"sizeLimit": "100Mi"}},
        {"name": "spire", "csi": {"driver": "csi.spiffe.io", "readOnly": True}},
        {"name": "trust", "configMap": {"name": "imp10-spire-bundle"}},
    ]
    volumes += [
        {"name": name + "-seed", "secret": {"secretName": role + "-" + name, "defaultMode": 0o640}}
        for name in (*config_names, "proxy")
    ]
    init: list[Record] = []
    for name, uid in (("app", UID[role]), ("authorization", AUTHORIZATION), ("fence", FENCE)):
        path = path_for[name]
        init.append(
            part(
                "seed-" + name,
                uid,
                IMAGE,
                ["python", "-c", SOCKET_SEED, name],
                [
                    mount(name + "-seed", "/seed", readonly=True),
                    mount(name + "-config", "/config"),
                    mount(path, "/sockets/" + path),
                    *([mount("app-state", "/state")] if name == "app" else []),
                ],
            )
        )
    proxy_init = part(
        "seed-proxy",
        PROXY,
        IMAGE,
        ["python", "-c", SOCKET_SEED, "proxy"],
        [
            mount("proxy-seed", "/seed", readonly=True),
            mount("proxy-config", "/proxy"),
            mount("outbound", "/sockets/outbound"),
        ],
    )
    proxy_init["env"].append(
        {"name": "POD_IP", "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}}}
    )
    init.append(proxy_init)
    proxy_mounts = [
        mount("proxy-config", "/proxy", readonly=True),
        mount("spire", "/run/spire", readonly=True),
        mount("backend", "/sockets/backend", readonly=True),
        mount("authorization", "/sockets/authorization", readonly=True),
        mount("outbound", "/sockets/outbound"),
    ]
    if role == "core":
        volumes.append(
            {"name": "tls", "secret": {"secretName": "core-browser", "defaultMode": 0o640}}
        )
        proxy_mounts.append(mount("tls", "/tls", readonly=True))
    if role == "pdp":
        volumes.append({"name": "opa", "emptyDir": {"sizeLimit": "100Mi"}})
        init.append(
            part(
                "seed-opa",
                UID[role],
                OPA_IMAGE,
                ["python", "-c", OPA_SEED],
                [mount("opa", "/opa")],
            )
        )
        app_mounts.append(mount("opa", "/opa", readonly=True))
    command = [
        "python",
        "-m",
        "tools.imp10_runtime.serve",
        "--role",
        role,
        "--config",
        "/config/config.json",
    ]
    app = part(
        "app", UID[role], IMAGE, command, app_mounts, memory="320Mi" if role == "pdp" else "192Mi"
    )
    if role in {"identity", "pdp"}:
        app["resources"]["limits"]["cpu"] = "2"
    app["readinessProbe"] = {"exec": {"command": ["test", "-S", BACKEND]}, "periodSeconds": 3}
    proxy = part(
        "proxy",
        PROXY,
        PRODUCTS["images"]["envoy"],
        [
            "/usr/local/bin/envoy",
            "-c",
            "/proxy/envoy.json",
            "--concurrency",
            "1",
            "--log-level",
            "warning",
        ],
        proxy_mounts,
        memory="128Mi",
    )
    proxy["ports"] = [{"name": "mesh", "containerPort": 8443}]
    if role == "core":
        proxy["ports"].append({"name": "browser", "containerPort": 9443})
    trusted = []
    for name, uid in (("authorization", AUTHORIZATION), ("fence", FENCE)):
        specific = [
            mount(name + "-config", "/config", readonly=True),
            mount(name, "/sockets/" + name),
        ]
        if name == "authorization":
            specific += [
                mount("trust", "/trust", readonly=True),
                mount("fence", "/sockets/fence", readonly=True),
            ]
        trusted.append(
            part(
                name,
                uid,
                IMAGE,
                [
                    "python",
                    "-c",
                    "from tools.imp03_runtime.config import load; "
                    "from tools.imp03_runtime.trust import serve; from pathlib import Path; "
                    f"serve('{name}', load(Path('/config/config.json')))",
                ],
                specific,
            )
        )
    return {
        "serviceAccountName": role,
        "automountServiceAccountToken": False,
        "securityContext": {
            **pod_security(UID[role]),
            "fsGroup": PROXY,
            "supplementalGroupsPolicy": "Strict",
        },
        "initContainers": init,
        "containers": [app, proxy, *trusted],
        "volumes": volumes,
    }


def ports(*values: int) -> list[Record]:
    return [{"protocol": "TCP", "port": value} for value in values]


def selector(app: str) -> Record:
    return {"podSelector": {"matchLabels": {"app": app}}}


def allow_from(name: str, lst: list[Record], *remote_ports: int) -> Record:
    return resource(
        "NetworkPolicy",
        name + "-mesh",
        api="networking.k8s.io/v1",
        spec={
            "podSelector": selector(name)["podSelector"],
            "policyTypes": ["Ingress", "Egress"],
            "ingress": lst,
            "egress": [],
        },
    )


def network(role: str) -> Record:
    allowed = [selector(source) for source in APPS if role in ROUTES[source]]
    if role == "identity":
        allowed += [{"ipBlock": {"cidr": HELP_IP + "/32"}}]
    ingress = [{"from": allowed, "ports": ports(8443)}]
    if role == "core":
        ingress.append({"ports": ports(9443)})
    np = allow_from(role, ingress)
    egress = np["spec"]["egress"]
    egress.extend({"to": [selector(dest)], "ports": ports(8443)} for dest in ROUTES[role])
    if role in {"identity", "data", "training", "receiver"}:
        egress.append({"to": [selector("postgres")], "ports": ports(5432)})
    if role == "identity":
        egress.append({"to": [selector("keycloak")], "ports": ports(8443)})
    if ROUTES[role] or role in {"identity", "training", "receiver", "data"}:
        egress.append(
            {
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
        )
    return np


def services() -> list[Record]:
    out = []
    for role in APPS:
        incoming = {"name": "mesh", "port": 8443, "targetPort": 8443}
        if role == "identity":
            incoming["nodePort"] = 30443
        spec: Record = {"selector": {"app": role}, "ports": [incoming]}
        if role in {"core", "identity"}:
            spec.update(type="NodePort", externalTrafficPolicy="Local")
        if role == "core":
            spec["ports"].append(
                {"name": "browser", "port": 9443, "targetPort": 9443, "nodePort": 30441}
            )
        out.append(resource("Service", role, spec=spec))
    return out


def role_objects(settings: Record, keycloak_ip: str) -> list[Record]:
    mesh = configurations(private_roles())
    objects = services() + [
        secret(
            "core-browser",
            {
                "browser.crt": (STATE / "core.crt").read_bytes(),
                "browser.key": (STATE / "core.key").read_bytes(),
            },
        )
    ]
    for role in APPS:
        labels = {"app": role, "care-link.session": SCOPE}
        objects.extend(
            [
                resource("ServiceAccount", role, automountServiceAccountToken=False),
                secret(role + "-app", role_inputs(role, settings, keycloak_ip)),
                secret(role + "-proxy", {"envoy.json": encode(mesh[role + "-envoy.json"])}),
                secret(role + "-fence", {"config.json": trust_config(role)}),
                secret(
                    role + "-authorization",
                    {"config.json": encode(mesh[role + "-authorization.json"])},
                ),
                network(role),
                resource(
                    "Deployment",
                    role,
                    api="apps/v1",
                    spec={
                        "replicas": 1,
                        "selector": {"matchLabels": {"app": role}},
                        "strategy": {"type": "Recreate"},
                        "template": {"metadata": {"labels": labels}, "spec": pod(role)},
                    },
                ),
            ]
        )
    return objects


def apply_roles(settings: Record) -> None:
    address = k("get", "service", "keycloak", "-o", "jsonpath={.spec.clusterIP}")
    manifests = role_objects(settings, address)
    k("create", "-f", "-", payload={"apiVersion": "v1", "kind": "List", "items": manifests})
    print(f"Created {len(manifests)} scoped product role resources.")


def provision_stores(
    settings: Record,
    *,
    existing_empty: bool,
    existing_migrations: bool = False,
) -> None:
    """Run initial migration in an isolated short-lived PostgreSQL admin client."""

    name = "imp10-initial-provisioner"
    keys = (
        "settings.json",
        "browser-ca.pem",
        "journal.sign",
        "identity.sign",
        "identity-custody",
        "manual.rego",
    )
    provisioner = part(
        name,
        23109,
        IMAGE,
        ["python", "-c", "from threading import Event; Event().wait()"],
        [mount("seed", "/seed", readonly=True), mount("work", "/operator")],
    )
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
    resources = [
        secret(
            name,
            {
                key: merge_policy() if key == "manual.rego" else (STATE / key).read_bytes()
                for key in keys
            },
        ),
        resource(
            "NetworkPolicy",
            name,
            api="networking.k8s.io/v1",
            spec={
                "podSelector": selector(name)["podSelector"],
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [],
                "egress": [{"to": [selector("postgres")], "ports": ports(5432)}, dns],
            },
        ),
        resource(
            "NetworkPolicy",
            name + "-postgres",
            api="networking.k8s.io/v1",
            spec={
                "podSelector": selector("postgres")["podSelector"],
                "policyTypes": ["Ingress"],
                "ingress": [{"from": [selector(name)], "ports": ports(5432)}],
            },
        ),
        resource(
            "Pod",
            name,
            spec={
                "automountServiceAccountToken": False,
                "restartPolicy": "Never",
                "securityContext": {**pod_security(23109), "fsGroup": PROXY},
                "containers": [provisioner],
                "volumes": [
                    {"name": "seed", "secret": {"secretName": name, "defaultMode": 0o640}},
                    {"name": "work", "emptyDir": {"medium": "Memory", "sizeLimit": "8Mi"}},
                ],
            },
        ),
    ]
    resources[-1]["metadata"]["labels"]["app"] = name
    k("create", "-f", "-", payload={"apiVersion": "v1", "kind": "List", "items": resources})
    try:
        k("wait", "--for=condition=Ready", f"pod/{name}", "--timeout=45s", timeout=50)
        source = Path(__file__).with_name("deployed_fixtures.py").read_text()
        code = (
            source
            + f"""
STATE = Path('/operator/private')
STATE.mkdir(mode=0o700)
for key in {keys!r}:
    write(STATE / key, (Path('/seed') / key).read_bytes())
initialize(json.loads((STATE / 'settings.json').read_text()), admin_port=5432,
           admin_host='postgres', existing_empty={existing_empty!r},
           existing_migrations={existing_migrations!r})
print('Verified TLS, migrated and bootstrapped four scoped stores.')
"""
        )
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
            name,
            "--",
            "python",
            "-c",
            "import sys; p='/app/tools/imp10_verification/deployed_fixtures.py'; "
            "exec(compile(sys.stdin.read(),p,'exec'),{'__file__':p,'__name__':'__main__'})",
        ]
        proc = subprocess.run(  # noqa: S603 - owned provisioner with fixed exec command
            command, input=code, capture_output=True, text=True, timeout=90
        )
        if proc.returncode:
            # Keep private database state in scoped custody.
            print("\n".join(proc.stderr.splitlines()[-8:]))
            raise RuntimeError("Owned admin provisioner did not complete")
        print(proc.stdout.strip())
    finally:
        k(
            "delete",
            "pod/" + name,
            "secret/" + name,
            "networkpolicy/" + name,
            "networkpolicy/" + name + "-postgres",
            "--ignore-not-found",
            "--wait=false",
        )

    from care_link_recovery_control import FileJournal

    FileJournal.provision(
        STATE / "journal",
        private_key(str(STATE / "journal.sign")),
        f"{SCOPE}-journal",
        journal_id=settings["journal_id"],
    )
