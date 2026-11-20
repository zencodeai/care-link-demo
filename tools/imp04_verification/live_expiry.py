"""Actual isolated issuer outage through SVID expiry, with unconditional recovery."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx

from tools.imp02_application.tls import PinnedAddressTransport
from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PREFIX, PRIVATE, record


def recovery_seconds(value: str) -> int:
    """Observation window only; it never changes application/request authority."""
    try:
        seconds = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Recovery seconds must be an integer") from error
    if not 75 <= seconds <= 300:
        raise argparse.ArgumentTypeError("Recovery seconds must be between75 and300")
    return seconds


def public_status(path: str) -> int:
    origin = "https://plans.localhost:30443"
    try:
        with httpx.Client(
            transport=PinnedAddressTransport(origin, "127.0.0.1", str(PRIVATE / "tls/ca.crt")),
            trust_env=False,
        ) as client:
            return client.get(origin + path, timeout=3).status_code
    except httpx.HTTPError:
        return 0


def leaves() -> list[dict[str, str]]:
    script = r"""
import json,sys,socket,ssl,datetime
ctx=ssl.create_default_context(cadata=sys.argv[1]);ctx.check_hostname=False
results=[]
for i,role in enumerate(('identity','core','data','pdp','journal')):
 with socket.create_connection(('172.29.44.'+str(11+i),8443),timeout=2) as raw:
  with ctx.wrap_socket(raw,server_hostname=role+'.imp04.mesh') as tls:
   cert=tls.getpeercert();uris=[v for k,v in cert.get('subjectAltName',[]) if k=='URI']
   if uris!=['spiffe://care-link.demo/demo/'+role]:raise ValueError('Unexpected peer identity')
   expiry=datetime.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert['notAfter']),datetime.timezone.utc)
   results.append({'role':role,'spiffe_id':uris[0],'not_after':expiry.isoformat()})
print(json.dumps(results))
"""
    return cast(
        list[dict[str, str]],
        json.loads(
            docker.exec(
                PREFIX + "-ingress",
                ["python", "-c", script, (PRIVATE / "spire-bundle.pem").read_text()],
            )
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument(
        "--recovery-seconds",
        type=recovery_seconds,
        default=300,
        help="Recovery observation window75..300s (default300; user-agreed recovery bound)",
    )
    args = parser.parse_args()
    if public_status("/v1/auth/csrf") != 200:
        raise ValueError("Current protected success required before issuer outage")
    value: dict[str, object] = {
        "target": PREFIX,
        "scope": "Own issuer only; no agents/fences/accepted resources changed",
        "before": leaves(),
        "status": "in_progress",
        "runtime_svid_ttl_seconds": 300,
        "issuer_outage_minimum_seconds": 302,
        "recovery_observation_seconds": args.recovery_seconds,
        "recovery_bound_scope": (
            "User-agreed300s recovery from issuer restart; application deadlines unchanged"
            if args.recovery_seconds == 300
            else "Explicit harness observation window; separate acceptance reference required"
        ),
        "recovery_window_user_agreed": args.recovery_seconds == 300,
        "application_deadlines_changed": False,
    }
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    server, restore = PREFIX + "-spire-server", False
    try:
        docker.inspect_container(server)
        restore = True
        docker.stop(server)
        stopped_at = datetime.now(UTC)
        value["issuer_stopped_at"] = stopped_at.isoformat()
        value["after_issuer_stop"] = leaves()
        # The configured runtime SVID TTL is300s. Waiting beyond stop+TTL also
        # covers a credential issued just before shutdown but delivered later.
        deadline = stopped_at + timedelta(seconds=302)
        value["wait_until"] = deadline.isoformat()
        args.output.write_text(json.dumps(value, indent=2) + "\n")
        last_notice = time.monotonic() - 30
        while datetime.now(UTC) < deadline:
            if time.monotonic() - last_notice >= 25:
                print(
                    json.dumps(
                        {
                            "phase": "real_svid_expiry_wait",
                            "seconds_remaining": round(
                                (deadline - datetime.now(UTC)).total_seconds()
                            ),
                        }
                    ),
                    flush=True,
                )
                last_notice = time.monotonic()
            time.sleep(min(5, max(0.01, (deadline - datetime.now(UTC)).total_seconds())))
        value["expired_observed_at"] = datetime.now(UTC).isoformat()
        value["expired_protected_bootstrap_status"] = public_status("/v1/auth/csrf")
        value["expired_public_health_status"] = public_status("/dev/health")
        if value["expired_protected_bootstrap_status"] == 200:
            raise ValueError("Expired workload trust improperly permitted protected traffic")
        if value["expired_public_health_status"] != 200:
            raise ValueError("Public health unavailable; expiry denial attribution is incomplete")
        value["expired_trust_denied"] = True
    finally:
        if restore:
            docker.start(server)
            value["issuer_restarted_at"] = datetime.now(UTC).isoformat()
            recovery_started = time.monotonic()
            ready_at = recovery_started + args.recovery_seconds
            value["recovery_observation_deadline_at"] = (
                datetime.now(UTC) + timedelta(seconds=args.recovery_seconds)
            ).isoformat()
            recovered: list[dict[str, str]] | None = None
            recovery_attempts = 0
            last_notice = recovery_started - 30
            while time.monotonic() < ready_at:
                recovery_attempts += 1
                if time.monotonic() - last_notice >= 25:
                    print(
                        json.dumps(
                            {
                                "phase": "real_svid_recovery_wait",
                                "seconds_remaining": max(0, round(ready_at - time.monotonic())),
                            }
                        ),
                        flush=True,
                    )
                    last_notice = time.monotonic()
                try:
                    observed = leaves()
                    if public_status("/v1/auth/csrf") == 200:
                        if time.monotonic() <= ready_at:
                            recovered = observed
                            value["recovered_observed_at"] = datetime.now(UTC).isoformat()
                        else:
                            value["late_recovery_observed_at"] = datetime.now(UTC).isoformat()
                            value["late_recovery_valid_leaves"] = observed
                        break
                except (RuntimeError, ValueError):
                    pass
                time.sleep(1)
            value["recovery_attempts"] = recovery_attempts
            value["recovery_observation_finished_at"] = datetime.now(UTC).isoformat()
            value["recovery_elapsed_seconds"] = round(time.monotonic() - recovery_started, 3)
            value["after_recovery"] = recovered
            value["recovered_protected_bootstrap_status"] = public_status("/v1/auth/csrf")
            value["clock_changed"] = False
            value["agent_or_fence_restart"] = False
            value["status"] = (
                "passed"
                if (
                    value.get("expired_trust_denied") is True
                    and recovered is not None
                    and value["recovered_protected_bootstrap_status"] == 200
                )
                else "failed"
            )
            args.output.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(record(value), indent=2))
    if value["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
