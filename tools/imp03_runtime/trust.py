"""Exact independent fence and authorization custody entrypoints."""

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

from .config import Record, integer, record, text


def serve(role: str, config: Record) -> None:
    if config.get("session") != "imp03-002" or integer(config, "uid") != os.geteuid():
        raise ValueError("Exact IMP-03 trust custodian required")
    server: socketserver.BaseServer
    if role == "fence":
        store = FenceStore(Path(text(config, "ledger_directory")), os.geteuid())
        allowed = frozenset(cast(list[str], config["allowed"]))
        if (store.directory / store.filename).exists():
            if store.read().allowed != allowed:
                raise ValueError("Current fence admission differs from configured candidate")
        else:
            store.initialize(allowed)
        server = FenceServer(
            Path(text(config, "socket")),
            store,
            owner_uid=os.geteuid(),
            access_gid=integer(config, "access_gid"),
            read_uids=frozenset(cast(list[int], config["read_uids"])),
            restrict_uid=integer(config, "restrict_uid"),
        )
    elif role == "authorization":
        rules = tuple(
            PeerRule(
                text(item, "spiffe_id"),
                frozenset((pair[0], pair[1]) for pair in cast(list[list[str]], item["routes"])),
            )
            for item in (record(value) for value in cast(list[object], config["rules"]))
        )
        enforcer = WorkloadEnforcer(
            integer(config, "proxy_uid"),
            tuple(x509.load_pem_x509_certificates(Path(text(config, "trust_bundle")).read_bytes())),
            rules,
            UnixFenceClient(Path(text(config, "fence_socket")), integer(config, "fence_uid")),
            local_spiffe_id=text(config, "local_spiffe_id"),
        )
        server = AuthorizationServer(
            Path(text(config, "socket")), enforcer, os.geteuid(), integer(config, "proxy_uid")
        )
    else:
        raise ValueError("Unknown trust role")
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
