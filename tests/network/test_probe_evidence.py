"""Route verifier rejects missing-server evidence and detects reachable bypass."""

import pytest

from tools.probe_trust_routes import classify


@pytest.mark.unit
@pytest.mark.parametrize(
    "allowed,forbidden,status",
    [
        ("other_failure", "timeout", "not_run"),
        ("connected", "connected", "failed"),
        ("connected", "other_failure", "not_run"),
        ("connected", "timeout", "passed"),
        ("probe_unavailable", "probe_unavailable", "not_run"),
    ],
)
def test_route_evidence_requires_same_target_control(allowed: str, forbidden: str, status: str):
    assert classify(allowed, forbidden).status == status


@pytest.mark.unit
def test_mesh_cleans_up_an_owned_container_that_appears_after_startup_timeout(monkeypatch):
    from subprocess import TimeoutExpired
    from unittest.mock import Mock

    from tools.imp06_verification import role_topology as mesh

    docker = Mock(side_effect=["sha256:" + "a" * 64, TimeoutExpired("docker", 30)])
    monkeypatch.setattr(mesh, "docker", docker)
    lab = mesh.Lab("fixture-image")

    with pytest.raises(TimeoutExpired):
        lab.run("late-proxy", [], [], image="fixture-image")

    expected = mesh.resource("late-proxy")
    docker.reset_mock()
    docker.side_effect = [expected, "", "", ""]
    assert lab.cleanup() == {"containers": 1, "volumes": 0, "networks": 0}
    assert docker.call_args_list[1].args == ("rm", "-f", expected)

    docker.reset_mock()
    docker.side_effect = [mesh.resource("unleased-proxy")]
    with pytest.raises(RuntimeError, match="cleanup ownership mismatch"):
        lab.cleanup()
    assert docker.call_count == 1
