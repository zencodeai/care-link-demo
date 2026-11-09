"""Observe actual allowed controls before assigning any negative-route evidence."""

import json
from datetime import UTC, datetime
from typing import cast

from .commands import kubectl, verify_session
from .model import NAMESPACE, LabInputs

PROBE = """import errno,json,socket,sys,time
started=time.monotonic();s=socket.socket();s.settimeout(2)
try:
 s.connect((sys.argv[1],int(sys.argv[2])))
 print(json.dumps({'result':'connected','seconds':time.monotonic()-started}))
except TimeoutError:
 print(json.dumps({'result':'timeout','seconds':time.monotonic()-started}))
except OSError as e:
 print(json.dumps({'result':'refused' if e.errno==errno.ECONNREFUSED else 'error',
                   'errno':e.errno,'seconds':time.monotonic()-started}))
finally:s.close()
"""


def pod_ip(inputs: LabInputs, name: str) -> str:
    value = cast(
        dict[str, object],
        json.loads(kubectl(inputs, "-n", NAMESPACE, "get", "pod", name, "-o", "json")),
    )
    status = cast(dict[str, object], value["status"])
    address = status.get("podIP")
    if not isinstance(address, str):
        raise RuntimeError("active control pod has no observed IP")
    return address


def probe(inputs: LabInputs, caller: str, address: str, port: int) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(
            kubectl(
                inputs,
                "-n",
                NAMESPACE,
                "exec",
                caller,
                "--",
                "python",
                "-c",
                PROBE,
                address,
                str(port),
            )
        ),
    )


def observe(inputs: LabInputs, host_probe_ip: str) -> dict[str, object]:
    verify_session(inputs)
    target, broker = pod_ip(inputs, "denied-fixture"), pod_ip(inputs, "broker-fixture")
    allowed_broker = probe(inputs, "runtime-probe", broker, 8443)
    results: list[dict[str, object]] = []
    cases = [
        ("database", target, 5432),
        ("direct_backend", target, 8011),
        ("direct_model", target, 1234),
        ("isolated_external_control", target, 8443),
        ("alternate_pod_port", target, 18443),
        ("isolated_node_network_control", host_probe_ip, 18443),
    ]
    for family, address, port in cases:
        control = probe(inputs, "allowed-probe", address, port)
        forbidden = (
            probe(inputs, "runtime-probe", address, port)
            if control["result"] == "connected"
            else {"result": "not_attempted"}
        )
        # Refusal is deliberately not denial evidence, even after another caller
        # connected: only an observed drop is credited for this policy harness.
        passed = control["result"] == "connected" and forbidden["result"] == "timeout"
        results.append(
            {
                "family": family,
                "address": address,
                "port": port,
                "control": control,
                "forbidden": forbidden,
                "status": "passed" if passed else "failed",
                "mock_used": False,
            }
        )
    passed = allowed_broker["result"] == "connected" and all(
        item["status"] == "passed" for item in results
    )
    return {
        "session": "imp02-002",
        "observed_at": datetime.now(UTC).isoformat(),
        "allowed_runtime_broker": allowed_broker,
        "routes": results,
        "status": "passed" if passed else "failed",
        "mock_used": False,
        "limitations": [
            "Isolated active test listeners; actual model admission remains IMP-06.",
            "These observations do not alone prove workload certificate or browser isolation.",
            "IPv6 and actual Mac-host interface restrictions require their own observation.",
        ],
    }
