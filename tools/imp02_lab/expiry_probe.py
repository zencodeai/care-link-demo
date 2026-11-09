"""Observe expiry denial on an existing actual mesh connection, without SVID keys.

The operator first stops only the leased SPIRE issuer deployment. This observer
performs no stop/restore action. It keeps the existing help→identity connection
active using anonymous BFF bootstrap requests and retains only statuses plus
public certificate/connection metadata. A reconnect cannot pass this test.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx

from tools.imp02_application.tls import PinnedAddressTransport

from .certificates import sample
from .commands import kubectl, private_json, verify_session
from .model import LabInputs, load_inputs
from .spire import TRUST_NAMESPACE


def issuer_stopped(inputs: LabInputs) -> dict[str, object]:
    verify_session(inputs)
    deployment = json.loads(
        kubectl(inputs, "-n", TRUST_NAMESPACE, "get", "deployment", "spire-server", "-o", "json")
    )
    pods = json.loads(
        kubectl(
            inputs, "-n", TRUST_NAMESPACE, "get", "pods", "-l", "app=spire-server", "-o", "json"
        )
    )
    if deployment["spec"].get("replicas") != 0 or pods["items"]:
        raise ValueError("operator-stopped SPIRE issuer with no remaining pods required")
    return {
        "deployment": "spire-server",
        "namespace": TRUST_NAMESPACE,
        "desired_replicas": 0,
        "remaining_pods": 0,
        "mock_used": False,
    }


def observe(
    inputs: LabInputs, ca_file: Path, *, timeout: int = 420, interval: int = 10
) -> dict[str, object]:
    if not 30 <= timeout <= 900 or not 1 <= interval <= 20:
        raise ValueError("bounded expiry observation required")
    precondition = issuer_stopped(inputs)
    origin = "https://help.localhost:19443"
    attempts: list[dict[str, object]] = []
    with httpx.Client(
        transport=PinnedAddressTransport(origin, "127.0.0.1", str(ca_file)),
        trust_env=False,
        timeout=30,
    ) as client:
        response = client.get(origin + "/v1/auth/csrf")
        attempts.append({"at": datetime.now(UTC).isoformat(), "status": response.status_code})
        if response.status_code != 200:
            return {
                "status": "failed",
                "reason": "initial live mesh control did not succeed",
                "attempts": attempts,
                "issuer": precondition,
                "mock_used": False,
            }
        before = sample(inputs, "help")
        leaf = cast(dict[str, object], before["certificate"])
        expires = datetime.fromisoformat(cast(str, leaf["expiration_time"]))
        baseline = cast(dict[str, int], before["upstream_connections"])
        total_key = "cluster.identity_mesh.upstream_cx_total"
        active_key = "cluster.identity_mesh.upstream_cx_active"
        requests_key = "cluster.identity_mesh.upstream_rq_total"
        if (
            baseline.get(active_key) != 1
            or baseline.get(total_key, 0) < 1
            or not datetime.now(UTC) < expires
        ):
            return {
                "status": "failed",
                "reason": "single current upstream connection not established",
                "before": before,
                "issuer": precondition,
                "mock_used": False,
            }
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
            try:
                response = client.get(origin + "/v1/auth/csrf")
                status: int | str = response.status_code
            except httpx.HTTPError:
                status = "transport_failure"
            at = datetime.now(UTC)
            attempts.append({"at": at.isoformat(), "status": status})
            if status == 200 and at < expires:
                continue
            after = sample(inputs, "help")
            current_leaf = cast(dict[str, object], after["certificate"])
            stats = cast(dict[str, int], after["upstream_connections"])
            unchanged = (
                stats.get(total_key) == baseline[total_key]
                and stats.get(active_key) == 1
                and stats.get(requests_key, 0) > baseline.get(requests_key, 0)
            )
            passed = (
                status == 403
                and at >= expires
                and unchanged
                and current_leaf["serial_number"] == leaf["serial_number"]
            )
            return {
                "status": "passed" if passed else "failed",
                "issuer": precondition,
                "scope": (
                    "expired peer cannot retain admission on observed existing mesh connection"
                ),
                "before": before,
                "after": after,
                "attempts": attempts,
                "connection_reused": unchanged,
                "mock_used": False,
                "limits": (
                    "HTTP1 upstream pool observation; does not establish "
                    "HTTP2 or instantaneous upstream revocation."
                ),
            }
        return {
            "status": "failed",
            "reason": "expiry denial not observed within declared bound",
            "before": before,
            "attempts": attempts,
            "issuer": precondition,
            "mock_used": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    result = observe(load_inputs(args.inputs), args.ca, timeout=args.timeout)
    private_json(args.output, result)
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
