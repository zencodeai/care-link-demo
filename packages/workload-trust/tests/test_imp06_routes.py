"""Certificate/fence-backed task routes; generated configs are not deployed mesh proof."""

import json
import os
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from care_link_workload_trust import (
    SOCKET_PEER_SCOPE_KEY,
    BackendVerifier,
    OutboundListener,
    PeerRule,
    ProxyInputs,
    SocketPeer,
    TrustDenied,
    WorkloadEnforcer,
    add_outbound,
    build_envoy,
)
from care_link_workload_trust.verification import TASK_ROUTES
from test_workload_trust import fixture as _certificate_fixture

certificate_fixture = _certificate_fixture


@pytest.mark.parametrize("template", sorted(TASK_ROUTES))
def test_task_uuid_routes_enforced_by_actual_certificate_and_backend(
    certificate_fixture, monkeypatch, template
):
    prior, store, _clock, xfcc, _leaf, _root = certificate_fixture
    identity = prior.rules[0].spiffe_id
    rule = PeerRule(identity, frozenset({("POST", template)}))
    enforcer = WorkloadEnforcer(prior.proxy_uid, prior.trust_roots, (rule,), store, prior.clock)
    actual = template.replace("{task_id}", str(uuid4()))
    admission = enforcer.authorize(prior.proxy_uid, "POST", actual, xfcc)
    expires = admission.certificate_expires_at.isoformat().replace("+00:00", "Z")
    request = SimpleNamespace(
        scope={SOCKET_PEER_SCOPE_KEY: SocketPeer(prior.proxy_uid)},
        method="POST",
        url=SimpleNamespace(path=actual),
        headers={
            "x-care-link-verified-spiffe": identity,
            "x-care-link-fence-generation": str(admission.fence_generation),
            "x-care-link-certificate-expires-at": expires,
            "x-care-link-certificate-digest": admission.certificate_digest,
        },
    )
    monkeypatch.setattr(os, "geteuid", lambda: prior.proxy_uid + 1)
    backend = BackendVerifier(prior.proxy_uid, (rule,), store, backend_uid=prior.proxy_uid + 1)
    assert backend(request, identity.rsplit("/", 1)[-1])
    for target in (
        actual.upper(),
        actual + "/suffix",
        actual + "?bypass=1",
        actual.replace("-", ""),
        template,
        actual.replace("/internal/", "/internal//"),
        actual.replace("/internal/", "/internal/%2e%2e/"),
    ):
        request.url.path = target
        assert not backend(request, identity.rsplit("/", 1)[-1])
        with pytest.raises(TrustDenied):
            enforcer.authorize(prior.proxy_uid, "POST", target, xfcc)
    request.url.path = actual
    request.scope["query_string"] = b"bypass=1"
    assert not backend(request, identity.rsplit("/", 1)[-1])
    request.scope["query_string"] = b""
    request.method = "GET"
    assert not backend(request, identity.rsplit("/", 1)[-1])
    request.method = "POST"
    request.scope.clear()
    assert not backend(request, identity.rsplit("/", 1)[-1])
    request.scope[SOCKET_PEER_SCOPE_KEY] = SocketPeer(prior.proxy_uid)
    store.restrict(identity, "imp06-runtime-restricted", 0)
    assert not backend(request, identity.rsplit("/", 1)[-1])


@pytest.mark.parametrize(
    "target",
    [
        "/internal/v1/tasks/{anything}/lease",
        "/internal/v1/tasks/*/lease",
        "/internal/v1/tasks/{task_id}/delete",
        "/unrelated/{task_id}",
        "/internal/v1/tasks/{task_id}/lease?allow=1",
    ],
)
def test_unregistered_templates_and_wildcards_rejected(target):
    with pytest.raises(ValueError):
        PeerRule("spiffe://care-link.demo/demo/runtime", frozenset({("POST", target)}))


def test_task_templates_never_add_get_admission():
    with pytest.raises(ValueError):
        PeerRule(
            "spiffe://care-link.demo/demo/runtime",
            frozenset(
                {
                    ("GET", "/internal/v1/tasks/{task_id}/lease"),
                }
            ),
        )


def proxy(routes):
    return build_envoy(
        ProxyInputs(
            "spiffe://care-link.demo/demo/core",
            (PeerRule("spiffe://care-link.demo/demo/runtime", frozenset(routes)),),
            "127.0.0.1",
            8443,
            "/run/app.sock",
            "/run/auth.sock",
            "/run/spire.sock",
            "envoyproxy/envoy@sha256:" + "a" * 64,
            "1.2.3",
            "ghcr.io/spiffe/spire@sha256:" + "b" * 64,
            "1.2.3",
            60,
        )
    )


def hcm(config, index=0):
    return config["static_resources"]["listeners"][index]["filter_chains"][0]["filters"][0][
        "typed_config"
    ]


def test_ingress_egress_match_same_canonical_uuid_and_only_inference_timeout():
    paths = [
        *sorted(TASK_ROUTES),
        "/internal/v1/broker/inference",
        "/internal/v1/inference/jobs",
        "/internal/v1/inference/execute",
        "/internal/v1/inference/tokenize",
        "/internal/v1/broker/tools",
        "/bff/main/v1/auth/login",
    ]
    routes = frozenset(("POST", path) for path in paths)
    ingress = proxy(routes)
    outbound = add_outbound(
        ingress,
        OutboundListener(
            "spiffe://care-link.demo/demo/core",
            "spiffe://care-link.demo/demo/data",
            "data.localhost",
            8443,
            "/run/egress.sock",
            routes,
        ),
    )
    for configuration in (hcm(ingress), hcm(outbound, 1)):
        built = configuration["route_config"]["virtual_hosts"][0]["routes"]
        assert len(built) == len(paths)
        for path, route in zip(sorted(paths), built, strict=True):
            match = route["match"]
            assert match["headers"] == [{"name": ":method", "string_match": {"exact": "POST"}}]
            if path in TASK_ROUTES:
                assert "path" not in match
                expression = match["safe_regex"]["regex"]
                actual = path.replace("{task_id}", str(uuid4()))
                assert re.fullmatch(expression, actual)
                assert not re.fullmatch(expression, actual + "?bypass=1")
                assert not re.fullmatch(expression, actual.upper())
                assert not re.fullmatch(expression, path)
                assert match["safe_regex"]["google_re2"] == {}
            else:
                assert match["path"] == path
            long = path in {
                "/internal/v1/broker/inference",
                "/internal/v1/inference/jobs",
                "/internal/v1/inference/execute",
                "/bff/main/v1/auth/login",
            }
            assert route["route"]["timeout"] == ("40s" if long else "10s")
    serialized = json.dumps(ingress)
    assert '"remove": "x-care-link-certificate-digest"' in serialized
    assert '"exact": "x-care-link-certificate-digest"' in serialized
    assert (
        "x-care-link-certificate-digest"
        in hcm(outbound, 1)["route_config"]["virtual_hosts"][0]["routes"][0][
            "request_headers_to_remove"
        ]
    )
