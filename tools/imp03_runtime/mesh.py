"""Render exact SPIRE/Envoy mesh configuration; no cluster or listener activation."""

import json
from pathlib import Path
from typing import cast

from care_link_workload_trust import (
    BrowserListener,
    OutboundListener,
    PeerRule,
    ProxyInputs,
    add_browser,
    add_outbound,
    build_envoy,
)

from .config import (
    FENCE_READER_GID,
    FENCE_RESTRICT_UID,
    ROLES,
    Record,
    integer,
    record,
    routes,
    spiffe,
    text,
)
from .prepare import write


def rename(value: object, suffix: str) -> object:
    if isinstance(value, dict):
        return {key: rename(item, suffix) for key, item in cast(Record, value).items()}
    if isinstance(value, list):
        return [rename(item, suffix) for item in cast(list[object], value)]
    if value in ("identity_mesh", "protected_egress", "pinned_egress"):
        return str(value) + "_" + suffix
    return value


def render(binding: Record, output: Path) -> None:
    output.mkdir(mode=0o700, exist_ok=False)
    pins, mesh, roles = record(binding["pins"]), record(binding["mesh"]), record(binding["roles"])
    for role in ROLES:
        cfg, target = record(roles[role]), record(mesh[role])
        peers = tuple(PeerRule(spiffe(peer), pairs) for peer, pairs in routes(role).items())
        inputs = ProxyInputs(
            spiffe(role),
            peers,
            text(target, "address"),
            integer(target, "port"),
            text(cfg, "backend_socket"),
            text(target, "authorization_socket"),
            text(target, "spire_socket"),
            text(pins, "envoy_image"),
            text(pins, "envoy_version"),
            text(pins, "spire_image"),
            text(pins, "spire_version"),
            integer(pins, "svid_ttl_seconds"),
        )
        result = build_envoy(inputs)
        record(result["node"])["cluster"] = "care-link-imp03-002"
        for destination, raw in record(cfg["outbound"]).items():
            remote, dest = record(raw), record(mesh[destination])
            updated = add_outbound(
                result,
                OutboundListener(
                    spiffe(role),
                    spiffe(destination),
                    text(dest, "address"),
                    integer(dest, "port"),
                    text(remote, "socket"),
                    routes(destination)[role],
                ),
            )
            # The public builder emits a single named egress; rename only the newly
            # added resources so multiple exact destinations remain independent.
            resources = record(updated["static_resources"])
            listeners = cast(list[object], resources["listeners"])
            listeners[-1] = rename(listeners[-1], destination)
            clusters = cast(list[object], resources["clusters"])
            # A TLS handshake does not renew an existing pooled connection.
            # Recycle mesh pools well inside the configured SVID lifetime;
            # per-request expiry and fence enforcement remain authoritative.
            pool_seconds = max(1, min(60, integer(pins, "svid_ttl_seconds") // 3))
            record(clusters[-1])["common_http_protocol_options"] = {
                "max_connection_duration": f"{pool_seconds}s"
            }
            clusters[-1] = rename(clusters[-1], destination)
            result = updated
        if role == "core":
            browser = record(binding["browser_tls"])
            result = add_browser(
                result,
                BrowserListener(
                    text(binding, "main_origin"),
                    text(browser, "address"),
                    integer(browser, "port"),
                    text(browser, "certificate"),
                    text(browser, "private_key"),
                ),
            )

        authorization: Record = {
            "session": "imp03-002",
            "uid": integer(target, "authorization_uid"),
            "socket": text(target, "authorization_socket"),
            "trust_bundle": text(target, "trust_bundle"),
            "proxy_uid": integer(cfg, "proxy_uid"),
            "local_spiffe_id": spiffe(role),
            "fence_socket": text(cfg, "fence_socket"),
            "fence_uid": integer(cfg, "fence_uid"),
            "rules": [
                {"spiffe_id": spiffe(peer), "routes": sorted(pairs)}
                for peer, pairs in routes(role).items()
            ],
        }
        write(
            output / (role + "-authorization.json"),
            (json.dumps(authorization, indent=2) + "\n").encode(),
        )
        write(output / (role + "-envoy.json"), (json.dumps(result, indent=2) + "\n").encode())

    first = record(roles["identity"])
    fence: Record = {
        "session": "imp03-002",
        "uid": integer(first, "fence_uid"),
        "socket": text(first, "fence_socket"),
        "ledger_directory": str(Path(text(first, "fence_socket")).parent / "ledger"),
        "access_gid": FENCE_READER_GID,
        "restrict_uid": FENCE_RESTRICT_UID,
        "read_uids": sorted(
            {integer(record(roles[role]), "uid") for role in ROLES}
            | {integer(record(mesh[role]), "authorization_uid") for role in ROLES}
        ),
        "allowed": sorted(spiffe(role) for role in ROLES),
    }
    write(output / "fence.json", (json.dumps(fence, indent=2) + "\n").encode())


def configure_review_browser(config: Record, domain: str) -> None:
    """Opt-in review routing; exact actor origins remain enforced by the BFF."""
    if domain != "qualification.localhost":
        raise ValueError("Explicit continuation review domain required")
    changed: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            node = record(cast(object, value))
            for raw in cast(list[object], node.get("virtual_hosts", [])):
                host = record(raw)
                if host.get("name") != "browser":
                    continue
                domains = cast(list[str], host["domains"])
                port = domains[0].rsplit(":", 1)[1]
                host["domains"] = sorted(set(domains + ["*." + domain + ":" + port]))
                routes = cast(list[Record], host["routes"])
                stream = {
                    "match": {"path": "/v1/review/events"},
                    "route": {**record(routes[-1]["route"]), "timeout": "0s"},
                }
                host["routes"] = [stream, *routes]
                changed.append("browser")
            for child in node.values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[object], value):
                visit(child)

    visit(config)
    if len(changed) != 1:
        raise ValueError("Exactly one reviewed browser listener required")
