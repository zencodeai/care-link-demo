"""Exact role routes and Envoy configuration, generated without live activation."""

from care_link_workload_trust import (
    BrowserListener,
    OutboundListener,
    PeerRule,
    ProxyInputs,
    add_browser,
    add_outbound,
    build_envoy,
)

from .model import NAMESPACE, LabInputs

AUTH_ROUTES = frozenset(
    {
        ("GET", "/v1/auth/csrf"),
        ("POST", "/v1/auth/login"),
        ("GET", "/v1/auth/callback"),
        ("GET", "/v1/auth/session"),
        ("POST", "/v1/auth/logout"),
        ("POST", "/v1/auth/step-up"),
        ("POST", "/v1/auth/step-up/confirm"),
        ("GET", "/v1/auth/step-up/proof"),
    }
)
HELP_ROUTES = frozenset(
    ("POST", "/internal/v1/identity/" + suffix)
    for suffix in ("help-authorize", "help-browser-context", "help-browser-proof")
)


def rules() -> tuple[PeerRule, ...]:
    return tuple(
        PeerRule(
            "spiffe://care-link.demo/lab/" + role,
            frozenset((method, "/bff/" + role + path) for method, path in AUTH_ROUTES)
            | (HELP_ROUTES if role == "help" else frozenset()),
        )
        for role in ("main", "help")
    ) + (
        PeerRule(
            "spiffe://care-link.demo/lab/identity_provider",
            frozenset({("POST", "/internal/v1/identity/signals")}),
        ),
    )


def identity(inputs: LabInputs, bind_address: str) -> dict[str, object]:
    config = build_envoy(
        ProxyInputs(
            "spiffe://care-link.demo/lab/identity",
            rules(),
            "127.0.0.1" if bind_address == "0.0.0.0" else bind_address,  # noqa: S104
            8443,
            "/run/care-link/backend/app.sock",
            "/run/care-link/authorization/authz.sock",
            "/run/spire/sockets/agent.sock",
            inputs.image("envoy"),
            "1.40.2",
            inputs.image("spire_agent"),
            "1.16.0",
            300,
        )
    )
    if bind_address == "0.0.0.0":  # noqa: S104 - fixed TLS port in restricted non-host-network pod
        config["static_resources"]["listeners"][0]["address"]["socket_address"]["address"] = (
            bind_address
        )
    config["admin"] = {
        "address": {"pipe": {"path": "/run/care-link/admin/admin.sock", "mode": 0o600}},
        "access_log": [],
    }
    return config


def browser(
    inputs: LabInputs, role: str, *, upstream: str | None = None, upstream_port: int = 8443
) -> dict[str, object]:
    if role not in {"main", "help"}:
        raise ValueError("explicit browser role required")
    port = 18443 if role == "main" else 19443
    # Reuse the reviewed static cluster builder for the two protected local UDSs;
    # this role has no inbound mesh listener or ext_authz bypass path.
    config = identity(inputs, "127.0.0.1")
    config["node"]["id"] = "spiffe://care-link.demo/lab/" + role
    resources = config["static_resources"]
    resources["listeners"] = []
    resources["clusters"] = [
        item for item in resources["clusters"] if item["name"] in {"application", "spire_agent"}
    ]
    config = add_browser(
        config,
        BrowserListener(
            f"https://{role}.localhost:{port}",
            "0.0.0.0",  # noqa: S104 - pod-only TLS listener, loopback NodePort publication
            8444,
            "/config/" + role + ".crt",
            "/config/" + role + ".key",
        ),
    )
    outgoing = frozenset((method, "/bff/" + role + path) for method, path in AUTH_ROUTES)
    if role == "help":
        outgoing |= HELP_ROUTES
    result = add_outbound(
        config,
        OutboundListener(
            "spiffe://care-link.demo/lab/" + role,
            "spiffe://care-link.demo/lab/identity",
            upstream or f"identity.{NAMESPACE}.svc.cluster.local",
            upstream_port,
            "/run/care-link/outbound/proxy.sock",
            outgoing,
        ),
    )
    # This lab qualifies IPv4 only. Docker's node name also resolves to an
    # unqualified AAAA address; do not let STRICT_DNS select that alternate path.
    for cluster in result["static_resources"]["clusters"]:
        if cluster["name"] == "identity_mesh":
            cluster["dns_lookup_family"] = "V4_ONLY"
    return result


def authorization_config() -> dict[str, object]:
    return {
        "socket": "/run/care-link/authorization/authz.sock",
        "proxy_uid": 21002,
        "proxy_gid": 21002,
        "fence_socket": "/run/care-link/fence/fence.sock",
        "fence_owner_uid": 21000,
        "local_spiffe_id": "spiffe://care-link.demo/lab/identity",
        "trust_bundle": "/config/bundle.crt",
        "rules": [{"spiffe_id": rule.spiffe_id, "routes": sorted(rule.routes)} for rule in rules()],
    }


def fence_config() -> dict[str, object]:
    return {
        "socket": "/run/care-link/fence/fence.sock",
        "ledger_directory": "/run/care-link/ledger",
        "access_gid": 21999,
        "read_uids": [21003, 21012, 21013],
        "restrict_uid": 21011,
        "allowed": [
            "spiffe://care-link.demo/lab/" + role
            for role in ("identity", "main", "help", "identity_provider")
        ],
        "initialize": True,
    }
