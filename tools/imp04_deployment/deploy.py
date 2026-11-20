"""Phased operator for the accepted, fresh-only IMP-04 target.

The plan is public. Private input is streamed only into the new seed. Every
subsequent Docker mutation is nonce/inspected-ID receipt bound.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path
from typing import Required, TypedDict, cast

from . import docker
from .config import CONFIG, PREFIX, PRIVATE, ROLES, ROOT, proposal

Record = dict[str, object]
APP_IMAGE = "care-link-imp04:plans-002"


class ContainerBudget(TypedDict):
    name: str
    uid: int
    cpu_limit: float
    memory_mib: int


class NetworkSpec(TypedDict, total=False):
    name: Required[str]
    subnet: Required[str]
    internal: Required[bool]
    gateway_mode_ipv4: str


class ImageInputs(TypedDict):
    pinned: dict[str, str]
    derived_keycloak_image_id: str
    browser_base_id: str


class AddressInputs(TypedDict):
    role_proxies: dict[str, str]


class TargetDescriptor(TypedDict):
    proposal_id: str
    containers: list[ContainerBudget]
    volumes: list[str]
    networks: list[NetworkSpec]
    images: ImageInputs
    addresses: AddressInputs


def descriptor() -> TargetDescriptor:
    # config.proposal verifies the exact accepted document digest before this
    # boundary; the trusted fixed document supplies the enumerated shape.
    return cast(TargetDescriptor, proposal())


INGRESS_SOURCE = """
import asyncio
from tools.imp03_shared.relay import TCPToTCPRelay, RelayLimits
async def run():
    relay = TCPToTCPRelay(30443, "172.29.44.12", 30443,
                          limits=RelayLimits(max_connections=64))
    await relay.start()
    try:
        await asyncio.Event().wait()
    finally:
        await relay.close()
asyncio.run(run())
"""


def name(suffix: str) -> str:
    return PREFIX + "-" + suffix


def mount(suffix: str, target: str, *, readonly: bool = False) -> str:
    return (
        "type=volume,source="
        + name(suffix)
        + ",target="
        + target
        + (",readonly" if readonly else "")
    )


def private_write(path: Path, value: object) -> None:
    from .prepare import write

    write(path, (json.dumps(value, indent=2) + "\n").encode())


def image_id(reference: str) -> str:
    return docker.inspect_image_id(reference)


def specs(application_image: str) -> list[docker.ContainerSpec]:
    """Render all 31 accepted containers; no Docker access or secrets needed."""
    p = descriptor()
    pins = p["images"]["pinned"]
    budgets = {c["name"]: c for c in p["containers"]}
    output: list[docker.ContainerSpec] = []

    def add(suffix: str, args: list[str], mounts: list[str], **kwargs: object) -> None:
        budget = budgets[name(suffix)]
        output.append(
            cast(
                docker.ContainerSpec,
                {
                    "name": name(suffix),
                    "image": application_image,
                    "args": args,
                    "mounts": mounts,
                    "user": str(budget["uid"]) + ":" + str(budget["uid"]),
                    "cpus": str(budget["cpu_limit"]),
                    "memory": str(budget["memory_mib"]) + "m",
                    **kwargs,
                },
            )
        )

    seed_mounts = [
        "type=volume,source=" + volume + ",target=/volumes/" + volume.removeprefix(PREFIX + "-")
        for volume in p["volumes"]
    ]
    add(
        "seed",
        ["python", "-c", "import time;time.sleep(14400)"],
        seed_mounts,
        tmpfs=[
            "/operator:rw,noexec,nosuid,size=160m,mode=0700",
            ROOT + ":rw,noexec,nosuid,size=32m,mode=0711",
        ],
        cap_add=["CHOWN", "DAC_OVERRIDE"],
    )
    add(
        "spire-server",
        ["-config", "/config/server.conf"],
        [
            mount("spire-server-config", "/config", readonly=True),
            mount("spire-server-data", "/run/spire/data"),
        ],
        image=pins["spire_server"],
        network=name("infrastructure"),
        ip="172.29.46.10",
        tmpfs=["/tmp:rw,noexec,nosuid,size=16m,mode=1777"],  # noqa: S108 - bounded container tmpfs, no host path
    )
    add(
        "postgres",
        [
            "-c",
            "set -a; . /config/postgres.env; set +a; export PGDATA=/var/lib/postgresql/data; exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/config/postgres.crt -c ssl_key_file=/config/postgres.key -c hba_file=/config/pg_hba.conf -c ssl_min_protocol_version=TLSv1.3",  # noqa: E501 - fixed command/script payload
        ],
        [
            mount("postgres-config", "/config", readonly=True),
            mount("postgres-config", "/docker-entrypoint-initdb.d", readonly=True),
            mount("postgres-data", "/var/lib/postgresql/data"),
        ],
        image=pins["postgres"],
        network=name("database"),
        ip="172.29.45.10",
        aliases=["postgres.imp04.internal"],
        publish=["127.0.0.1:25436:5432"],
        entrypoint="/bin/sh",
        tmpfs=[
            "/var/run/postgresql:rw,noexec,nosuid,size=4m,mode=1777",
            "/tmp:rw,noexec,nosuid,size=16m,mode=1777",  # noqa: S108 - bounded container tmpfs, no host path
        ],
    )
    add(
        "keycloak",
        [
            "-c",
            "set -a; . /config/kc.env; set +a; exec /opt/keycloak/bin/kc.sh start --optimized --import-realm --hostname=https://id.plans.localhost:31443 --hostname-strict=true --http-enabled=false --https-certificate-file=/config/keycloak.crt --https-certificate-key-file=/config/keycloak.key",  # noqa: E501 - fixed command/script payload
        ],
        [
            mount("keycloak-config", "/config", readonly=True),
            mount("keycloak-config", "/opt/keycloak/data/import", readonly=True),
            mount("keycloak-data", "/opt/keycloak/data"),
        ],
        image=p["images"]["derived_keycloak_image_id"],
        network=name("database"),
        ip="172.29.45.13",
        publish=["127.0.0.1:31443:8443"],
        entrypoint="/bin/sh",
        pids_limit=512,
        tmpfs=["/tmp:rw,noexec,nosuid,size=64m,mode=1777"],  # noqa: S108 - bounded container tmpfs, no host path
    )
    for i, role in enumerate(ROLES):
        add(
            role + "-agent",
            ["-config", "/config/agent.conf"],
            [mount(role + "-agent", "/config"), mount(role + "-svid", "/run/spire/sockets")],
            image=pins["spire_agent"],
            network=name("infrastructure"),
            ip="172.29.46." + str(11 + i),
            tmpfs=["/tmp:rw,noexec,nosuid,size=8m,mode=1777"],  # noqa: S108 - bounded container tmpfs, no host path
        )
    add(
        "fence",
        [
            "python",
            "-m",
            "tools.imp03_runtime",
            "trust",
            "--role",
            "fence",
            "--config",
            ROOT + "/fence/config.json",
        ],
        [mount("fence", ROOT + "/fence")],
        groups=["22999"],
    )
    for suffix, _uid, app_uid, network, target, port, address in [
        ("identity-db", 22041, 22011, "database", "172.29.45.10", 5432, "172.29.45.11"),
        ("data-db", 22042, 22013, "database", "172.29.45.10", 5432, "172.29.45.12"),
        ("identity-provider", 22041, 22011, "infrastructure", "172.29.46.20", 8443, "172.29.46.21"),
    ]:
        path = ROOT + "/connectors/" + suffix
        add(
            suffix + "-connector",
            [
                "python",
                "-m",
                "tools.imp03_shared.relay",
                "unix",
                "--socket",
                path + "/forward.sock",
                "--target-host",
                target,
                "--target-port",
                str(port),
                "--allowed-uid",
                str(app_uid),
                "--allowed-uid",
                "0",
                "--access-gid",
                str(app_uid),
            ],
            [mount(suffix, path)],
            network=name(network),
            ip=address,
            groups=[str(app_uid)],
        )
    add(
        "operator-seed",
        ["python", "-c", "import time;time.sleep(14400)"],
        [mount("operator", CONFIG)]
        + [mount(r + "-config", CONFIG + "/" + r) for r in ROLES]
        + [mount("data-db", ROOT + "/connectors/data-db", readonly=True)],
        network=name("database"),
        cap_add=["CHOWN", "DAC_OVERRIDE"],
    )
    for role in ROLES:
        auth = ROOT + "/" + role + "/authorization"
        add(
            role + "-authorization",
            [
                "python",
                "-m",
                "tools.imp03_runtime",
                "trust",
                "--role",
                "authorization",
                "--config",
                auth + "/config.json",
            ],
            [mount(role + "-authorization", auth), mount("fence", ROOT + "/fence", readonly=True)],
            groups=["22002", "22999"],
        )
        mounts = [
            mount(role + "-config", CONFIG + "/" + role),
            mount(role + "-backend", ROOT + "/" + role + "/backend"),
            mount(role + "-outbound", ROOT + "/" + role + "/outbound", readonly=True),
            mount("fence", ROOT + "/fence", readonly=True),
        ]
        args = ["python", "-m", "tools.imp04_deployment.serve", "--root", CONFIG, "--role", role]
        if role == "pdp":
            mounts.append(mount("opa", "/opt", readonly=True))
        forwards = (
            [("identity-db", 5432, 22041), ("identity-provider", 31443, 22041)]
            if role == "identity"
            else [("data-db", 5432, 22042)]
            if role == "data"
            else []
        )
        for suffix, port, uid in forwards:
            target = ROOT + "/connectors/" + suffix
            mounts.append(mount(suffix, target, readonly=True))
            args += ["--forward", str(port), str(uid), target + "/forward.sock"]
        add(
            role + "-app",
            args,
            mounts,
            groups=["22002", "22999"],
            tmpfs=["/tmp:rw,noexec,nosuid,size=16m,mode=1777"],  # noqa: S108 - bounded container tmpfs, no host path
        )
        add(
            role + "-proxy",
            [
                "-c",
                ROOT + "/" + role + "/proxy/envoy.json",
                "--log-level",
                "critical",
                "--disable-hot-restart",
            ],
            [
                mount(role + "-proxy", ROOT + "/" + role + "/proxy", readonly=True),
                mount(role + "-backend", ROOT + "/" + role + "/backend", readonly=True),
                mount(role + "-outbound", ROOT + "/" + role + "/outbound"),
                mount(role + "-authorization", auth, readonly=True),
                mount(role + "-svid", ROOT + "/" + role + "/spire", readonly=True),
            ],
            image=pins["envoy"],
            network=name("mesh"),
            ip=p["addresses"]["role_proxies"][role],
            pid_container=name(role + "-agent"),
        )
    add(
        "ingress",
        [
            "python",
            "-c",
            INGRESS_SOURCE,
        ],
        [],
        network=name("ingress"),
        publish=["127.0.0.1:30443:30443"],
    )
    add(
        "review-chrome",
        ["node", "/opt/review-server.cjs"],
        [mount("browser-home", "/run/browser-home")],
        image=p["images"]["browser_base_id"],
        network=name("ingress"),
        publish=["127.0.0.1:30900:29900"],
        pids_limit=512,
        init_process=True,
        tmpfs=["/tmp:rw,nosuid,nodev,size=1g,mode=1777"],  # noqa: S108 - bounded container tmpfs, no host path
        environment={
            "HOME": "/run/browser-home",
            "NODE_EXTRA_CA_CERTS": "/run/browser-home/ca.crt",
            "CARE_LINK_REVIEW_WS_PATH": "PRIVATE_ISSUED_AT_BROWSER_PHASE",
        },
    )
    if len(output) != 31 or {c["name"] for c in output} != set(budgets):
        raise ValueError("Container plan differs from accepted enumeration")
    return output


def plan(application_image: str) -> Record:
    p = descriptor()
    return {
        "proposal_id": p["proposal_id"],
        "networks": p["networks"],
        "volumes": p["volumes"],
        "containers": specs(application_image),
        "additional_networks": {
            name("keycloak"): [
                {"name": name("infrastructure"), "ip": "172.29.46.20"},
                {"name": name("ingress")},
            ],
            name("ingress"): [{"name": name("mesh")}],
        },
    }


def create(suffix: str, application_image: str) -> None:
    selected = next(x.copy() for x in specs(application_image) if x["name"] == name(suffix))
    docker.create_container(**selected)


def _wait(name_: str, command: list[str], *, timeout: float = 60) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return docker.exec(name_, command, root=True)
        except RuntimeError:
            time.sleep(0.25)
    raise TimeoutError("Owned service readiness failed: " + name_)


def wait_socket(container: str, socket: str) -> None:
    _wait(
        container,
        [
            "python",
            "-c",
            "import pathlib,stat,sys;p=pathlib.Path(sys.argv[1]);sys.exit(0 if p.exists() and stat.S_ISSOCK(p.stat().st_mode) else 1)",  # noqa: E501 - fixed command/script payload
            socket,
        ],
    )


def resources(private: Path, application_image: str) -> Record:
    p = descriptor()
    for network in p["networks"]:
        docker.create_network(
            network["name"],
            subnet=network["subnet"],
            internal=network["internal"],
            isolated=network.get("gateway_mode_ipv4") == "isolated",
        )
    for volume in p["volumes"]:
        docker.create_volume(volume)
    create("seed", application_image)
    docker.start(name("seed"))
    for source, target in [
        (private / "inputs.json", "/operator/inputs.json"),
        (private / "tls", "/operator/tls"),
        (private / "realm.json", "/operator/realm.json"),
        (private / "provider-init.sql", "/operator/provider-init.sql"),
        (private / "opa-linux-arm64", "/operator/opa"),
    ]:
        docker.copy_into(name("seed"), source, target)
    return {
        "new_networks": len(p["networks"]),
        "new_volumes": len(p["volumes"]),
        "seed_started": True,
    }


def authority(private: Path, application_image: str) -> Record:
    from .trust import bootstrap

    return bootstrap(private, application_image)


def seed(private: Path, application_image: str) -> Record:
    del private, application_image
    result = docker.exec(
        name("seed"),
        ["python", "-m", "tools.imp04_deployment.supervisor", "--input", "/operator/inputs.json"],
        root=True,
    )
    return json.loads(result)


def dependencies(private: Path, application_image: str) -> Record:
    del private
    create("postgres", application_image)
    docker.start(name("postgres"))
    _wait(name("postgres"), ["pg_isready", "-U", "postgres"], timeout=120)
    create("keycloak", application_image)
    docker.connect_network(name("keycloak"), name("infrastructure"), ip="172.29.46.20")
    docker.connect_network(name("keycloak"), name("ingress"))
    docker.start(name("keycloak"))
    for role in ROLES:
        create(role + "-agent", application_image)
        docker.start(name(role + "-agent"))
    create("fence", application_image)
    docker.start(name("fence"))
    for suffix in ("identity-db", "data-db", "identity-provider"):
        create(suffix + "-connector", application_image)
        docker.start(name(suffix + "-connector"))
        wait_socket(name(suffix + "-connector"), ROOT + "/connectors/" + suffix + "/forward.sock")
    return {
        "new_dependencies_started": True,
        "provider_readiness": "must_verify_https_discovery",
        "live_workload_trust": "pending",
    }


def provision(private: Path, application_image: str) -> Record:
    del private
    create("operator-seed", application_image)
    docker.start(name("operator-seed"))
    script = (
        "import json;from pathlib import Path;from tools.imp03_shared.relay import ThreadedLoopbackBridge;from tools.imp04_deployment.provision import provision;from tools.imp03_runtime.config import load;"  # noqa: E501 - fixed command/script payload
        + f"b=ThreadedLoopbackBridge(Path('{ROOT}/connectors/data-db/forward.sock'),5432,server_uid=22042);b.start();provision(Path('{CONFIG}'),load(Path('{CONFIG}/admin.json')));b.close();print(json.dumps({{'provisioned':True,'existing_state_adopted':False}}))"  # noqa: E501 - fixed script payload
    )
    result = json.loads(docker.exec(name("operator-seed"), ["python", "-c", script], root=True))
    docker.stop(name("operator-seed"))
    return result


def applications(private: Path, application_image: str) -> Record:
    del private
    for role in ROLES:
        for suffix in ("authorization", "app", "proxy"):
            create(role + "-" + suffix, application_image)
            docker.start(name(role + "-" + suffix))
    create("ingress", application_image)
    docker.connect_network(name("ingress"), name("mesh"))
    docker.start(name("ingress"))
    docker.stop(name("seed"))
    return {
        "new_applications_started": list(ROLES),
        "browser_origin": "https://plans.localhost:30443",
        "live_trust": "not_yet_qualified",
    }


def browser(private: Path, application_image: str) -> Record:
    selected = next(
        x.copy() for x in specs(application_image) if x["name"] == name("review-chrome")
    )
    token = secrets.token_hex(24)
    environment = selected.get("environment")
    if environment is None:
        raise ValueError("Browser process environment required")
    environment["CARE_LINK_REVIEW_WS_PATH"] = token
    identity = docker.create_container(**selected)
    docker.start(name("review-chrome"))
    script = "const fs=require('fs');fs.mkdirSync('/run/browser-home/.local/share/pki/nssdb',{recursive:true});"  # noqa: E501 - fixed command/script payload
    docker.exec(name("review-chrome"), ["node", "-e", script])
    docker.exec(
        name("review-chrome"),
        [
            "certutil",
            "-N",
            "--empty-password",
            "-d",
            "sql:/run/browser-home/.local/share/pki/nssdb",
        ],
    )
    docker.exec(
        name("review-chrome"),
        [
            "certutil",
            "-A",
            "-d",
            "sql:/run/browser-home/.local/share/pki/nssdb",
            "-n",
            "IMP04 transport CA",
            "-t",
            "C,,",
            "-i",
            "/run/browser-home/ca.crt",
        ],
    )
    endpoint = "ws://127.0.0.1:30900/" + token
    private_write(private / "browser-server.json", {"container_id": identity, "endpoint": endpoint})
    cfg = json.loads((private / "browser.json").read_text())
    cfg["endpoint"] = endpoint
    # Same owned credential file is atomically replaced, never printed.
    temporary = private / "browser-updated.json"
    private_write(temporary, cfg)
    temporary.replace(private / "browser.json")
    return {
        "container_id": identity,
        "broker_ready": "verify_before_connect",
        "native_ca_imported": True,
        "tls_bypass": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=(
            "plan",
            "resources",
            "authority",
            "seed",
            "dependencies",
            "provision",
            "applications",
            "browser",
        ),
        required=True,
    )
    parser.add_argument("--private", type=Path, default=PRIVATE)
    parser.add_argument("--image", default=APP_IMAGE)
    args = parser.parse_args()
    if args.private != PRIVATE or args.private.is_symlink():
        raise ValueError("Exact new-target private root required")
    image = image_id(args.image)
    if args.action == "plan":
        print(json.dumps(plan(image), indent=2))
        return
    actions = {
        "resources": resources,
        "authority": authority,
        "seed": seed,
        "dependencies": dependencies,
        "provision": provision,
        "applications": applications,
        "browser": browser,
    }
    result = actions[args.action](args.private, image)
    private_write(args.private / (args.action + "-result.json"), result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
