"""Offline tests for exact IMP-10 proxy roles and route containment."""

import json

import pytest
from care_link_domain import INFERENCE_ACTOR_PATH

from tools.imp06_runtime.routes import LEDGER_ROUTES, RUNTIME_ROUTES, inbound
from tools.imp10_runtime.mesh import configurations, render
from tools.imp10_runtime.routes import (
    EVALUATION_ROUTES,
    HELP_AUTH_ROUTES,
    HELP_IDENTITY_ROUTES,
    TRAINING_IDENTITY_ROUTES,
    TRAINING_ROUTES,
)


def bindings(*, enabled=True):
    outbound = {
        "core": ["identity", "data", "pdp"],
        "data": ["identity", "core", "pdp", "journal"],
        "identity": [],
        "journal": [],
        "pdp": [],
    }
    if enabled:
        outbound["core"] += ["receiver", "training", "inference"]
        outbound["data"] += ["receiver"]
        outbound.update(
            runtime=["core"],
            receiver=["identity"],
            training=["identity"],
            help=["identity"],
            inference=["data", "host-inference-bridge"],
        )
        outbound["host-inference-bridge"] = []
    roles = {}
    for offset, (role, peers) in enumerate(outbound.items(), start=10):
        common = {
            "spire_socket": "/run/mesh/spire.sock",
            "outbound": {peer: f"/run/mesh/{peer}.sock" for peer in peers},
        }
        roles[role] = common
        if role != "runtime":
            common["backend_socket"] = "/run/mesh/app.sock"
        if role not in {"runtime", "help"}:
            common.update(
                address=f"10.90.0.{offset}",
                port=8443,
                authorization_socket="/run/mesh/authorize.sock",
                authorization_uid=23001,
                trust_bundle="/run/mesh/bundle.pem",
                proxy_uid=23002,
                fence_socket="/run/mesh/fence.sock",
                fence_uid=23003,
            )
        if role in {"core", "help"}:
            common["browser"] = {
                "origin": f"https://{role}.example:8444",
                "address": f"10.90.0.{offset}",
                "port": 8444,
                "certificate": "/run/mesh/browser.crt",
                "private_key": "/run/mesh/browser.key",
            }
    return {
        "session": "imp10-protected",
        "features": {name: enabled for name in ("assisted", "training", "referral", "help")},
        "pins": {
            "envoy_image": "sandbox/envoy@sha256:" + "a" * 64,
            "spire_image": "sandbox/spire@sha256:" + "8" * 64,
            "envoy_version": "1.34.0",
            "spire_version": "1.12.0",
            "svid_ttl_seconds": 90,
        },
        "roles": roles,
    }


def inbound_rules(rendered, role):
    return {
        item["spiffe_id"]: {tuple(pair) for pair in item["routes"]}
        for item in rendered[role + "-authorization.json"]["rules"]
    }


def egress_rule_set(resources, destination):
    listener = next(
        item for item in resources["listeners"] if item["name"] == "protected_egress_" + destination
    )
    manager = listener["filter_chains"][0]["filters"][0]["typed_config"]
    routes = manager["route_config"]["virtual_hosts"][0]["routes"]
    assert all(route["route"]["cluster"] == "identity_mesh_" + destination for route in routes)
    return {
        (route["match"]["headers"][0]["string_match"]["exact"], route["match"]["path"])
        for route in routes
        if "path" in route["match"]
    }


def test_training_evaluation_and_identity_share_exact_allowlists():
    rendered = configurations(bindings())
    core = rendered["core-envoy.json"]["static_resources"]
    data = rendered["data-envoy.json"]["static_resources"]
    training = rendered["training-envoy.json"]["static_resources"]
    prefix = "spiffe://care-link.demo/demo/"
    assert (
        egress_rule_set(core, "training")
        == inbound_rules(rendered, "training")[prefix + "core"]
        == TRAINING_ROUTES
    )
    assert egress_rule_set(core, "data") & EVALUATION_ROUTES == EVALUATION_ROUTES
    assert (
        egress_rule_set(training, "identity")
        == inbound_rules(rendered, "identity")[prefix + "training"]
        == TRAINING_IDENTITY_ROUTES
    )
    assert inbound_rules(rendered, "data") == {
        rule.spiffe_id: rule.routes for rule in inbound("data", training_enabled=True)
    }
    assert not egress_rule_set(data, "identity") & TRAINING_ROUTES
    assert inbound_rules(rendered, "data")[prefix + "inference"] == LEDGER_ROUTES
    for role, target in (("core", "training"), ("training", "identity")):
        cluster = next(
            item
            for item in rendered[role + "-envoy.json"]["static_resources"]["clusters"]
            if item["name"] == "identity_mesh_" + target
        )
        assert cluster["common_http_protocol_options"]["max_connection_duration"] == "30s"
        tls = cluster["transport_socket"]["typed_config"]["common_tls_context"]
        assert tls["tls_certificate_sds_secret_configs"][0]["name"] == prefix + role
        validation = tls["combined_validation_context"]["default_validation_context"]
        assert validation["match_typed_subject_alt_names"] == [
            {"san_type": "URI", "matcher": {"exact": prefix + target}}
        ]


def test_runtime_and_help_have_no_private_inbound_or_extra_egress():
    rendered = configurations(bindings())
    runtime = rendered["runtime-envoy.json"]["static_resources"]
    help_role = rendered["help-envoy.json"]["static_resources"]
    assert {item["name"] for item in runtime["listeners"]} == {"protected_egress_core"}
    assert {item["name"] for item in runtime["clusters"]} == {"spire_agent", "identity_mesh_core"}
    assert {item["name"] for item in help_role["listeners"]} == {
        "browser_tls",
        "protected_egress_identity",
    }
    assert {item["name"] for item in help_role["clusters"]} == {
        "application",
        "spire_agent",
        "identity_mesh_identity",
    }
    assert (
        "runtime-authorization.json" not in rendered and "help-authorization.json" not in rendered
    )
    assert egress_rule_set(help_role, "identity") == HELP_AUTH_ROUTES | HELP_IDENTITY_ROUTES
    assert inbound_rules(rendered, "core")["spiffe://care-link.demo/demo/runtime"] == RUNTIME_ROUTES
    browser = next(item for item in help_role["listeners"] if item["name"] == "browser_tls")
    manager = browser["filter_chains"][0]["filters"][0]["typed_config"]
    host = manager["route_config"]["virtual_hosts"][0]
    assert host["domains"] == ["help.example:8444"]
    assert host["routes"][0:2] == [
        {"match": {"path": "/internal"}, "direct_response": {"status": 403}},
        {"match": {"prefix": "/internal/"}, "direct_response": {"status": 403}},
    ]


def test_inference_actor_proofs_are_available_only_to_data_over_assisted_mesh():
    route = ("POST", INFERENCE_ACTOR_PATH)
    rendered = configurations(bindings())
    data = rendered["data-envoy.json"]["static_resources"]
    runtime = rendered["runtime-envoy.json"]["static_resources"]
    core_rules = inbound_rules(rendered, "core")
    assert route in egress_rule_set(data, "core")
    assert route not in egress_rule_set(runtime, "core")
    assert {peer for peer, routes in core_rules.items() if route in routes} == {
        "spiffe://care-link.demo/demo/data"
    }
    baseline = configurations(bindings(enabled=False))
    assert route not in egress_rule_set(baseline["data-envoy.json"]["static_resources"], "core")


def test_manual_profile_does_not_render_opted_out_paths(tmp_path):
    output = tmp_path / "private"
    render(bindings(enabled=False), output)
    assert len(list(output.iterdir())) == 10
    assert all(path.stat().st_mode & 0o077 == 0 for path in output.iterdir())
    document = json.loads((output / "data-authorization.json").read_text())
    assert set(map(tuple, document["rules"][0]["routes"])).isdisjoint(EVALUATION_ROUTES)
    assert "training" not in (output / "core-envoy.json").read_text()
    assert not (output / "runtime-envoy.json").exists()
    with pytest.raises(FileExistsError):
        render(bindings(enabled=False), output)


def test_route_and_private_listener_cannot_be_extended_by_configuration(tmp_path):
    binding = bindings()
    binding["roles"]["runtime"]["outbound"]["data"] = "/run/mesh/data.sock"
    with pytest.raises(ValueError, match="Exact protected mesh configuration fields"):
        render(binding, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()

    binding = bindings()
    binding["roles"]["help"]["port"] = 8443
    with pytest.raises(ValueError, match="Exact protected mesh configuration fields"):
        configurations(binding)

    binding = bindings()
    binding["roles"]["help"]["browser"]["origin"] = "https://Core.Example:8445"
    with pytest.raises(ValueError, match="distinct browser hostnames"):
        configurations(binding)

    with pytest.raises(ValueError, match="explicit IMP-10 protected mesh"):
        configurations({**bindings(), "session": "imp03-002"})
