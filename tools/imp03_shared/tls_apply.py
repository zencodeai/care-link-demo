"""Apply the exact shared-lab transport renewal; coordinator approval is external.

This module never restores automatically. All raw command output and rollback
material remain in a fresh owner-only backup directory, including on failure.
Only the primary operator invokes it under the separately approved maintenance.
"""

import base64
import hashlib
import json
import os
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from tools.imp02_application.tls import PinnedAddressTransport

from . import tls_renewal

ROOT = Path("/private/tmp/care-link-imp02-002")
CLUSTER = "care-link-imp02-002"
NODE = CLUSTER + "-control-plane"
NAMESPACE = CLUSTER
CONTEXT = "kind-" + CLUSTER
PKI_NAME = "imp02-pki"
HOST_PROXY = CLUSTER + "-host-proxy"
STATIC = CLUSTER + "-static"
PROTECTED = (CLUSTER + "-host-agent", CLUSTER + "-host-help")
HELP_VOLUME = CLUSTER + "-host-proxy-config"
STATIC_VOLUME = CLUSTER + "-static-config"
PYTHON = (
    "docker.io/library/python@sha256:"
    "82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56"
)
CERT_KEYS = tuple(name + ".crt" for name in ("ca", *tls_renewal.LEAVES))
SECRET_CERT_KEYS = ("ca.crt", "postgres.crt", "keycloak.crt")
NODE_FILES = {
    "ca.crt": ("/var/lib/care-link/imp02-002/config/identity/application/ca.crt", 21011),
    "main.crt": ("/var/lib/care-link/imp02-002/config/main/proxy/main.crt", 21002),
}
Record = dict[str, object]


class Runner(Protocol):
    def __call__(
        self, arguments: list[str], *, input: bytes | None = None, timeout: float = 30
    ) -> bytes: ...


class PrivateRunner:
    def __init__(self, backup: Path) -> None:
        self.backup = backup

    def __call__(
        self, arguments: list[str], *, input: bytes | None = None, timeout: float = 30
    ) -> bytes:
        prefix = "command-" + uuid4().hex
        try:
            result = subprocess.run(  # noqa: S603 - fixed target arguments and private input
                arguments, input=input, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "TLS maintenance command timed out; inspect private backup"
            ) from None
        _write(self.backup / (prefix + ".stdout"), result.stdout)
        _write(self.backup / (prefix + ".stderr"), result.stderr)
        _json(self.backup / (prefix + ".json"), {"argv": arguments, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError("TLS maintenance command failed; inspect private backup")
        return result.stdout


def _record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("Expected exact maintenance object")
    return cast(Record, value)


def _text(value: Record, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError("Missing maintenance field: " + key)
    return result


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected maintenance array")
    return cast(list[object], value)


def _directory(path: Path) -> None:
    info = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Owner-only absolute0700 maintenance directory required")


def _read(path: Path) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("Owner-only regular0600 maintenance file required")
    return path.read_bytes()


def _write(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())


def _json(path: Path, value: object) -> None:
    _write(path, (json.dumps(value, indent=2) + "\n").encode())


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _kubectl(*args: str) -> list[str]:
    return [
        "kubectl",
        "--kubeconfig",
        str(ROOT / "cluster/kubeconfig"),
        "--context",
        CONTEXT,
        "--request-timeout=20s",
        "-n",
        NAMESPACE,
        *args,
    ]


def _inspect(run: Runner, names: list[str]) -> list[Record]:
    return [_record(item) for item in _items(json.loads(run(["docker", "inspect", *names])))]


def _candidate(candidate: Path) -> Record:
    manifest = tls_renewal.public_summary(candidate)
    ca = x509.load_pem_x509_certificate(_read(candidate / "ca.crt"))
    now = datetime.now(UTC)
    ca.verify_directly_issued_by(ca)
    for name in tls_renewal.CERTIFICATES:
        cert = x509.load_pem_x509_certificate(_read(candidate / (name + ".crt")))
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValueError("Renewal candidate is not currently valid")
        cert.verify_directly_issued_by(ca)
        key_path = (
            candidate / "manual.key" if name == "manual" else ROOT / "secrets" / (name + ".key")
        )
        key = serialization.load_pem_private_key(_read(key_path), None)
        if key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ) != cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ):
            raise ValueError("Renewal candidate private-key binding differs")
    return manifest


def _preflight(run: Runner) -> Record:
    _directory(ROOT)
    _read(ROOT / "cluster/kubeconfig")
    lease = _record(json.loads(_read(ROOT / "cluster/lease.json")))
    if lease != {"session": "imp02-002", "cluster": CLUSTER}:
        raise ValueError("Wrong retained lab lease")
    node = _inspect(run, [NODE])[0]
    if (
        _record(_record(node["Config"])["Labels"]).get("io.x-k8s.kind.cluster") != CLUSTER
        or node.get("Name") != "/" + NODE
        or not _record(node["State"]).get("Running")
    ):
        raise ValueError("Docker node is not the exact running retained kind cluster")
    containers = _inspect(run, [HOST_PROXY, STATIC, *PROTECTED])
    by_name = {_text(item, "Name").removeprefix("/"): item for item in containers}
    if set(by_name) != {HOST_PROXY, STATIC, *PROTECTED}:
        raise ValueError("Exact retained surface/process inventory required")
    for name, volume in ((HOST_PROXY, HELP_VOLUME), (STATIC, STATIC_VOLUME)):
        container = by_name[name]
        mounts = [_record(x) for x in _items(container["Mounts"])]
        if not any(
            m.get("Type") == "volume"
            and m.get("Name") == volume
            and m.get("Destination") == "/config"
            for m in mounts
        ):
            raise ValueError("Retained surface config volume binding differs")
    protected: Record = {}
    for name in PROTECTED:
        item, state = by_name[name], _record(by_name[name]["State"])
        if state.get("Running") is not True:
            raise ValueError("Protected agent/help process is not running")
        protected[name] = {
            "id": item["Id"],
            "started_at": state["StartedAt"],
            "restart_count": item["RestartCount"],
        }
    return {"node_id": node["Id"], "protected": protected, "postgres": _postgres_identity(run)}


def _postgres_identity(run: Runner) -> Record:
    pods = _record(json.loads(run(_kubectl("get", "pods", "-l", "app=postgres", "-o", "json"))))
    items = _items(pods["items"])
    if len(items) != 1:
        raise ValueError("Exact single PostgreSQL pod required")
    pod = _record(items[0])
    status = _record(pod["status"])
    containers = [_record(x) for x in _items(status["containerStatuses"])]
    if (
        status.get("phase") != "Running"
        or len(containers) != 1
        or containers[0].get("ready") is not True
    ):
        raise ValueError("Existing PostgreSQL pod must be ready")
    start = (
        run(
            _kubectl(
                "exec",
                "deployment/postgres",
                "--",
                "psql",
                "-X",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-c",
                "SELECT pg_postmaster_start_time();",
            )
        )
        .decode()
        .strip()
    )
    return {
        "pod_uid": _record(pod["metadata"])["uid"],
        "restart_count": containers[0]["restartCount"],
        "postmaster_start_time": start,
    }


def _secret(run: Runner) -> Record:
    value = _record(json.loads(run(_kubectl("get", "secret", PKI_NAME, "-o", "json"))))
    metadata = _record(value["metadata"])
    if metadata.get("name") != PKI_NAME or metadata.get("namespace") != NAMESPACE:
        raise ValueError("Unexpected TLS Secret target")
    _text(metadata, "resourceVersion")
    data = _record(value["data"])
    if not set(SECRET_CERT_KEYS) <= set(data):
        raise ValueError("Expected retained TLS certificate entries missing")
    return value


VOLUME_SCRIPT = r"""
import base64,hashlib,json,os,pathlib,stat,sys,tempfile
request=json.load(sys.stdin)
files={'help':pathlib.Path('/volumes/help/help.crt'),
       'static':pathlib.Path('/volumes/static/static.crt')}
if set(request) != {'action','certificates'} or request['action'] not in {'read','write'}:
 raise ValueError('exact certificate operation required')
result={}
for name,path in files.items():
 info=path.lstat()
 if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600:
  raise ValueError('existing private regular certificate required')
 content=path.read_bytes()
 if request['action']=='write':
  item=request['certificates'][name]
  if hashlib.sha256(content).hexdigest()!=item['expected_old_sha256']:
   raise ValueError('existing certificate changed since snapshot')
  value=base64.b64decode(item['pem'],validate=True)
  fd,temp=tempfile.mkstemp(prefix='.imp03-tls-',dir=path.parent)
  try:
   with os.fdopen(fd,'wb') as stream:
    stream.write(value);stream.flush();os.fsync(stream.fileno())
    os.fchown(stream.fileno(),info.st_uid,info.st_gid)
   os.replace(temp,path)
  finally:
   if os.path.exists(temp):os.unlink(temp)
  content=value
 result[name]={'pem':base64.b64encode(content).decode(),
               'sha256':hashlib.sha256(content).hexdigest(),
               'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode)}
print(json.dumps(result))
"""


def _volumes(run: Runner, *, write: bool = False, certificates: Record | None = None) -> Record:
    name = "care-link-imp03-003-tls-maintenance-" + uuid4().hex[:12]
    mounts = [
        "--mount",
        f"type=volume,src={HELP_VOLUME},dst=/volumes/help" + ("" if write else ",readonly"),
        "--mount",
        f"type=volume,src={STATIC_VOLUME},dst=/volumes/static" + ("" if write else ",readonly"),
    ]
    args = [
        "docker",
        "create",
        "--interactive",
        "--pull=never",
        "--name",
        name,
        "--label",
        "care-link.scope=imp03-003-tls-maintenance",
        "--network",
        "none",
        "--read-only",
        "--cap-drop=ALL",
        "--cap-add=CHOWN",
        "--cap-add=DAC_OVERRIDE",
        "--security-opt=no-new-privileges",
        "--user",
        "0:0",
        "--pids-limit=32",
        "--memory=128m",
        *mounts,
        PYTHON,
        "python",
        "-c",
        VOLUME_SCRIPT,
    ]
    identifier = run(args).decode().strip()
    if not identifier or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("Invalid exact maintenance container ID")
    try:
        result = run(
            ["docker", "start", "--attach", "--interactive", identifier],
            input=json.dumps(
                {"action": "write" if write else "read", "certificates": certificates or {}}
            ).encode(),
        )
        return _record(json.loads(result))
    finally:
        run(["docker", "rm", "--force", identifier])


def _snapshot(run: Runner, candidate: Path, backup: Path, manifest: Record) -> Record:
    secret = _secret(run)
    _json(backup / "old-secret.json", secret)
    files = backup / "public-files"
    files.mkdir(mode=0o700)
    old_data = _record(secret["data"])
    records = {
        _text(_record(x), "name"): _record(x) for x in _items(manifest["renewed_certificates"])
    }
    for filename in CERT_KEYS:
        pem = _read(ROOT / "secrets" / filename)
        expected = _record(records[filename.removesuffix(".crt")]["old"])["pem_sha256"]
        if _digest(pem) != expected or (
            filename in SECRET_CERT_KEYS
            and base64.b64decode(_text(old_data, filename), validate=True) != pem
        ):
            raise ValueError("Current local/Secret certificate differs from renewal baseline")
        _write(files / ("local-" + filename), pem)
    node: Record = {}
    for filename, (target, uid) in NODE_FILES.items():
        pem = run(["docker", "exec", NODE, "cat", target])
        custody = run(["docker", "exec", NODE, "stat", "-c", "%u:%g:%a", target]).decode().strip()
        if pem != _read(files / ("local-" + filename)) or custody != f"{uid}:{uid}:600":
            raise ValueError("Node mounted certificate baseline/custody differs")
        _write(files / ("node-" + filename), pem)
        node[filename] = {"path": target, "sha256": _digest(pem), "uid": uid}
    volumes = _volumes(run)
    for name in ("help", "static"):
        item = _record(volumes[name])
        pem = base64.b64decode(_text(item, "pem"), validate=True)
        if pem != _read(files / ("local-" + name + ".crt")):
            raise ValueError("Surface volume certificate differs from renewal baseline")
        _write(files / ("volume-" + name + ".crt"), pem)
    bindings: Record = {"node": node, "volumes": volumes}
    _json(backup / "old-public-bindings.json", bindings)
    patch = {
        "metadata": {"resourceVersion": _record(secret["metadata"])["resourceVersion"]},
        "data": {
            name: base64.b64encode(_read(candidate / name)).decode() for name in SECRET_CERT_KEYS
        },
    }
    _json(backup / "certificate-patch.json", patch)
    return bindings


def _replace_local(candidate: Path, filename: str) -> None:
    directory = ROOT / "secrets"
    _directory(directory)
    target = directory / filename
    _read(target)
    temporary = directory / (".imp03-renewal-" + uuid4().hex)
    try:
        _write(temporary, _read(candidate / filename))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_node(run: Runner, candidate: Path) -> None:
    # One exec owns staging, stdin write, install and rename. Docker archive/cp
    # does not consistently observe kind's process-mounted /tmp namespace.
    for filename, (target, uid) in NODE_FILES.items():
        destination = target + ".imp03-renewal-" + uuid4().hex
        script = (
            "set -eu\numask 077\n"
            "stage=$(mktemp -d /tmp/care-link-imp03-003-tls.XXXXXX)\n"
            'trap \'rm -f -- "$stage/certificate.crt" "'
            + destination
            + '"; rmdir -- "$stage"\' EXIT\n'
            'cat > "$stage/certificate.crt"\n'
            f'install -o {uid} -g {uid} -m 0600 "$stage/certificate.crt" '
            f"'{destination}'\n"
            f"mv -f -- '{destination}' '{target}'\n"
        )
        run(
            ["docker", "exec", "--interactive", NODE, "sh", "-c", script],
            input=_read(candidate / filename),
        )


def _wait_projected(run: Runner, candidate: Path, *, timeout: float = 120) -> None:
    end = time.monotonic() + timeout
    for role in ("postgres", "keycloak"):
        expected = {
            _digest(_read(candidate / (role + ".crt"))): "/cert/" + role + ".crt",
            _digest(_read(candidate / "ca.crt")): "/cert/ca.crt",
        }
        while True:
            output = run(
                _kubectl(
                    "exec",
                    "deployment/" + role,
                    "--",
                    "sha256sum",
                    "/cert/" + role + ".crt",
                    "/cert/ca.crt",
                ),
                timeout=max(1, min(25, end - time.monotonic())),
            ).decode()
            actual = {
                line.split()[0]: line.split()[-1] for line in output.splitlines() if line.split()
            }
            if actual == expected:
                break
            if time.monotonic() >= end:
                raise TimeoutError("Projected renewal certificate update deadline exceeded")
            time.sleep(min(2, max(0, end - time.monotonic())))


def _check_unchanged(run: Runner, before: Record) -> None:
    if _postgres_identity(run) != before["postgres"]:
        raise ValueError("PostgreSQL process/pod identity changed during certificate reload")
    protected = _record(before["protected"])
    for item in _inspect(run, list(PROTECTED)):
        name, state = _text(item, "Name").removeprefix("/"), _record(item["State"])
        actual = {
            "id": item["Id"],
            "started_at": state["StartedAt"],
            "restart_count": item["RestartCount"],
        }
        if state.get("Running") is not True or actual != protected.get(name):
            raise ValueError("Protected host agent/help process changed during TLS maintenance")


class TLSStream(Protocol):
    def get_extra_info(self, name: str) -> object: ...


class TLSMetadata(Protocol):
    def getpeercert(self, binary_form: bool = False) -> object: ...

    def version(self) -> str | None: ...


def _verify_tls(run: Runner, candidate: Path) -> Record:
    observed: Record = {}
    surfaces = (
        ("main", "https://main.localhost:18443", "/"),
        (
            "keycloak",
            "https://id.localhost:20443",
            "/realms/care-link-imp02/.well-known/openid-configuration",
        ),
        ("help", "https://help.localhost:19443", "/"),
        ("static", "https://static.localhost:21443", "/fallback"),
    )
    for name, origin, path in surfaces:
        expected = x509.load_pem_x509_certificate(_read(candidate / (name + ".crt")))
        with httpx.Client(
            transport=PinnedAddressTransport(origin, "127.0.0.1", str(candidate / "ca.crt")),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            with client.stream("GET", origin + path, timeout=15) as response:
                if response.status_code != 200:
                    raise ValueError("Refreshed HTTPS surface did not return expected availability")
                raw_stream = response.extensions.get("network_stream")
                if raw_stream is None:
                    raise ValueError("TLS stream evidence unavailable")
                stream = cast(TLSStream, raw_stream)
                metadata = stream.get_extra_info("ssl_object")
                # httpcore exposes CPython's low-level _ssl._SSLSocket here,
                # rather than ssl.SSLSocket/SSLObject. The transport above has
                # already verified its CA and hostname; inspect its public API.
                if not callable(getattr(metadata, "getpeercert", None)) or not callable(
                    getattr(metadata, "version", None)
                ):
                    raise ValueError("Verified HTTPS SSL object unavailable")
                connection = cast(TLSMetadata, metadata)
                peer = connection.getpeercert(True)
                tls_version = connection.version()
                if not isinstance(peer, bytes):
                    raise ValueError("Actual HTTPS peer certificate unavailable")
                actual = x509.load_der_x509_certificate(peer)
                fingerprint = actual.fingerprint(hashes.SHA256()).hex()
                if fingerprint != expected.fingerprint(hashes.SHA256()).hex():
                    raise ValueError("HTTPS listener did not load exact renewed leaf")
                if name == "keycloak":
                    raw = response.read()
                    if len(raw) > 128 * 1024 or _record(json.loads(raw)).get("issuer") != (
                        origin + "/realms/care-link-imp02"
                    ):
                        raise ValueError("Existing provider realm discovery binding differs")
                observed[name] = {
                    "status": 200,
                    "tls_version": tls_version,
                    "peer_fingerprint_sha256": fingerprint,
                    "verify_full_hostname_and_ca": True,
                }
    # Only a fixed SELECT is issued. The existing pod password enters process
    # environment through its already configured variable, never command argv.
    query = (
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At -v ON_ERROR_STOP=1 '
        '"host=postgres.care-link-imp02-002.svc.cluster.local hostaddr=127.0.0.1 port=5432 '
        'user=postgres dbname=postgres sslmode=verify-full sslrootcert=/cert/ca.crt" '
        '-c "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid();"'
    )
    result = run(_kubectl("exec", "deployment/postgres", "--", "sh", "-c", query)).decode().strip()
    if result != "t|TLSv1.3":
        raise ValueError("PostgreSQL verify-full TLS1.3 connection was not observed")
    observed["postgres"] = {"verify_full": True, "negotiated_tls_version": "TLSv1.3"}
    return observed


def _assert_current_secret(run: Runner, candidate: Path, backup: Path) -> None:
    original = _record(json.loads(_read(backup / "old-secret.json")))
    actual = _secret(run)
    old_data, data = _record(original["data"]), _record(actual["data"])
    expected = {
        **old_data,
        **{name: base64.b64encode(_read(candidate / name)).decode() for name in SECRET_CERT_KEYS},
    }
    if data != expected:
        raise ValueError("Secret changed outside exact certificate entries or certificate mismatch")
    if _record(original["metadata"]).get("uid") != _record(actual["metadata"]).get("uid"):
        raise ValueError("Retained TLS Secret resource identity changed")


def verify(candidate_dir: Path, backup_dir: Path, *, runner: Runner | None = None) -> Record:
    """Verify named files/processes; HTTPS and application checks remain separate."""
    _directory(backup_dir)
    manifest = _candidate(candidate_dir)
    run = runner or PrivateRunner(backup_dir)
    before = _record(json.loads(_read(backup_dir / "before.json")))
    _assert_current_secret(run, candidate_dir, backup_dir)
    for filename in CERT_KEYS:
        if _read(ROOT / "secrets" / filename) != _read(candidate_dir / filename):
            raise ValueError("Local certificate file does not match approved candidate")
    for filename, (target, uid) in NODE_FILES.items():
        if (
            run(["docker", "exec", NODE, "cat", target]) != _read(candidate_dir / filename)
            or run(["docker", "exec", NODE, "stat", "-c", "%u:%g:%a", target]).decode().strip()
            != f"{uid}:{uid}:600"
        ):
            raise ValueError("Node certificate file/custody mismatch")
    volumes = _volumes(run)
    for name in ("help", "static"):
        if _record(volumes[name]).get("sha256") != _digest(_read(candidate_dir / (name + ".crt"))):
            raise ValueError("Surface volume certificate mismatch")
    _wait_projected(run, candidate_dir)
    _check_unchanged(run, before)
    transport = _verify_tls(run, candidate_dir)
    return {
        "verified_at": datetime.now(UTC).isoformat(),
        "certificate_bindings_match": True,
        "transport": transport,
        "other_secret_entries_unchanged": True,
        "postgres_process_preserved": True,
        "host_agent_help_processes_preserved": True,
        "candidate_profile": manifest["profile"],
        "certificate_digests": {name: _digest(_read(candidate_dir / name)) for name in CERT_KEYS},
        "limits": (
            "Verified certificate/custody/process/TLS and discovery; actor regressions separate."
        ),
    }


def apply(candidate_dir: Path, backup_dir: Path, *, runner: Runner | None = None) -> Record:
    """Apply the exact maintenance proposal once; partial failure retains all private backup."""
    manifest = _candidate(candidate_dir)
    if not backup_dir.is_absolute() or backup_dir.exists() or backup_dir.is_symlink():
        raise ValueError("Fresh absolute private backup required; existing backup refused")
    backup_dir.mkdir(mode=0o700)
    _directory(backup_dir)
    run = runner or PrivateRunner(backup_dir)
    before = _preflight(run)
    _json(backup_dir / "before.json", before)
    bindings = _snapshot(run, candidate_dir, backup_dir, manifest)
    run(
        _kubectl(
            "patch",
            "secret",
            PKI_NAME,
            "--type=merge",
            "--patch-file",
            str(backup_dir / "certificate-patch.json"),
            "-o",
            "json",
        )
    )
    for filename in CERT_KEYS:
        _replace_local(candidate_dir, filename)
    _replace_node(run, candidate_dir)
    return _finish_after_node(run, candidate_dir, backup_dir, bindings)


def _finish_after_node(
    run: Runner, candidate_dir: Path, backup_dir: Path, bindings: Record, *, resumed: bool = False
) -> Record:
    old_volumes = _record(bindings["volumes"])
    _volumes(
        run,
        write=True,
        certificates={
            name: {
                "expected_old_sha256": _record(old_volumes[name])["sha256"],
                "pem": base64.b64encode(_read(candidate_dir / (name + ".crt"))).decode(),
            }
            for name in ("help", "static")
        },
    )
    _wait_projected(run, candidate_dir)
    reloaded = (
        run(
            _kubectl(
                "exec",
                "deployment/postgres",
                "--",
                "psql",
                "-X",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-c",
                "SELECT pg_reload_conf();",
            )
        )
        .decode()
        .strip()
    )
    if reloaded != "t":
        raise ValueError("PostgreSQL reload was not acknowledged")
    for role in ("keycloak", "identity", "main"):
        run(_kubectl("rollout", "restart", "deployment/" + role))
        run(_kubectl("rollout", "status", "deployment/" + role, "--timeout=120s"), timeout=140)
    for name in (HOST_PROXY, STATIC):
        run(["docker", "restart", "--time", "15", name], timeout=45)
    result = verify(candidate_dir, backup_dir, runner=run)
    result["actions"] = [
        (
            "Prior certificate-only Secret patch and six local replacements verified; not repeated"
            if resumed
            else "resourceVersion-bound certificate-only Secret patch and local replacements"
        ),
        "two exact node public files atomically replaced through process-local stdin staging",
        "help/static volume certificates replaced preserving keys/owners",
        "projected certificate digests observed; PostgreSQL config reloaded",
        "keycloak/identity/main sequential rollout; exact host-proxy/static restart",
    ]
    result["resumed_after_node_stage"] = resumed
    _json(backup_dir / "public-result.json", result)
    return result


def resume_after_node_stage(
    candidate_dir: Path, backup_dir: Path, *, runner: Runner | None = None
) -> Record:
    """Explicit continuation for only a failed node stage; never rebase old state."""
    manifest = _candidate(candidate_dir)
    _directory(backup_dir)
    if (backup_dir / "public-result.json").exists():
        raise ValueError("Completed maintenance cannot be resumed")
    run = runner or PrivateRunner(backup_dir)
    before = _record(json.loads(_read(backup_dir / "before.json")))
    if _preflight(run) != before:
        raise ValueError("Original protected process/node baseline changed before resume")
    _assert_current_secret(run, candidate_dir, backup_dir)
    patch = _record(json.loads(_read(backup_dir / "certificate-patch.json")))
    expected_patch = {
        name: base64.b64encode(_read(candidate_dir / name)).decode() for name in SECRET_CERT_KEYS
    }
    if patch.get("data") != expected_patch:
        raise ValueError("Candidate differs from original certificate patch")
    records = {
        _text(_record(item), "name"): _record(item)
        for item in _items(manifest["renewed_certificates"])
    }
    for filename in CERT_KEYS:
        old = _read(backup_dir / "public-files" / ("local-" + filename))
        if _digest(old) != _record(records[filename.removesuffix(".crt")]["old"])["pem_sha256"]:
            raise ValueError("Original certificate backup differs from candidate baseline")
        if _read(ROOT / "secrets" / filename) != _read(candidate_dir / filename):
            raise ValueError("Resume requires the completed six local certificate replacements")
    bindings = _record(json.loads(_read(backup_dir / "old-public-bindings.json")))
    for filename, (target, uid) in NODE_FILES.items():
        current = run(["docker", "exec", NODE, "cat", target])
        original = _read(backup_dir / "public-files" / ("node-" + filename))
        custody = run(["docker", "exec", NODE, "stat", "-c", "%u:%g:%a", target]).decode().strip()
        if (
            current not in (original, _read(candidate_dir / filename))
            or custody != f"{uid}:{uid}:600"
        ):
            raise ValueError("Node certificate is outside original-or-candidate resume scope")
    volumes = _volumes(run)
    if volumes != bindings["volumes"]:
        raise ValueError("Surface volumes changed after snapshot; later-stage resume refused")
    _replace_node(run, candidate_dir)
    return _finish_after_node(run, candidate_dir, backup_dir, bindings, resumed=True)
