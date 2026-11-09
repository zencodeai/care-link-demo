"""Fail-closed Envoy v3/SPIRE SDS source builder; never installs or activates."""

import ipaddress
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .verification import IDENTITY, PeerRule

IMAGE = re.compile(r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


@dataclass(frozen=True)
class ProxyInputs:
    local_spiffe_id: str
    peers: tuple[PeerRule, ...]
    bind_address: str
    listener_port: int
    backend_socket: str
    authorization_socket: str
    spire_socket: str
    envoy_image: str
    envoy_version: str
    spire_image: str
    spire_version: str
    svid_ttl_seconds: int

    def __post_init__(self) -> None:
        if IDENTITY.fullmatch(self.local_spiffe_id) is None or not self.peers:
            raise ValueError("exact local/peer SPIFFE identity required")
        address = ipaddress.ip_address(self.bind_address)
        if (
            address.version != 4
            or address.is_unspecified
            or not address.is_private
            or not 1024 <= self.listener_port <= 65535
        ):
            raise ValueError("qualified private IPv4 listener required")
        if len({self.backend_socket, self.authorization_socket, self.spire_socket}) != 3:
            raise ValueError("distinct protected sockets required")
        for path in (self.backend_socket, self.authorization_socket, self.spire_socket):
            if not PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                raise ValueError("fixed absolute Unix sockets required")
        if not all(
            IMAGE.fullmatch(image) for image in (self.envoy_image, self.spire_image)
        ) or not all(
            VERSION.fullmatch(version) for version in (self.envoy_version, self.spire_version)
        ):
            raise ValueError("explicit immutable image digests and version pins required")
        if not 30 <= self.svid_ttl_seconds <= 3600:
            raise ValueError("explicit measured SVID TTL required")


def _cluster(name: str, path: str, http2: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "name": name,
        "type": "STATIC",
        "connect_timeout": "0.25s",
        "load_assignment": {
            "cluster_name": name,
            "endpoints": [{"lb_endpoints": [{"endpoint": {"address": {"pipe": {"path": path}}}}]}],
        },
    }
    if http2:
        result["typed_extension_protocol_options"] = {
            "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": {
                "@type": (
                    "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions"
                ),
                "explicit_http_config": {"http2_protocol_options": {}},
            }
        }
    return result


def build_envoy(inputs: ProxyInputs) -> dict[str, object]:
    sds: dict[str, object] = {
        "resource_api_version": "V3",
        "api_config_source": {
            "api_type": "GRPC",
            "transport_api_version": "V3",
            "grpc_services": [{"envoy_grpc": {"cluster_name": "spire_agent"}}],
        },
    }
    exact_routes = sorted({pair for peer in inputs.peers for pair in peer.routes})
    routes = [
        {
            "match": {
                "path": path,
                "headers": [{"name": ":method", "string_match": {"exact": method}}],
            },
            "route": {
                "cluster": "application",
                "timeout": "40s" if path.startswith("/bff/") else "10s",
            },
            "request_headers_to_remove": [
                "x-forwarded-client-cert",
                "x-forwarded-for",
                "x-forwarded-host",
                "x-forwarded-proto",
            ],
        }
        for method, path in exact_routes
    ]
    # Header mutation precedes ext_authz. Protected response headers are minted
    # only by the local auth listener and cannot be supplied by a remote caller.
    hcm = {
        "@type": (
            "type.googleapis.com/envoy.extensions.filters.network."
            "http_connection_manager.v3.HttpConnectionManager"
        ),
        "stat_prefix": "private_workload",
        "codec_type": "AUTO",
        "normalize_path": True,
        "merge_slashes": False,
        "path_with_escaped_slashes_action": "REJECT_REQUEST",
        "use_remote_address": True,
        "forward_client_cert_details": "SANITIZE_SET",
        "set_current_client_cert_details": {"cert": True, "chain": True, "uri": True},
        "common_http_protocol_options": {
            "headers_with_underscores_action": "REJECT_REQUEST",
            "idle_timeout": "60s",
        },
        "request_headers_timeout": "2s",
        "request_timeout": "45s",
        "max_request_headers_kb": 32,
        "route_config": {
            "name": "exact_private_routes",
            "virtual_hosts": [{"name": "private", "domains": ["*"], "routes": routes}],
        },
        "http_filters": [
            {
                "name": "envoy.filters.http.header_mutation",
                "typed_config": {
                    "@type": (
                        "type.googleapis.com/envoy.extensions.filters.http."
                        "header_mutation.v3.HeaderMutation"
                    ),
                    "mutations": {
                        "request_mutations": [
                            {"remove": "x-care-link-verified-spiffe"},
                            {"remove": "x-care-link-fence-generation"},
                            {"remove": "x-care-link-certificate-expires-at"},
                        ]
                    },
                },
            },
            {
                "name": "envoy.filters.http.ext_authz",
                "typed_config": {
                    "@type": (
                        "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz"
                    ),
                    "failure_mode_allow": False,
                    "clear_route_cache": False,
                    "validate_mutations": True,
                    "http_service": {
                        "server_uri": {
                            "uri": "http://workload-authorization",
                            "cluster": "workload_authorization",
                            "timeout": "0.25s",
                        },
                        "authorization_request": {
                            "allowed_headers": {"patterns": [{"exact": "x-forwarded-client-cert"}]}
                        },
                        "authorization_response": {
                            "allowed_upstream_headers": {
                                "patterns": [
                                    {"exact": "x-care-link-verified-spiffe"},
                                    {"exact": "x-care-link-fence-generation"},
                                    {"exact": "x-care-link-certificate-expires-at"},
                                ]
                            }
                        },
                    },
                },
            },
            {
                "name": "envoy.filters.http.router",
                "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"
                },
            },
        ],
    }
    tls = {
        "@type": (
            "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext"
        ),
        "require_client_certificate": True,
        "common_tls_context": {
            "tls_params": {
                "tls_minimum_protocol_version": "TLSv1_3",
                "tls_maximum_protocol_version": "TLSv1_3",
            },
            "tls_certificate_sds_secret_configs": [
                {"name": inputs.local_spiffe_id, "sds_config": sds}
            ],
            "combined_validation_context": {
                "default_validation_context": {
                    "match_typed_subject_alt_names": [
                        {"san_type": "URI", "matcher": {"exact": rule.spiffe_id}}
                        for rule in inputs.peers
                    ]
                },
                "validation_context_sds_secret_config": {
                    "name": "spiffe://care-link.demo",
                    "sds_config": sds,
                },
            },
        },
    }
    return {
        "node": {"id": inputs.local_spiffe_id, "cluster": "care-link-imp02-002"},
        "static_resources": {
            "listeners": [
                {
                    "name": "private_mtls",
                    "address": {
                        "socket_address": {
                            "address": inputs.bind_address,
                            "port_value": inputs.listener_port,
                        }
                    },
                    "filter_chains": [
                        {
                            "transport_socket": {
                                "name": "envoy.transport_sockets.tls",
                                "typed_config": tls,
                            },
                            "filters": [
                                {
                                    "name": "envoy.filters.network.http_connection_manager",
                                    "typed_config": hcm,
                                }
                            ],
                        }
                    ],
                }
            ],
            "clusters": [
                _cluster("application", inputs.backend_socket),
                _cluster("workload_authorization", inputs.authorization_socket),
                _cluster("spire_agent", inputs.spire_socket, True),
            ],
        },
    }


def spire_registration(
    inputs: ProxyInputs,
    *,
    parent_spiffe_id: str,
    namespace: str,
    service_account: str,
    proxy_container_name: str,
    workload_image: str,
) -> dict[str, object]:
    """One candidate entry binding proxy image AND admitted application lineage.

    These selectors must be observed from the pinned attestor on the actual lab;
    namespace labels or IP addresses are never sufficient substitutions.
    """
    name = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
    if (
        not parent_spiffe_id.startswith("spiffe://care-link.demo/spire/agent/")
        or not all(name.fullmatch(x) for x in (namespace, service_account, proxy_container_name))
        or IMAGE.fullmatch(workload_image) is None
    ):
        raise ValueError(
            "attested parent, exact namespace/account/container and image digest required"
        )
    return {
        "spiffe_id": inputs.local_spiffe_id,
        "parent_id": parent_spiffe_id,
        "ttl": inputs.svid_ttl_seconds,
        "selectors": [
            f"k8s:ns:{namespace}",
            f"k8s:sa:{service_account}",
            f"k8s:container-name:{proxy_container_name}",
            f"k8s:container-image:{inputs.envoy_image}",
            f"k8s:pod-image:{workload_image}",
        ],
    }
