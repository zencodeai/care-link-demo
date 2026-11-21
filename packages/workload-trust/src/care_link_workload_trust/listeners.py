"""Explicit browser and local egress listeners around the protected mesh boundary."""

import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import urlsplit

from .verification import IDENTITY, TASK_ROUTES, canonical_route, envoy_path_match, route_timeout

HCM = (
    "type.googleapis.com/envoy.extensions.filters.network."
    "http_connection_manager.v3.HttpConnectionManager"
)
ROUTER = {
    "name": "envoy.filters.http.router",
    "typed_config": {"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"},
}
PROTECTED_HEADERS = [
    "x-forwarded-client-cert",
    "x-care-link-verified-spiffe",
    "x-care-link-fence-generation",
    "x-care-link-certificate-expires-at",
    "x-care-link-certificate-digest",
]


def _resources(config: dict[str, object]) -> dict[str, list[object]]:
    resources = config.setdefault("static_resources", {"listeners": [], "clusters": []})
    return cast(dict[str, list[object]], resources)


def _sds() -> dict[str, object]:
    return {
        "resource_api_version": "V3",
        "api_config_source": {
            "api_type": "GRPC",
            "transport_api_version": "V3",
            "grpc_services": [{"envoy_grpc": {"cluster_name": "spire_agent"}}],
        },
    }


@dataclass(frozen=True)
class BrowserListener:
    origin: str
    address: str
    port: int
    certificate: str
    private_key: str


def add_browser(config: dict[str, object], inputs: BrowserListener) -> dict[str, object]:
    origin = urlsplit(inputs.origin)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.path
        or origin.username
        or not 1024 <= inputs.port <= 65535
        or not inputs.address
    ):
        raise ValueError("fixed HTTPS browser origin/listener required")
    for path in (inputs.certificate, inputs.private_key):
        if not PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise ValueError("fixed mounted browser TLS keys required")
    result = deepcopy(config)
    resources = _resources(result)
    resources["listeners"].append(
        {
            "name": "browser_tls",
            "address": {"socket_address": {"address": inputs.address, "port_value": inputs.port}},
            "filter_chains": [
                {
                    "transport_socket": {
                        "name": "envoy.transport_sockets.tls",
                        "typed_config": {
                            "@type": (
                                "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3."
                                "DownstreamTlsContext"
                            ),
                            "common_tls_context": {
                                "tls_params": {
                                    "tls_minimum_protocol_version": "TLSv1_3",
                                    "tls_maximum_protocol_version": "TLSv1_3",
                                },
                                "tls_certificates": [
                                    {
                                        "certificate_chain": {"filename": inputs.certificate},
                                        "private_key": {"filename": inputs.private_key},
                                    }
                                ],
                            },
                        },
                    },
                    "filters": [
                        {
                            "name": "envoy.filters.network.http_connection_manager",
                            "typed_config": {
                                "@type": HCM,
                                "stat_prefix": "private_browser",
                                "normalize_path": True,
                                "path_with_escaped_slashes_action": "REJECT_REQUEST",
                                "forward_client_cert_details": "SANITIZE",
                                "route_config": {
                                    "name": "browser",
                                    "virtual_hosts": [
                                        {
                                            "name": "browser",
                                            "domains": [origin.netloc],
                                            "routes": [
                                                {
                                                    "match": {"prefix": "/"},
                                                    "route": {
                                                        "cluster": "application",
                                                        "timeout": "45s",
                                                    },
                                                    "request_headers_to_remove": PROTECTED_HEADERS,
                                                }
                                            ],
                                        }
                                    ],
                                },
                                "http_filters": [ROUTER],
                                "request_headers_timeout": "2s",
                                "request_timeout": "45s",
                                "max_request_headers_kb": 32,
                            },
                        }
                    ],
                }
            ],
        }
    )
    return result


@dataclass(frozen=True)
class OutboundListener:
    local_spiffe_id: str
    destination_spiffe_id: str
    address: str
    port: int
    socket_path: str
    routes: frozenset[tuple[str, str]]


def add_outbound(config: dict[str, object], inputs: OutboundListener) -> dict[str, object]:
    if (
        IDENTITY.fullmatch(inputs.local_spiffe_id) is None
        or IDENTITY.fullmatch(inputs.destination_spiffe_id) is None
        or not re.fullmatch(r"[a-z0-9.-]+", inputs.address)
        or not 1024 <= inputs.port <= 65535
        or not inputs.routes
        or not PurePosixPath(inputs.socket_path).is_absolute()
        or ".." in PurePosixPath(inputs.socket_path).parts
        or any(
            method not in {"GET", "POST"}
            or not canonical_route(path)
            or (path in TASK_ROUTES and method != "POST")
            for method, path in inputs.routes
        )
    ):
        raise ValueError("explicit fixed mesh destination/routes and egress socket required")
    result = deepcopy(config)
    resources = _resources(result)
    resources["clusters"].append(
        {
            "name": "identity_mesh",
            "type": "STRICT_DNS",
            "connect_timeout": "1s",
            "load_assignment": {
                "cluster_name": "identity_mesh",
                "endpoints": [
                    {
                        "lb_endpoints": [
                            {
                                "endpoint": {
                                    "address": {
                                        "socket_address": {
                                            "address": inputs.address,
                                            "port_value": inputs.port,
                                        }
                                    }
                                }
                            }
                        ]
                    }
                ],
            },
            "transport_socket": {
                "name": "envoy.transport_sockets.tls",
                "typed_config": {
                    "@type": (
                        "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3."
                        "UpstreamTlsContext"
                    ),
                    "common_tls_context": {
                        "tls_params": {
                            "tls_minimum_protocol_version": "TLSv1_3",
                            "tls_maximum_protocol_version": "TLSv1_3",
                        },
                        "tls_certificate_sds_secret_configs": [
                            {"name": inputs.local_spiffe_id, "sds_config": _sds()}
                        ],
                        "combined_validation_context": {
                            "default_validation_context": {
                                "match_typed_subject_alt_names": [
                                    {
                                        "san_type": "URI",
                                        "matcher": {"exact": inputs.destination_spiffe_id},
                                    }
                                ]
                            },
                            "validation_context_sds_secret_config": {
                                "name": "spiffe://care-link.demo",
                                "sds_config": _sds(),
                            },
                        },
                    },
                },
            },
        }
    )
    resources["listeners"].append(
        {
            "name": "protected_egress",
            "address": {"pipe": {"path": inputs.socket_path, "mode": 0o660}},
            "filter_chains": [
                {
                    "filters": [
                        {
                            "name": "envoy.filters.network.http_connection_manager",
                            "typed_config": {
                                "@type": HCM,
                                "stat_prefix": "protected_egress",
                                "request_timeout": "45s",
                                "normalize_path": True,
                                "path_with_escaped_slashes_action": "REJECT_REQUEST",
                                "route_config": {
                                    "name": "pinned_egress",
                                    "virtual_hosts": [
                                        {
                                            "name": "identity",
                                            "domains": ["*"],
                                            "routes": [
                                                {
                                                    "match": {
                                                        **envoy_path_match(path),
                                                        "headers": [
                                                            {
                                                                "name": ":method",
                                                                "string_match": {"exact": method},
                                                            }
                                                        ],
                                                    },
                                                    "route": {
                                                        "cluster": "identity_mesh",
                                                        "timeout": route_timeout(path),
                                                    },
                                                    "request_headers_to_remove": PROTECTED_HEADERS,
                                                }
                                                for method, path in sorted(inputs.routes)
                                            ],
                                        }
                                    ],
                                },
                                "http_filters": [ROUTER],
                            },
                        }
                    ]
                }
            ],
        }
    )
    return result
