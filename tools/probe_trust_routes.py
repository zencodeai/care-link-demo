"""Read-only TCP route qualification from two existing, explicitly selected lab pods.

A blocked-route result requires a successful same-target control from the allowed pod.
This does not prove mTLS identity, host firewall, credential rotation or business policy.
No resources, listeners, credentials or configuration are created or changed.
"""

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Literal

PROBE = """import json,socket,sys
try:
 c=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=2)
 c.close()
 print(json.dumps({'result':'connected'}))
except TimeoutError:
 print(json.dumps({'result':'timeout'}))
except OSError:
 print(json.dumps({'result':'other_failure'}))
"""


@dataclass(frozen=True)
class ProbeResult:
    status: Literal["passed", "failed", "not_run"]
    actual: str
    allowed: str
    forbidden: str


def classify(allowed: str, forbidden: str) -> ProbeResult:
    if allowed != "connected":
        return ProbeResult(
            "not_run", "Target not proven active through allowed caller", allowed, forbidden
        )
    if forbidden == "connected":
        return ProbeResult(
            "failed", "Forbidden caller reached the active target", allowed, forbidden
        )
    if forbidden == "timeout":
        return ProbeResult(
            "passed", "TCP dropped for this observed source/target only", allowed, forbidden
        )
    return ProbeResult(
        "not_run", "Refusal/error is not credited as route enforcement", allowed, forbidden
    )


def observe(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)  # noqa: S603
        if result.returncode:
            return "probe_unavailable"
        value: object = json.loads(result.stdout)
        if isinstance(value, dict):
            observed = value.get("result")
            if observed in {"connected", "timeout", "other_failure"}:
                return str(observed)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return "probe_unavailable"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", default="care-link-imp-02", choices=["care-link-imp-02"])
    parser.add_argument("--allowed-pod", required=True)
    parser.add_argument("--forbidden-pod", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    for value in (args.context, args.allowed_pod, args.forbidden_pod, args.target):
        if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,253}", value) is None or value.startswith("-"):
            parser.error("Invalid explicit resource name")
    if args.allowed_pod == args.forbidden_pod or not 1 <= args.port <= 65535:
        parser.error("Distinct caller pods and valid port required")
    kubectl = shutil.which("kubectl")
    if not kubectl:
        parser.error("Existing kubectl is required; no tool is installed automatically")

    def probe(pod: str) -> str:
        return observe(
            [
                kubectl,
                "--context",
                args.context,
                "--namespace",
                args.namespace,
                "exec",
                pod,
                "--",
                "python",
                "-c",
                PROBE,
                args.target,
                str(args.port),
            ]
        )

    allowed = probe(args.allowed_pod)
    forbidden = probe(args.forbidden_pod) if allowed == "connected" else "not_attempted"
    result = classify(allowed, forbidden)
    print(
        json.dumps(
            {
                "format_version": "route-observation-1",
                "context": args.context,
                "namespace": args.namespace,
                "allowed_pod": args.allowed_pod,
                "forbidden_pod": args.forbidden_pod,
                "target": args.target,
                "port": args.port,
                **asdict(result),
                "limits": "TCP observation only; verify workload identities and target "
                "lineage separately. No mTLS/CNI/host admission implied.",
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result.status == "passed" else 1)


if __name__ == "__main__":
    main()
