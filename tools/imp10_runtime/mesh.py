"""Render an exact opt-in IMP-10 mesh without creating any runtime resources."""

import argparse
import ipaddress
import json
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from care_link_workload_trust import (
    BrowserListener,
    OutboundListener,
    PeerRule,
    ProxyInputs,
    add_browser,
    add_outbound,
    build_envoy,
)

from tools.imp03_runtime.config import ROLES, Record, integer, load, protected_routes, record, text
from tools.imp03_runtime.mesh import rename
from tools.imp03_runtime.prepare import write
from tools.imp06_runtime.routes import inbound

from .serve import PROTECTED_PROFILE

RouteSet = frozenset[tuple[str, str]]
NO_PRIVATE_LISTENER = frozenset({"runtime", "help"})
FEATURE_ROLES = {
    "assisted": {"runtime", "inference", "host-inference-bridge"},
    "training": {"training"},
    "referral": {"receiver"},
    "help": {"help"},
}
PINS = {"envoy_image", "envoy_version", "spire_image", "spire_version", "svid_ttl_seconds"}
PRIVATE_FIELDS = {
    "address",
    "port",
    "backend_socket",
    "authorization_socket",
    "authorization_uid",
    "trust_bundle",
    "proxy_uid",
    "fence_socket",
    "fence_uid",
}


def _identity(role: str) -> str:
    return f"spiffe://care-link.demo/demo/{role}"


def _shape(value: object, required: set[str], *, optional: frozenset[str] = frozenset()) -> Record:
    result = record(value)
    if not required <= result.keys() <= required | optional:
        raise ValueError("Exact protected mesh configuration fields required")
    return result


def _absolute_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("Protected mesh paths must be absolute")
    return value


def _routes(features: Record, roles: set[str]) -> dict[str, dict[str, RouteSet]]:
    graph: dict[str, dict[str, RouteSet]] = {}
    app_config: Record = {
        "training_enabled": features["training"],
        "referral_enabled": features["referral"],
    }
    if features["help"]:
        app_config["help_identity"] = {}
    for destination in sorted(roles - NO_PRIVATE_LISTENER):
        if destination in {"inference", "host-inference-bridge"} or (
            features["assisted"] and destination in {"core", "data"}
        ):
            peers = {
                rule.spiffe_id.rsplit("/", 1)[1]: rule.routes
                for rule in inbound(destination, training_enabled=features["training"] is True)
            }
        else:
            peers = protected_routes(app_config, destination)
        if not peers.keys() <= roles:
            raise ValueError("Protected mesh route references an undeclared role")
        graph[destination] = peers
    return graph


def _browser(value: object) -> BrowserListener:
    binding = _shape(value, {"origin", "address", "port", "certificate", "private_key"})
    origin = text(binding, "origin")
    url = urlsplit(origin)
    address = ipaddress.ip_address(text(binding, "address"))
    certificate, key = (
        _absolute_path(text(binding, name)) for name in ("certificate", "private_key")
    )
    if (
        url.scheme != "https"
        or not url.hostname
        or url.hostname.endswith(".")
        or url.username is not None
        or url.path
        or url.query
        or url.fragment
        or origin != "https://" + url.netloc
        or address.version != 4
        or not address.is_private
        or address.is_unspecified
        or certificate == key
    ):
        raise ValueError("A private HTTPS browser endpoint with distinct TLS files is required")
    return BrowserListener(origin, str(address), integer(binding, "port"), certificate, key)


def _browser_surface(envoy: Record, browser: BrowserListener) -> Record:
    result = add_browser(envoy, browser)
    listener = cast(list[Record], record(result["static_resources"])["listeners"])[-1]
    chain = cast(list[Record], listener["filter_chains"])[0]
    manager = record(cast(list[Record], chain["filters"])[0]["typed_config"])
    host = cast(list[Record], record(manager["route_config"])["virtual_hosts"])[0]
    host["routes"] = [
        {"match": {field: path}, "direct_response": {"status": 403}}
        for field, path in (("path", "/internal"), ("prefix", "/internal/"))
    ] + cast(list[Record], host["routes"])
    return result


def _render_role(
    role: str,
    roles: dict[str, Record],
    graph: dict[str, dict[str, RouteSet]],
    pins: Record,
) -> dict[str, Record]:
    binding = roles[role]
    peers = graph.get(role, {})
    private = role not in NO_PRIVATE_LISTENER
    egress = {name: peer[role] for name, peer in graph.items() if role in peer}
    sockets = _shape(binding["outbound"], set(egress))
    paths = [_absolute_path(text(sockets, dest)) for dest in egress]
    paths.append(_absolute_path(text(binding, "spire_socket")))
    if role != "runtime":
        paths.append(_absolute_path(text(binding, "backend_socket")))
    if private:
        paths.extend(
            _absolute_path(text(binding, name)) for name in ("authorization_socket", "fence_socket")
        )
    if len(set(paths)) != len(paths):
        raise ValueError("Role-local socket paths must be distinct")
    rules = tuple(PeerRule(_identity(peer), route) for peer, route in sorted(peers.items()))
    # The base renderer needs a private listener to build the SDS and app clusters.
    # For egress-only roles, discard the scaffold before exporting any config.
    unused = f"/run/care-link-unbound/{role}"
    ttl = integer(pins, "svid_ttl_seconds")
    inputs = ProxyInputs(
        _identity(role),
        rules or (PeerRule(_identity(role), frozenset({("GET", "/dev/health")})),),
        text(binding, "address") if private else "127.0.0.1",
        integer(binding, "port") if private else 8443,
        text(binding, "backend_socket") if role != "runtime" else unused + "/backend.sock",
        text(binding, "authorization_socket") if private else unused + "/authorization.sock",
        text(binding, "spire_socket"),
        text(pins, "envoy_image"),
        text(pins, "envoy_version"),
        text(pins, "spire_image"),
        text(pins, "spire_version"),
        ttl,
    )
    envoy = build_envoy(inputs)
    record(envoy["node"])["cluster"] = PROTECTED_PROFILE
    if not private:
        resources = record(envoy["static_resources"])
        resources["listeners"] = []
        groups = {"application", "spire_agent"} if role == "help" else {"spire_agent"}
        resources["clusters"] = [
            group for group in cast(list[Record], resources["clusters"]) if group["name"] in groups
        ]
    for destination, allowed in egress.items():
        target = roles[destination]
        envoy = add_outbound(
            envoy,
            OutboundListener(
                _identity(role),
                _identity(destination),
                text(target, "dial_address" if "dial_address" in target else "address"),
                integer(target, "port"),
                text(sockets, destination),
                allowed,
            ),
        )
        resources = record(envoy["static_resources"])
        listeners = cast(list[object], resources["listeners"])
        clusters = cast(list[object], resources["clusters"])
        listeners[-1] = rename(listeners[-1], destination)
        record(clusters[-1])["common_http_protocol_options"] = {
            "max_connection_duration": f"{max(1, min(60, ttl // 3))}s"
        }
        clusters[-1] = rename(clusters[-1], destination)

    if "browser" in binding:
        browser = _browser(binding["browser"])
        if private and (browser.address, browser.port) == (
            inputs.bind_address,
            inputs.listener_port,
        ):
            raise ValueError("Browser and private workload listeners require distinct endpoints")
        envoy = _browser_surface(envoy, browser)
    rendered = {role + "-envoy.json": envoy}
    if private:
        uid, proxy, fence = (
            integer(binding, key) for key in ("authorization_uid", "proxy_uid", "fence_uid")
        )
        if 0 in (uid, proxy, fence) or len({uid, proxy, fence}) != 3:
            raise ValueError(
                "Mesh authorization, fence and proxy require distinct non-root custodians"
            )
        rendered[role + "-authorization.json"] = {
            "session": "imp03-002",
            "uid": uid,
            "socket": inputs.authorization_socket,
            "trust_bundle": _absolute_path(text(binding, "trust_bundle")),
            "proxy_uid": proxy,
            "local_spiffe_id": _identity(role),
            "fence_socket": text(binding, "fence_socket"),
            "fence_uid": fence,
            "rules": [
                {"spiffe_id": rule.spiffe_id, "routes": sorted(rule.routes)} for rule in rules
            ],
        }
    return rendered


def configurations(binding: Record) -> dict[str, Record]:
    _shape(binding, {"session", "features", "pins", "roles"})
    if binding["session"] != PROTECTED_PROFILE:
        raise ValueError("An explicit IMP-10 protected mesh profile is required")
    features = _shape(binding["features"], set(FEATURE_ROLES))
    if any(type(enabled) is not bool for enabled in features.values()):
        raise ValueError("Exact boolean mesh feature selections required")
    pins = _shape(binding["pins"], PINS)
    expected_roles: set[str] = set(ROLES)
    for feature, added in FEATURE_ROLES.items():
        if features[feature]:
            expected_roles |= added
    roles = {
        name: record(value) for name, value in _shape(binding["roles"], expected_roles).items()
    }
    common = {"spire_socket", "outbound"}
    for role, role_config in roles.items():
        if role == "runtime":
            _shape(role_config, common)
        elif role == "help":
            _shape(role_config, common | {"backend_socket", "browser"})
        else:
            required = common | PRIVATE_FIELDS
            if role == "core":
                required.add("browser")
            _shape(role_config, required, optional=frozenset({"dial_address"}))
    if "help" in roles and (
        urlsplit(_browser(roles["help"]["browser"]).origin).hostname
        == urlsplit(_browser(roles["core"]["browser"]).origin).hostname
    ):
        raise ValueError("Core and private Help require distinct browser hostnames")
    graph = _routes(features, expected_roles)
    rendered: dict[str, Record] = {}
    for role in sorted(roles):
        rendered.update(_render_role(role, roles, graph, pins))
    return rendered


def render(binding: Record, output: Path) -> None:
    rendered = configurations(binding)
    output.mkdir(mode=0o700, exist_ok=False)
    for name, data in rendered.items():
        write(output / name, (json.dumps(data, indent=2) + "\n").encode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.bindings.is_absolute():
        parser.error("An absolute owner-only bindings path is required")
    try:
        render(load(args.bindings), args.output)
    except (KeyError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
