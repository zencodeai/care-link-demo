"""Bound existing continuation mesh connection pools without changing routes."""

import copy
import hashlib
import json
import time
from typing import cast

from . import docker
from .continuation import require_profile
from .deployment import create, name
from .infrastructure import private_write
from .model import PRIVATE, ROLE_UID, ROOT, Record, mount


def bounded(config: Record, seconds: int) -> tuple[Record, list[str]]:
    result = copy.deepcopy(config)
    resources = cast(Record, result["static_resources"])
    names: list[str] = []
    for cluster in cast(list[Record], resources["clusters"]):
        socket = cast(Record, cluster.get("transport_socket", {}))
        typed = cast(Record, socket.get("typed_config", {}))
        if not str(typed.get("@type", "")).endswith(".UpstreamTlsContext"):
            continue
        tls = cast(Record, typed.get("common_tls_context", {}))
        if "tls_certificate_sds_secret_configs" not in tls:
            raise ValueError("Existing SDS workload credentials required")
        options = cast(Record, cluster.setdefault("common_http_protocol_options", {}))
        options["max_connection_duration"] = f"{seconds}s"
        names.append(str(cluster["name"]))
    return result, names


def apply() -> Record:
    require_profile()
    inputs = json.loads((PRIVATE / "inputs.json").read_text())
    seconds = max(1, min(60, inputs["binding"]["pins"]["svid_ttl_seconds"] // 3))
    helper = name("pool-maintenance-seed")
    create(
        "pool-maintenance-seed",
        ["python", "-c", "import time;time.sleep(900)"],
        [mount(role + "-proxy", "/proxy-configs/" + role) for role in ROLE_UID],
        uid=22002,
        image=str(docker.inspect_container(name("core-app"))["Image"]),
    )
    docker.start(helper)
    result: Record = {
        "maximum_connection_seconds": seconds,
        "routes_or_identity_rules_changed": False,
        "issuer_policy_or_fences_changed": False,
        "roles": [],
    }
    roles: list[Record] = []
    try:
        values = cast(
            dict[str, Record],
            json.loads(
                docker.exec(
                    helper,
                    [
                        "python",
                        "-c",
                        "import json;from pathlib import Path;"
                        "print(json.dumps({p.parent.name:json.loads(p.read_text()) "
                        "for p in Path('/proxy-configs').glob('*/envoy.json')}))",
                    ],
                )
            ),
        )
        if set(values) != set(ROLE_UID):
            raise ValueError("All five exact continuation proxy configurations required")
        for role, config in values.items():
            original = json.dumps(config, sort_keys=True)
            backup = PRIVATE / ("pool-before-" + role + ".json")
            private_write(backup, original)
            updated, clusters = bounded(config, seconds)
            script = (
                "import os,sys;from pathlib import Path;"
                f"p=Path('/proxy-configs/{role}/envoy.pool-candidate.json');"
                "f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);"
                "o=os.fdopen(f,'w');o.write(sys.stdin.read());o.flush();os.fsync(o.fileno());o.close()"
            )
            docker.exec(helper, ["python", "-c", script], stdin=json.dumps(updated))
            docker.exec(
                name(role + "-proxy"),
                [
                    "envoy",
                    "--mode",
                    "validate",
                    "-c",
                    ROOT + "/" + role + "/proxy/envoy.pool-candidate.json",
                ],
            )
            roles.append(
                {
                    "role": role,
                    "cluster_names": clusters,
                    "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
                    "after_sha256": hashlib.sha256(
                        json.dumps(updated, sort_keys=True).encode()
                    ).hexdigest(),
                    "envoy_validation": "passed",
                }
            )
        for role in ROLE_UID:
            docker.exec(
                helper,
                [
                    "python",
                    "-c",
                    "import os;from pathlib import Path;"
                    + f"p=Path('/proxy-configs/{role}');"
                    + "os.replace(p/'envoy.pool-candidate.json',p/'envoy.json');"
                    + "f=os.open(p,os.O_RDONLY|os.O_DIRECTORY);os.fsync(f);os.close(f)",
                ],
            )
        for role in ROLE_UID:
            target = name(role + "-proxy")
            before = docker.inspect_container(target)
            docker.stop(target)
            docker.start(target)
            for _ in range(20):
                after = docker.inspect_container(target)
                if cast(Record, after["State"])["Running"]:
                    break
                time.sleep(0.2)
            if before["Id"] != after["Id"] or not cast(Record, after["State"])["Running"]:
                raise RuntimeError("Exact proxy restart did not complete")
        result["roles"] = roles
        return result
    finally:
        docker.stop(helper)
        docker.remove_owned(helper)


if __name__ == "__main__":
    print(json.dumps(apply(), indent=2))
