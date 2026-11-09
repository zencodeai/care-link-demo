"""Explicit role entrypoints for native UDS authorization and fence custody."""

import argparse
import json
import os
import socketserver
from pathlib import Path
from typing import cast

from care_link_workload_trust import (
    AuthorizationServer,
    FenceServer,
    FenceStore,
    PeerRule,
    UnixFenceClient,
    WorkloadEnforcer,
)
from cryptography import x509


def _integer(config: dict[str, object], name: str) -> int:
    value = config[name]
    if type(value) is not int or value < 0:
        raise ValueError("explicit positive numeric identity required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("authorization", "fence"))
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = cast(dict[str, object], json.loads(args.config.read_text()))
    socket = Path(cast(str, config["socket"]))
    server: socketserver.BaseServer
    if args.role == "fence":
        store = FenceStore(Path(cast(str, config["ledger_directory"])), os.geteuid())
        if config.get("initialize") is True:
            if (store.directory / store.filename).exists():
                existing = store.read()
                if existing.allowed != frozenset(cast(list[str], config["allowed"])):
                    raise ValueError("existing fence admission differs from configured candidate")
            else:
                store.initialize(frozenset(cast(list[str], config["allowed"])))
        server = FenceServer(
            socket,
            store,
            owner_uid=os.geteuid(),
            access_gid=_integer(config, "access_gid"),
            read_uids=frozenset(cast(list[int], config["read_uids"])),
            restrict_uid=_integer(config, "restrict_uid"),
        )
    else:
        roots = x509.load_pem_x509_certificates(
            Path(cast(str, config["trust_bundle"])).read_bytes()
        )
        rules = tuple(
            PeerRule(
                cast(str, item["spiffe_id"]),
                frozenset((pair[0], pair[1]) for pair in cast(list[list[str]], item["routes"])),
            )
            for item in cast(list[dict[str, object]], config["rules"])
        )
        fences = UnixFenceClient(
            Path(cast(str, config["fence_socket"])), _integer(config, "fence_owner_uid")
        )
        local_identity = config["local_spiffe_id"]
        if not isinstance(local_identity, str) or not local_identity:
            raise ValueError("deployment authorizer requires exact local workload identity")
        enforcer = WorkloadEnforcer(
            _integer(config, "proxy_uid"),
            tuple(roots),
            rules,
            fences,
            local_spiffe_id=local_identity,
        )
        server = AuthorizationServer(socket, enforcer, os.geteuid(), _integer(config, "proxy_gid"))
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
