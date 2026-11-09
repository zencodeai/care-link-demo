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
