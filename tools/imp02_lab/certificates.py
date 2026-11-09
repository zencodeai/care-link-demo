"""Public-only Envoy SDS certificate observations; never fetch/export SVID keys."""

import argparse
import ipaddress
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .commands import kubectl, private_json, run, verify_session
from .host_support import PROJECT
from .model import (
    LABELS,
    NAMESPACE,
    LabInputs,
    container_security,
    document,
    load_inputs,
    pod_security,
)

READ_CERTIFICATES = """import http.client,json,socket,struct
class U(http.client.HTTPConnection):
 def connect(self):
  s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(2)
  s.connect('/admin/admin.sock')
  _,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
  if uid!=21002:raise PermissionError('unexpected admin owner')
  self.sock=s
c=U('localhost',timeout=2);c.request('GET','/certs');r=c.getresponse()
if r.status!=200:raise RuntimeError('certificate metadata unavailable')
b=r.read(262145)
if len(b)>262144:raise RuntimeError('certificate metadata too large')
data=json.loads(b);result=[]
for context in data.get('certificates',[]):
 for cert in context.get('cert_chain',[]):
  fields=['serial_number','subject_alt_names','valid_from','expiration_time']
  result.append({k:cert[k] for k in fields if k in cert})
c.request('GET','/stats?format=json&filter=cluster.identity_mesh.upstream_');r=c.getresponse()
if r.status!=200:raise RuntimeError('connection metadata unavailable')
b=r.read(262145)
if len(b)>262144:raise RuntimeError('connection metadata too large')
allowed={'cluster.identity_mesh.'+name for name in
 ['upstream_cx_total','upstream_cx_active','upstream_rq_total']}
stats={v['name']:v['value'] for v in json.loads(b).get('stats',[]) if v.get('name') in allowed}
print(json.dumps({'loaded_certificates':result,'upstream_connections':stats}));c.close()
"""

READ_IPV6 = """import json,pathlib,socket
base=pathlib.Path('/proc/sys/net/ipv6/conf');interfaces=[]
for p in sorted(base.iterdir()) if base.exists() else []:
 if p.name in ['all','default','lo']:continue
 interfaces.append({'interface':p.name,'disable_ipv6':(p/'disable_ipv6').read_text().strip()})
addresses=[]
p=pathlib.Path('/proc/net/if_inet6')
for line in p.read_text().splitlines() if p.exists() else []:
 fields=line.split()
 if len(fields)==6:
  addresses.append({'address_hex':fields[0],'interface':fields[5],'scope_hex':fields[3]})
print(json.dumps({'kernel_ipv6_socket_support':socket.has_ipv6,'interfaces':interfaces,'addresses':addresses,
 'all_nonloopback_interfaces_disabled':bool(interfaces) and
  all(i['disable_ipv6']=='1' for i in interfaces)}))
"""


def diagnostic_pod(inputs: LabInputs, role: str) -> dict[str, object]:
    if role not in {"identity", "main"}:
        raise ValueError("exact Kubernetes proxy diagnostic role required")
    return document(
        "Pod",
        role + "-cert-probe",
        spec={
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "securityContext": pod_security(21002),
            "containers": [
                {
                    "name": "metadata",
                    "image": inputs.image("python"),
                    "command": ["python", "-c", "import time;time.sleep(86400)"],
                    "securityContext": container_security(),
                    "resources": {"limits": {"cpu": "100m", "memory": "32Mi"}},
                    "volumeMounts": [{"name": "admin", "mountPath": "/admin", "readOnly": True}],
                }
            ],
            "volumes": [
                {
                    "name": "admin",
                    "persistentVolumeClaim": {"claimName": role + "-admin", "readOnly": True},
                }
            ],
        },
    )


def host_diagnostic(inputs: LabInputs) -> dict[str, object]:
    return {
        "image": inputs.image("python"),
        "container_name": PROJECT + "-cert-probe",
        "user": "21002:21002",
        "network_mode": "none",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "command": ["python", "-c", "import time;time.sleep(86400)"],
        "mem_limit": "32m",
        "cpus": "0.1",
        "pids_limit": 16,
        "labels": LABELS,
        "profiles": ["qualification"],
        "volumes": [{"type": "volume", "source": "admin", "target": "/admin", "read_only": True}],
    }


def sample(inputs: LabInputs, role: str) -> dict[str, object]:
    verify_session(inputs)
    if role == "help":
        raw = run(
            [
                "docker",
                "exec",
                "--user",
                "21002:21002",
                PROJECT + "-cert-probe",
                "python",
                "-c",
                READ_CERTIFICATES,
            ],
            timeout=10,
        )
    elif role in {"identity", "main"}:
        raw = kubectl(
            inputs,
            "-n",
            NAMESPACE,
            "exec",
            role + "-cert-probe",
            "--",
            "python",
            "-c",
            READ_CERTIFICATES,
        )
    else:
        raise ValueError("exact proxy role required")
    value = cast(dict[str, object], json.loads(raw))
    expected = "spiffe://care-link.demo/lab/" + role
    matches: list[dict[str, object]] = []
    for certificate in cast(list[dict[str, object]], value["loaded_certificates"]):
        names = cast(list[dict[str, str]], certificate.get("subject_alt_names", []))
        if any(name.get("uri") == expected for name in names):
            if not all(
                isinstance(certificate.get(key), str) and certificate[key]
                for key in ("serial_number", "valid_from", "expiration_time")
            ):
                raise ValueError("loaded SVID public metadata incomplete")
            matches.append(certificate)
    if len(matches) != 1:
        raise ValueError("exact single loaded proxy SVID not observed")
    return {
        "role": role,
        "observed_at": datetime.now(UTC).isoformat(),
        "spiffe_id": expected,
        "certificate": matches[0],
        "upstream_connections": value.get("upstream_connections", {}),
        "mock_used": False,
        "source": "Envoy admin UDS /certs, kernel owner UID21002; public fields only",
    }


def renewal(
    inputs: LabInputs, role: str, *, timeout: int = 420, interval: int = 20
) -> dict[str, object]:
    if not 30 <= timeout <= 900 or not 1 <= interval <= 30:
        raise ValueError("bounded lifecycle observation required")
    first = sample(inputs, role)
    baseline = cast(dict[str, object], first["certificate"])
    previous_expiry = datetime.fromisoformat(cast(str, baseline["expiration_time"]))
    deadline = time.monotonic() + timeout
    observations = [first]
    while time.monotonic() < deadline:
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
        current = sample(inputs, role)
        observations.append(current)
        certificate = cast(dict[str, object], current["certificate"])
        expires = datetime.fromisoformat(cast(str, certificate["expiration_time"]))
        if (
            certificate["serial_number"] != baseline["serial_number"]
            and expires > previous_expiry
            and datetime.now(UTC) < expires
        ):
            return {
                "status": "passed",
                "scope": "actual proxy SDS-loaded X.509 SVID renewal",
                "before": first,
                "after": current,
                "sample_count": len(observations),
                "mock_used": False,
                "limits": "Does not alone prove old-peer expiry or open-connection fencing.",
            }
    return {
        "status": "failed",
        "reason": "renewal not observed within declared bound",
        "before": first,
        "last": observations[-1],
        "mock_used": False,
    }


def ipv6(inputs: LabInputs) -> dict[str, object]:
    verify_session(inputs)
    raw = kubectl(inputs, "-n", NAMESPACE, "exec", "runtime-probe", "--", "python", "-c", READ_IPV6)
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "runtime": json.loads(raw),
        "mock_used": False,
        "limits": "Kernel/interface observation only; no absent-listener denial claim.",
    }


def host_ipv6() -> dict[str, object]:
    """Observe native interfaces without printing addresses or changing settings."""
    if sys.platform != "darwin":
        return {
            "status": "not_run",
            "reason": "native host observer is scoped to this Mac workstation",
        }
    observed = subprocess.run(
        ["/sbin/ifconfig", "-a"], capture_output=True, text=True, check=False, timeout=3
    )
    if observed.returncode:
        raise RuntimeError("native interface observation unavailable")
    interface = ""
    addresses: list[dict[str, object]] = []
    for line in observed.stdout.splitlines():
        if line and not line[0].isspace():
            interface = line.split(":", 1)[0]
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "inet6":
            value = ipaddress.IPv6Address(fields[1].split("%", 1)[0])
            addresses.append(
                {
                    "interface": interface,
                    "scope": "loopback"
                    if value.is_loopback
                    else "link_local"
                    if value.is_link_local
                    else "other",
                }
            )
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "mock_used": False,
        "interfaces_with_ipv6": addresses,
        "native_ipv6_configured": bool(addresses),
        "limits": "Observation only; does not assert host firewall denial or disable IPv6.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sample", "renewal", "ipv6", "host-ipv6"))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--role", choices=("identity", "main", "help"), default="identity")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    inputs = load_inputs(args.inputs)
    result = (
        host_ipv6()
        if args.command == "host-ipv6"
        else (
            ipv6(inputs)
            if args.command == "ipv6"
            else sample(inputs, args.role)
            if args.command == "sample"
            else renewal(inputs, args.role, timeout=args.timeout)
        )
    )
    private_json(args.output, result)
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
