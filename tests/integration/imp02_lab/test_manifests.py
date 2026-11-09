"""Source guard tests; these do not count as deployed policy/attestation evidence."""

from pathlib import Path

import pytest

from tools.imp02_lab import applications, dependencies, host_support, proxy_config, spire
from tools.imp02_lab.model import LabInputs


def inputs(tmp_path: Path) -> LabInputs:
    image = "docker.io/library/synthetic-fixture@sha256:" + "a" * 64
    return LabInputs(
        {
            name: image
            for name in (
                "application",
                "envoy",
                "spire_agent",
                "python",
                "postgres",
                "keycloak_runtime",
            )
        },
        tmp_path / "kind",
        tmp_path / "calico",
        tmp_path / "state",
        "a" * 64,
        "b" * 64,
    )


def test_node_credentials_outlive_bounded_workload_expiry_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.imp02_lab import spire_bootstrap

    server = spire.configurations()["server.conf"]
    assert 'agent_ttl = "1h"' in server
    assert 'default_x509_svid_ttl = "300s"' in server
    calls = []

    def server_command(_inputs: LabInputs, *args: str) -> str:
        calls.append(args)
        return "not-executed source fixture"

    monkeypatch.setattr(spire_bootstrap, "server_command", server_command)
    spire_bootstrap.register_proxy(inputs(tmp_path), "main", inputs(tmp_path).image("application"))
    spire_bootstrap.register_proxy(
        inputs(tmp_path), "identity", inputs(tmp_path).image("application")
    )
    spire_bootstrap.register_host_proxy(inputs(tmp_path), "help")
    spire_bootstrap.register_host_proxy(inputs(tmp_path), "identity_provider")
    assert len(calls) == 4
    for args in calls:
        assert args[args.index("-x509SVIDTTL") + 1] == "300"


def test_application_sockets_and_secrets_have_distinct_custody(tmp_path: Path) -> None:
    manifests = applications.manifests(inputs(tmp_path))
    deployments = [item for item in manifests if item["kind"] == "Deployment"]
    seen_uids = {}
    for item in deployments:
        spec = item["spec"]["template"]["spec"]
        assert spec["automountServiceAccountToken"] is False
        assert not spec.get("hostNetwork") and not spec.get("hostPID")
        assert all("hostPath" not in volume for volume in spec["volumes"])
        for container in spec["containers"]:
            assert container["securityContext"]["runAsNonRoot"] is True
            assert container["securityContext"]["readOnlyRootFilesystem"] is True
            if container["name"] == "application":
                seen_uids[item["metadata"]["name"]] = container["securityContext"]["runAsUser"]
                assert all(
                    mount["name"] not in {"spire", item["metadata"]["name"] + "-admin"}
                    for mount in container["volumeMounts"]
                )
            if container["name"] == "proxy":
                assert all(mount["name"] != "fence-ledger" for mount in container["volumeMounts"])
    assert seen_uids == {"identity": 21011, "main": 21012}
    seed = applications.seed(inputs(tmp_path))
    compile(seed["spec"]["template"]["spec"]["containers"][0]["command"][2], "seed", "exec")


def test_help_has_no_network_or_svid_mount_and_native_pid_attestation(tmp_path: Path) -> None:
    result = host_support.composition(inputs(tmp_path))
    help_service = result["services"]["help"]
    assert help_service["network_mode"] == "none"
    assert help_service["pid"] == "service:agent"
    assert help_service["entrypoint"] == []
    assert all(volume["type"] == "volume" for volume in help_service["volumes"])
    assert not any(
        volume["source"] in {"agent-config", "workload-api"} for volume in help_service["volumes"]
    )
    assert result["services"]["proxy"]["ports"] == ["127.0.0.1:19443:8444"]
    compile(host_support.seed_script(), "host-seed", "exec")


def test_persistence_and_exact_proxy_routes(tmp_path: Path) -> None:
    data = dependencies.manifests(inputs(tmp_path))
    pg = next(
        item
        for item in data
        if item["kind"] == "Deployment" and item["metadata"]["name"] == "postgres"
    )
    volumes = pg["spec"]["template"]["spec"]["volumes"]
    assert next(volume for volume in volumes if volume["name"] == "data")[
        "persistentVolumeClaim"
    ] == {"claimName": "postgres-data"}
    config = proxy_config.browser(
        inputs(tmp_path), "help", upstream="kind-node", upstream_port=30444
    )
    serialized = str(config)
    assert "/bff/help/v1/auth/callback" in serialized
    assert "/bff/main/v1/auth/callback" not in serialized
    assert "spiffe://care-link.demo/lab/identity" in serialized


def test_live_tls_range_and_destination_fence_configuration(tmp_path: Path) -> None:
    tls_parameters: list[dict[str, object]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                if name == "tls_params":
                    tls_parameters.append(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(proxy_config.identity(inputs(tmp_path), "192.168.0.10"))
    visit(proxy_config.browser(inputs(tmp_path), "main"))
    assert len(tls_parameters) == 3
    for parameters in tls_parameters:
        assert parameters["tls_minimum_protocol_version"] == "TLSv1_3"
        assert parameters["tls_maximum_protocol_version"] == "TLSv1_3"
    assert proxy_config.authorization_config()["local_spiffe_id"] == (
        "spiffe://care-link.demo/lab/identity"
    )


@pytest.mark.parametrize("role", ["main", "help"])
def test_ipv4_lab_does_not_select_unqualified_docker_aaaa(tmp_path: Path, role: str) -> None:
    config = proxy_config.browser(
        inputs(tmp_path), role, upstream="care-link-imp02-002-control-plane", upstream_port=30444
    )
    cluster = next(
        item for item in config["static_resources"]["clusters"] if item["name"] == "identity_mesh"
    )
    assert cluster["dns_lookup_family"] == "V4_ONLY"
    endpoint = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]
    assert endpoint["address"]["socket_address"] == {
        "address": "care-link-imp02-002-control-plane",
        "port_value": 30444,
    }
