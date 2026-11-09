"""Bounded local signed-signal→durable-fence qualification; no native SSF claim.

The operator starts only the named fixture services. The signing key remains
outside containers; signed machine events are supplied through stdin. The sole
supported effect fences identity_provider itself after all other demonstrations.
"""

import argparse
import base64
import hashlib
import inspect
import json
import os
import select
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
from care_link_contracts import validate_contract
from care_link_workload_trust import OutboundListener, add_outbound
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from psycopg.conninfo import conninfo_to_dict

from .certificates import READ_CERTIFICATES
from .commands import kubectl, private_json, run, verify_session
from .host_support import PROJECT
from .model import CLUSTER, LABELS, NAMESPACE, LabInputs, load_inputs
from .proxy_config import identity

PEER = "spiffe://care-link.demo/lab/identity_provider"
PATH = "/internal/v1/identity/signals"
PREFIX = PROJECT + "-signal-"


def proxy_configuration(inputs: LabInputs) -> dict[str, object]:
    value = identity(inputs, "127.0.0.1")
    value["node"]["id"] = PEER
    value["static_resources"]["listeners"] = []
    value["static_resources"]["clusters"] = [
        item for item in value["static_resources"]["clusters"] if item["name"] == "spire_agent"
    ]
    value = add_outbound(
        value,
        OutboundListener(
            PEER,
            "spiffe://care-link.demo/lab/identity",
            CLUSTER + "-control-plane",
            30444,
            "/run/care-link/signals/proxy.sock",
            frozenset({("POST", PATH)}),
        ),
    )
    for cluster in value["static_resources"]["clusters"]:
        if cluster["name"] == "identity_mesh":
            cluster["dns_lookup_family"] = "V4_ONLY"
    return value


def composition(inputs: LabInputs) -> dict[str, object]:
    common = {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "labels": LABELS,
        "mem_limit": "128m",
        "cpus": "0.5",
        "pids_limit": 32,
    }

    def mount(source: str, target: str, readonly: bool = False) -> dict[str, object]:
        return {"type": "volume", "source": source, "target": target, "read_only": readonly}

    return {
        "name": PROJECT,
        "services": {
            "signal-seed": common
            | {
                "container_name": PREFIX + "seed",
                "image": inputs.image("python"),
                "user": "0:0",
                "network_mode": "none",
                "cap_add": ["CHOWN", "FOWNER", "DAC_OVERRIDE"],
                "command": ["python", "-c", "import time;time.sleep(86400)"],
                "volumes": [
                    mount(name, "/volumes/" + name)
                    for name in ("signal-config", "signal-outbound", "signal-admin")
                ],
            },
            "signal-proxy": common
            | {
                "container_name": PREFIX + "proxy",
                "image": inputs.image("envoy"),
                "user": "21004:21004",
                "pid": "container:" + PROJECT + "-agent",
                "networks": ["kind"],
                "command": [
                    "-c",
                    "/config/envoy.json",
                    "--disable-hot-restart",
                    "--log-level",
                    "warning",
                ],
                "volumes": [
                    mount("signal-config", "/config", True),
                    mount("signal-outbound", "/run/care-link/signals"),
                    mount("signal-admin", "/run/care-link/admin"),
                    mount("workload-api", "/run/spire/sockets", True),
                ],
            },
            "signal-client": common
            | {
                "container_name": PREFIX + "client",
                "image": inputs.image("python"),
                "user": "21005:21004",
                "network_mode": "none",
                "command": ["python", "-c", "import time;time.sleep(86400)"],
                "volumes": [mount("signal-outbound", "/run/care-link/signals", True)],
            },
            "signal-cert-probe": common
            | {
                "container_name": PREFIX + "cert-probe",
                "image": inputs.image("python"),
                "user": "21004:21004",
                "network_mode": "none",
                "command": ["python", "-c", "import time;time.sleep(86400)"],
                "volumes": [mount("signal-admin", "/admin", True)],
            },
        },
        "networks": {"kind": {"external": True, "name": "kind"}},
        "volumes": {
            name: {"name": PROJECT + "-" + name, "labels": LABELS}
            for name in ("signal-config", "signal-outbound", "signal-admin")
        }
        | {"workload-api": {"external": True, "name": PROJECT + "-workload-api"}},
    }


def seed_script() -> str:
    return "\n".join(
        [
            "import json,os,pathlib,sys",
            "data=json.dumps(json.load(sys.stdin),separators=(',',':')).encode()",
            "settings=[('signal-config',0o700),('signal-outbound',0o710),('signal-admin',0o700)]",
            "for name,mode in settings:",
            " p=pathlib.Path('/volumes',name);os.chown(p,21004,21004);p.chmod(mode)",
            "p=pathlib.Path('/volumes/signal-config/envoy.json')",
            "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)",
            "with os.fdopen(fd,'wb') as out:",
            " out.write(data)",
            " out.flush();os.fsync(out.fileno())",
            "os.chown(p,21004,21004);p.chmod(0o600)",
        ]
    )


def prepare(inputs: LabInputs, directory: Path) -> None:
    if (
        directory.is_symlink()
        or directory.stat().st_uid != os.geteuid()
        or directory.stat().st_mode & 0o077
    ):
        raise ValueError("existing owner-only fixture directory required")
    private_json(directory / "envoy.json", proxy_configuration(inputs))
    private_json(directory / "compose.json", composition(inputs))
    fd = os.open(directory / "seed.py", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(seed_script())


def canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def signed_event(
    key: Ed25519PrivateKey, issuer: str, subject: str, *, sequence: int, previous: str
) -> dict[str, object]:
    event: dict[str, object] = {
        "issuer_id": issuer,
        "audience": "care-link-identity",
        "jti": str(uuid4()),
        "subject_id": subject,
        "event_type": "workload_compromised",
        "source_sequence": str(sequence),
        "previous_digest": previous,
        "event_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    event["digest"] = hashlib.sha256(canonical(event)).hexdigest()
    event["signature"] = base64.urlsafe_b64encode(key.sign(canonical(event))).rstrip(b"=").decode()
    validate_contract("Signal", event)
    return event


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def oracle(
    dsn: str, expected_database: str, issuer: str, event: dict[str, object]
) -> dict[str, object]:
    settings = conninfo_to_dict(dsn)
    if (
        settings.get("sslmode") != "verify-full"
        or not settings.get("sslrootcert")
        or settings.get("dbname") != expected_database
        or expected_database in {"postgres", "template0", "template1"}
    ):
        raise ValueError("exact isolated identity database and verified TLS required")
    signal_key = _digest(issuer + "\0" + str(event["jti"]))
    head_key = _digest(issuer + "\0" + str(event["subject_id"]))
    keys = {
        "signal": signal_key,
        "operation": "workload:" + signal_key,
        "head": head_key,
        "workload_state": head_key,
        "issuer": issuer,
    }
    with psycopg.connect(dsn, connect_timeout=3) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '3s'")
        if connection.execute("SELECT current_database()").fetchone() != (expected_database,):
            raise ValueError("wrong identity database")
        result: dict[str, object] = {}
        for kind, record_key in keys.items():
            row = connection.execute(
                "SELECT payload::text FROM identity.record WHERE kind=%s AND record_key=%s",
                (kind, record_key),
            ).fetchone()
            result[kind] = None if row is None else json.loads(str(row[0]))
    return result


def oracle_via_identity_pod(
    inputs: LabInputs, expected_database: str, issuer: str, event: dict[str, object]
) -> dict[str, object]:
    """Read exact workload keys with the deployed identity DSN kept inside its pod.

    The inline implementation is the same read-only, verify-full observer as
    direct mode. Only public machine identifiers enter stdin; only keyed state
    returns. No credentials or application configuration cross the exec channel.
    """
    code = (
        "import hashlib,json,pathlib,sys,psycopg\n"
        "from psycopg.conninfo import conninfo_to_dict\n"
        + inspect.getsource(_digest)
        + "\n"
        + inspect.getsource(oracle)
        + "\nargs=json.load(sys.stdin)\n"
        "config=json.loads(pathlib.Path('/config/identity.json').read_text())\n"
        "value=oracle(config['store_dsn'],args['expected_database'],args['issuer'],args['event'])\n"
        "print(json.dumps(value))\n"
    )
    result = kubectl(
        inputs,
        "-n",
        NAMESPACE,
        "exec",
        "-i",
        "deployment/identity",
        "-c",
        "application",
        "--",
        "python",
        "-c",
        code,
        stdin=json.dumps(
            {
                "expected_database": expected_database,
                "issuer": issuer,
                "event": {"jti": event["jti"], "subject_id": event["subject_id"]},
            }
        ),
    )
    return cast(dict[str, object], json.loads(result))


SENDER = """import http.client,json,socket,struct,sys
class U(http.client.HTTPConnection):
 def connect(self):
  s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(30)
  s.connect('/run/care-link/signals/proxy.sock')
  _,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
  if uid!=21004:raise PermissionError('unverified signal proxy')
  self.sock=s
c=U('identity.mesh.local',timeout=30)
for line in sys.stdin:
 event=json.loads(line);c.request('POST','/internal/v1/identity/signals',json.dumps(event),
  {'Content-Type':'application/json'})
 r=c.getresponse();raw=r.read(65537)
 if len(raw)>65536:raise RuntimeError('response cap exceeded')
 try:body=json.loads(raw)
 except ValueError:body={}
 allowed=['jti','state','accepted_sequence','message_key']
 print(json.dumps({'status':r.status,'body':{k:body[k] for k in allowed if k in body}}),flush=True)
c.close()
"""


def metadata() -> dict[str, object]:
    # The default pretty Workload API output is not used. Envoy /certs exposes
    # only public certificate metadata; JSON SVID/key export is forbidden here.
    code = READ_CERTIFICATES.replace("uid!=21002", "uid!=21004")
    return cast(
        dict[str, object],
        json.loads(
            run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "21004:21004",
                    PREFIX + "cert-probe",
                    "python",
                    "-c",
                    code,
                ],
                timeout=10,
            )
        ),
    )


def _private(path: Path) -> bytes:
    mode = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(mode.st_mode)
        or mode.st_uid != os.geteuid()
        or mode.st_mode & 0o077
    ):
        raise ValueError("owner-only regular qualification input required")
    return path.read_bytes()


def exercise(inputs: LabInputs, config: dict[str, object]) -> dict[str, object]:
    verify_session(inputs)
    issuer, subject = str(config["issuer_id"]), str(config["subject_id"])
    mapping = cast(dict[str, str], config["workload_subjects"])
    if mapping.get(subject) != PEER or list(mapping.values()).count(PEER) != 1:
        raise ValueError("only mapped identity_provider self-fence is supported")
    key = load_pem_private_key(_private(Path(str(config["signing_key_file"]))), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 local-source key required")
    database = str(config["expected_database"])
    transport = config.get("verification_transport", "direct_dsn")
    if transport not in {"direct_dsn", "identity_pod"}:
        raise ValueError("explicit known verification transport required")
    dsn = (
        _private(Path(str(config["verification_dsn_file"]))).decode().strip()
        if transport == "direct_dsn"
        else None
    )

    def observe(event: dict[str, object]) -> dict[str, object]:
        if transport == "identity_pod":
            return oracle_via_identity_pod(inputs, database, issuer, event)
        if dsn is None:
            raise ValueError("direct DSN required")
        return oracle(dsn, database, issuer, event)

    unknown_subject = str(uuid4())
    while unknown_subject in mapping:
        unknown_subject = str(uuid4())
    unknown = signed_event(key, issuer, unknown_subject, sequence=1, previous="0" * 64)
    before_unknown = observe(unknown)
    if cast(dict[str, object], before_unknown.get("issuer") or {}).get("quarantined") is True:
        raise ValueError("current nonquarantined local issuer required")
    # Fixed argv, no shell; neither private key nor DSN enters this process.
    sender = subprocess.Popen(  # noqa: S603
        [  # noqa: S607 - fixed Docker binary, exact leased container and fixed argv
            "docker",
            "exec",
            "-i",
            "--user",
            "21005:21004",
            PREFIX + "client",
            "python",
            "-u",
            "-c",
            SENDER,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def send(event: dict[str, object]) -> dict[str, object]:
        if sender.stdin is None or sender.stdout is None:
            raise RuntimeError("fixture sender unavailable")
        sender.stdin.write(json.dumps(event) + "\n")
        sender.stdin.flush()
        if not select.select([sender.stdout], [], [], 40)[0]:
            raise RuntimeError("fixture response deadline")
        line = sender.stdout.readline()
        if not line:
            raise RuntimeError("fixture sender closed")
        return cast(dict[str, object], json.loads(line))

    checkpoint = "unknown_mapping"
    committed_candidate: dict[str, object] | None = None
    try:
        denied = send(unknown)
        after_unknown = observe(unknown)
        if (
            denied != {"status": 403, "body": {"message_key": "identity.workload_mapping_denied"}}
            or before_unknown != after_unknown
        ):
            raise RuntimeError("unknown workload mapping did not deny without state change")
        before = metadata()
        baseline = cast(dict[str, int], before["upstream_connections"])
        if (
            baseline.get("cluster.identity_mesh.upstream_cx_active") != 1
            or baseline.get("cluster.identity_mesh.upstream_cx_total", 0) < 1
        ):
            raise RuntimeError("one established upstream connection required before self-fence")
        leaf = next(
            cert
            for cert in cast(list[dict[str, object]], before["loaded_certificates"])
            if any(
                name.get("uri") == PEER
                for name in cast(list[dict[str, str]], cert["subject_alt_names"])
            )
        )
        expires = datetime.fromisoformat(str(leaf["expiration_time"]))
        if expires <= datetime.now(UTC) + timedelta(seconds=30):
            raise RuntimeError("fresh current SVID required before restrictive test")
        provisional = signed_event(key, issuer, subject, sequence=1, previous="0" * 64)
        prior = observe(provisional)
        state = cast(dict[str, object], prior.get("workload_state") or {})
        if state.get("blocked") is True:
            raise ValueError("self workload already restricted; never reset it for this test")
        head = cast(dict[str, object], prior.get("head") or {"sequence": "0", "digest": "0" * 64})
        event = signed_event(
            key,
            issuer,
            subject,
            sequence=int(str(head["sequence"])) + 1,
            previous=str(head["digest"]),
        )
        checkpoint = "self_fence_send"
        committed_candidate = {"jti": event["jti"], "digest": event["digest"]}
        ack = send(event)
        checkpoint = "self_fence_sql"
        validate_contract("SignalAck", ack["body"])
        if ack["status"] != 200 or ack["body"] != {
            "jti": event["jti"],
            "state": "applied",
            "accepted_sequence": event["source_sequence"],
        }:
            raise RuntimeError("durable applied acknowledgment absent")
        sql = observe(event)
        operation = cast(dict[str, object], sql["operation"])
        if (
            operation.get("state") != "completed"
            or sql["signal"]["state"] != "applied"
            or sql["head"]["digest"] != event["digest"]
            or sql["workload_state"]["blocked"] is not True
        ):
            raise RuntimeError("acknowledged SQL restriction not durable/current")
        receipt = next(row for row in operation["fence_receipts"] if row["peer"] == PEER)
        code = (
            "import json;from pathlib import Path;from dataclasses import asdict;"
            "from care_link_workload_trust import UnixFenceClient;"
            "c=UnixFenceClient(Path('/run/care-link/fence/fence.sock'),21000);"
            "r=c.receipt(" + repr(receipt["command_id"]) + ");"
            "print(json.dumps({'receipt':None if r is None else asdict(r),"
            "'denied':sorted(c.current().denied)}))"
        )
        fence = json.loads(
            kubectl(
                inputs,
                "-n",
                NAMESPACE,
                "exec",
                "deployment/identity",
                "-c",
                "authorization",
                "--",
                "python",
                "-c",
                code,
            )
        )
        if (
            fence["receipt"] is None
            or fence["receipt"]["durable"] is not True
            or fence["receipt"]["peer"] != PEER
            or PEER not in fence["denied"]
        ):
            raise RuntimeError("actual custodian receipt absent")
        checkpoint = "same_connection_denial"
        repeat = send(event)
        after = metadata()
        a, b = before["upstream_connections"], after["upstream_connections"]
        same = (
            a["cluster.identity_mesh.upstream_cx_total"]
            == b["cluster.identity_mesh.upstream_cx_total"]
            and a["cluster.identity_mesh.upstream_cx_active"]
            == b["cluster.identity_mesh.upstream_cx_active"]
            == 1
            and b["cluster.identity_mesh.upstream_rq_total"]
            >= a["cluster.identity_mesh.upstream_rq_total"] + 2
        )
        passed = repeat["status"] == 403 and same and datetime.now(UTC) < expires
        return {
            "status": "passed" if passed else "failed",
            "mock_used": False,
            "scope": "custom signed local-source self restriction, not native SSF/CAEP",
            "unknown": {
                "jti": unknown["jti"],
                "denied": denied,
                "sql_unchanged": before_unknown == after_unknown,
            },
            "applied": {
                "jti": event["jti"],
                "digest": event["digest"],
                "ack": ack,
                "sql": sql,
                "custodian": fence,
            },
            "repeat": repeat,
            "same_existing_tls_connection": same,
            "before": before,
            "after": after,
            "remaining_state": "identity_provider remains fenced; no unfence/reset is performed",
        }
    except (OSError, RuntimeError, ValueError, KeyError, StopIteration, psycopg.Error) as error:
        # Preserve a truthful partial-effect result after any uncertain response.
        # Never retry with a replacement event or clear a restrictive fence.
        return {
            "status": "failed",
            "mock_used": False,
            "checkpoint": checkpoint,
            "error_type": type(error).__name__,
            "effect_may_be_committed": committed_candidate is not None,
            "candidate": committed_candidate,
            "remaining_state": "inspect durable state; no unfence/reset or replacement event",
        }
    finally:
        if sender.stdin is not None:
            try:
                sender.stdin.close()
            except OSError:
                pass  # A dead sender must not obscure a recorded uncertain effect.
        try:
            sender.wait(timeout=3)
        except subprocess.TimeoutExpired:
            sender.kill()
            sender.wait(timeout=3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "exercise"))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute-self-fence", action="store_true")
    args = parser.parse_args()
    inputs = load_inputs(args.inputs)
    if args.command == "prepare":
        if args.directory is None:
            parser.error("existing private --directory required")
        prepare(inputs, args.directory)
    else:
        if not args.execute_self_fence or args.config is None or args.output is None:
            parser.error("explicit --execute-self-fence, private --config and --output required")
        result = exercise(inputs, json.loads(_private(args.config)))
        private_json(args.output, result)
        if result["status"] != "passed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
