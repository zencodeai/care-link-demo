"""Fresh, labelled Docker composition sharing only the named lab infrastructure."""

import json
import time
from pathlib import Path
from typing import cast

from . import docker
from .infrastructure import initialize_spire, postgres_access, private_write, verify_cluster
from .model import (
    AUTH_UID,
    CONFIG,
    INGRESS_NETWORK,
    MESH_IP,
    MESH_NETWORK,
    PG_NODEPORT,
    PREFIX,
    ROLE_UID,
    ROOT,
    RUNTIME_IMAGE,
    Record,
    mount,
    volume_names,
)
from .profiles import ACTIVE


def name(suffix: str) -> str:
    return PREFIX + "-" + suffix


def create(
    suffix: str,
    args: list[str],
    mounts: list[str],
    *,
    uid: int = 65532,
    image: str = RUNTIME_IMAGE,
    network: str = "none",
    ip: str | None = None,
    groups: list[str] | None = None,
    pid: str | None = None,
    publish: list[str] | None = None,
    tmpfs: list[str] | None = None,
    cap_add: list[str] | None = None,
    entrypoint: str | None = None,
    cpus: str = "1",
    memory: str = "256m",
    environment: dict[str, str] | None = None,
) -> str:
    return docker.create_container(
        name(suffix),
        image=image,
        args=args,
        mounts=mounts,
        user=f"{uid}:{uid}",
        network=network,
        ip=ip,
        pid_container=pid,
        groups=groups,
        publish=publish,
        tmpfs=tmpfs,
        cap_add=cap_add,
        entrypoint=entrypoint,
        cpus=cpus,
        memory=memory,
        environment=environment,
    )


def wait_socket(container: str, socket: str, *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        value = docker.exec(
            container,
            [
                "python",
                "-c",
                "import pathlib,stat,sys; p=pathlib.Path(sys.argv[1]); "
                "print(p.exists() and stat.S_ISSOCK(p.stat().st_mode))",
                socket,
            ],
            root=False,
        ).strip()
        if value == "True":
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Named protected socket readiness failed: " + container)
        time.sleep(0.2)


def prepare_volumes(private: Path) -> Record:
    """Run only once; a partial resource set is retained, never adopted/reset."""
    verify_cluster()
    for volume in volume_names():
        docker.create_volume(volume)
    docker.create_network(MESH_NETWORK, subnet=ACTIVE.subnet, internal=True, isolated=True)
    docker.create_network(INGRESS_NETWORK)
    seed_mounts = [
        mount(v.removeprefix(PREFIX + "-"), "/volumes/" + v.removeprefix(PREFIX + "-"))
        for v in volume_names()
    ]
    create(
        "seed",
        ["python", "-c", "import time;time.sleep(7200)"],
        seed_mounts,
        uid=0,
        tmpfs=[
            "/operator:rw,noexec,nosuid,size=160m,mode=0700",
            ROOT + ":rw,noexec,nosuid,size=32m,mode=0711",
        ],
        cap_add=["CHOWN", "DAC_OVERRIDE"],
    )
    docker.start(name("seed"))
    result = initialize_spire(private, list(ROLE_UID))
    for source, target in [
        (private / "inputs.json", "/operator/inputs.json"),
        (private / "tls-renewal", "/operator/tls"),
        (private / "agents", "/operator/agents"),
        (private / "spire-bundle.pem", "/operator/spire-bundle.pem"),
        (private / "opa-linux-arm64", "/operator/opa"),
    ]:
        docker.copy_into(name("seed"), source, target)
    result["volume_preparation"] = json.loads(
        docker.exec(
            name("seed"),
            ["python", "-m", "tools.imp03_shared.supervisor", "--input", "/operator/inputs.json"],
            root=True,
        )
    )
    private_write(private / "volume-preparation.json", json.dumps(result, indent=2))
    return result


def dependencies(private: Path) -> Record:
    inputs = cast(Record, json.loads((private / "inputs.json").read_text()))
    pins = cast(Record, cast(Record, inputs["binding"])["pins"])
    for role in ROLE_UID:
        create(
            role + "-agent",
            ["-config", "/config/agent.conf"],
            [
                mount(role + "-agent", "/config", readonly=True),
                mount(role + "-svid", "/run/spire/sockets"),
            ],
            uid=0,
            image=str(pins["spire_image"]),
            network="kind",
            tmpfs=["/run/spire/data:rw,noexec,nosuid,size=16m,mode=0700"],
        )
        docker.start(name(role + "-agent"))
    create(
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
        uid=22000,
        groups=["22999"],
    )
    docker.start(name("fence"))
    node = verify_cluster()
    continuation = ACTIVE.name == "continuation-001"
    if continuation:
        from .continuation import start_database

        start_database()
    for suffix, uid, app_uid, port in [
        ("identity-db", 22041, 22011, PG_NODEPORT),
        ("identity-provider", 22041, 22011, 30443),
        ("data-db", 22042, 22013, PG_NODEPORT),
    ]:
        path = ROOT + "/connectors/" + suffix
        database_connector = suffix != "identity-provider"
        target = "172.29.35.10" if continuation and database_connector else node
        target_port = 5432 if continuation and database_connector else port
        create(
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
                str(target_port),
                "--allowed-uid",
                str(app_uid),
                "--allowed-uid",
                "0",
                "--access-gid",
                str(app_uid),
            ],
            [mount(suffix, path)],
            uid=uid,
            network=PREFIX + "-database" if continuation and database_connector else "kind",
            ip=("172.29.35.11" if suffix == "identity-db" else "172.29.35.12")
            if continuation and database_connector
            else None,
            groups=[str(app_uid)],
        )
        docker.start(name(suffix + "-connector"))
        wait_socket(name(suffix + "-connector"), path + "/forward.sock")
    addresses: list[str] = []
    for suffix in ("identity-db", "data-db"):
        settings = cast(
            Record, docker.inspect_container(name(suffix + "-connector"))["NetworkSettings"]
        )
        networks = cast(dict[str, Record], settings["Networks"])
        network = PREFIX + "-database" if continuation else "kind"
        addresses.append(cast(str, networks[network]["IPAddress"]))
    if not continuation:
        postgres_access(addresses)
    return {"connector_addresses": addresses, "shared_node": node}


def configuration_mounts(*, readonly: bool = False) -> list[str]:
    return [mount("operator", CONFIG, readonly=readonly)] + [
        mount(role + "-config", CONFIG + "/" + role, readonly=readonly) for role in ROLE_UID
    ]


def provision(private: Path) -> Record:
    create(
        "operator-seed",
        ["python", "-c", "import time;time.sleep(7200)"],
        configuration_mounts() + [mount("data-db", ROOT + "/connectors/data-db", readonly=True)],
        uid=0,
        cap_add=["CHOWN", "DAC_OVERRIDE"],
    )
    docker.start(name("operator-seed"))
    script = (
        "import json;from pathlib import Path;"
        "from tools.imp03_shared.relay import ThreadedLoopbackBridge;"
        "from tools.imp03_runtime.provision import provision;"
        "from tools.imp03_runtime.config import load;"
        f"b=ThreadedLoopbackBridge(Path('{ROOT}/connectors/data-db/forward.sock'),5432,server_uid=22042);"
        "b.start();"
        f"provision(Path('{CONFIG}'),load(Path('{CONFIG}/admin.json')));b.close();"
        "print(json.dumps({'provisioned':True,'existing_state_adopted':False}))"
    )
    result = json.loads(docker.exec(name("operator-seed"), ["python", "-c", script], root=True))
    private_write(private / "provision-result.json", json.dumps(result))
    return result


def applications(private: Path) -> Record:
    inputs = cast(Record, json.loads((private / "inputs.json").read_text()))
    pins = cast(Record, cast(Record, inputs["binding"])["pins"])
    for role, uid in ROLE_UID.items():
        auth_path = ROOT + "/" + role + "/authorization"
        create(
            role + "-authorization",
            [
                "python",
                "-m",
                "tools.imp03_runtime",
                "trust",
                "--role",
                "authorization",
                "--config",
                auth_path + "/config.json",
            ],
            [
                mount(role + "-authorization", auth_path),
                mount("fence", ROOT + "/fence", readonly=True),
            ],
            uid=AUTH_UID[role],
            groups=["22002", "22999"],
        )
        docker.start(name(role + "-authorization"))
        base_mounts = [
            mount(role + "-config", CONFIG + "/" + role),
            mount(role + "-backend", ROOT + "/" + role + "/backend"),
            mount(role + "-outbound", ROOT + "/" + role + "/outbound", readonly=True),
            mount("fence", ROOT + "/fence", readonly=True),
        ]
        args = ["python", "-m", "tools.imp03_shared.relay", "run", "--root", CONFIG, "--role", role]
        if role == "pdp":
            base_mounts.append(mount("opa", "/opt", readonly=True))
        for suffix, port, connector_uid in (
            [("identity-db", 5432, 22041), ("identity-provider", 20443, 22041)]
            if role == "identity"
            else [("data-db", 5432, 22042)]
            if role == "data"
            else []
        ):
            target = ROOT + "/connectors/" + suffix
            base_mounts.append(mount(suffix, target, readonly=True))
            args += ["--forward", str(port), str(connector_uid), target + "/forward.sock"]
        create(
            role + "-app",
            args,
            base_mounts,
            uid=uid,
            groups=["22002", "22999"],
            tmpfs=["/tmp:rw,noexec,nosuid,size=16m,mode=1777"],  # noqa: S108 - bounded container tmpfs
        )
        docker.start(name(role + "-app"))
        create(
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
                mount(role + "-authorization", auth_path, readonly=True),
                mount(role + "-svid", ROOT + "/" + role + "/spire", readonly=True),
            ],
            uid=22002,
            image=str(pins["envoy_image"]),
            network=MESH_NETWORK,
            ip=MESH_IP[role],
            pid=name(role + "-agent"),
        )
        docker.start(name(role + "-proxy"))
    create(
        "ingress",
        [
            "python",
            "-m",
            "tools.imp03_shared.relay",
            "ingress",
            "--listen-port",
            str(ACTIVE.browser_port),
            "--target-host",
            MESH_IP["core"],
            "--target-port",
            str(ACTIVE.browser_port),
        ],
        [],
        network=INGRESS_NETWORK,
        publish=[f"127.0.0.1:{ACTIVE.browser_port}:{ACTIVE.browser_port}"],
    )
    docker.connect_network(name("ingress"), MESH_NETWORK)
    docker.start(name("ingress"))
    return {
        "applications_started": list(ROLE_UID),
        "browser_origin": ACTIVE.main_origin,
        "trust_qualification": "pending",
    }
