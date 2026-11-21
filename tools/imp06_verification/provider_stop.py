"""Exercise provider-stop attestation on an isolated disposable Linux process."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from care_link_workload_trust import FenceServer, FenceStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_INFERENCE = "spiffe://care-link.demo/demo/inference"
_DATA, _CONTROL, _GROUP = 65532, 65531, 65530
_OLD, _NEW = "qualification-provider-old", "qualification-provider-replacement"
_TARGET, _ISSUER = "imp06-005-disposable", "fixture-host-stop"
_PROVIDER = """
import socket
import sys
import threading

sockets = [socket.socket(fileno=int(argument)) for argument in sys.argv[1:]]
for connection in sockets:
    if connection.recv(14, socket.MSG_WAITALL) != b"synthetic-work":
        raise RuntimeError("unexpected fixture work")
    connection.sendall(b"accepted")
threading.Event().wait(30)
"""
_RESTRICT = """
from pathlib import Path
import sys
from care_link_workload_trust import UnixFenceClient

result = UnixFenceClient(Path(sys.argv[1]), 0).restrict(sys.argv[2], sys.argv[3], 0)
if not result.durable or result.generation != 1:
    raise RuntimeError("restriction was not acknowledged")
"""
_VERIFY = """
from pathlib import Path
import sys
from care_link_workload_trust import UnixFenceClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tools.imp06_runtime.provider_stop import ProviderStopAuthority

path, key, issuer, target, old, new = sys.argv[1:]
base = Path(path)
authority = ProviderStopAuthority(
    base / "receipts",
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)),
    UnixFenceClient(base / "socket" / "fence.sock", 0),
    issuer=issuer,
    target=target,
    owner_uid=0,
    current_generation=new,
)
observed = authority.verified_stop_time(old)
print(observed.isoformat() if observed is not None else "unverified")
"""


def _child(code: str, uid: int, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code, *args],
        user=uid,
        group=_GROUP,
        extra_groups=(),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def _stop_fixture_provider(restrict: Callable[[], None]) -> dict[str, object]:
    first, first_child = socket.socketpair()
    second, second_child = socket.socketpair()
    descriptors = (first_child.fileno(), second_child.fileno())
    with (
        first,
        second,
        first_child,
        second_child,
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", _PROVIDER, *map(str, descriptors)],
            pass_fds=descriptors,
            user=65529,
            group=65529,
            extra_groups=(),
        ) as provider,
    ):
        first_child.close()
        second_child.close()
        try:
            for connection in (first, second):
                connection.settimeout(1)
                connection.sendall(b"synthetic-work")
                _require(
                    connection.recv(8, socket.MSG_WAITALL) == b"accepted",
                    "provider did not accept work",
                )
            first.settimeout(0.05)
            try:
                first.recv(1)
                raise RuntimeError("fixture provider unexpectedly completed")
            except TimeoutError:
                _require(provider.poll() is None, "provider exited on client timeout")
            second.close()
            restrict()
            _require(provider.poll() is None, "provider exited on client disconnect")
            provider.kill()
            _require(provider.wait(timeout=3) == -signal.SIGKILL, "provider stop unconfirmed")
            _require(first.recv(1) == b"", "provider socket stayed open")
            return {
                "pid": provider.pid,
                "exit_code": provider.returncode,
                "client_timeout_while_provider_alive": True,
                "client_disconnect_while_provider_alive": True,
                "compute_process_exited": True,
            }
        finally:
            if provider.poll() is None:
                provider.kill()


def _canonical(record: object) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")


def _verify_stopped(root: Path, fence_path: Path) -> dict[str, object]:
    signer = Ed25519PrivateKey.generate()
    verifier_args = (
        str(root),
        signer.public_key().public_bytes_raw().hex(),
        _ISSUER,
        _TARGET,
        _OLD,
        _NEW,
    )
    _require(
        _child(_VERIFY, _DATA, *verifier_args) == "unverified",
        "accepted empty stop authority",
    )
    command = str(uuid4())

    def restrict_while_running() -> None:
        _child(_RESTRICT, _CONTROL, str(fence_path), _INFERENCE, command)
        _require(
            _child(_VERIFY, _DATA, *verifier_args) == "unverified",
            "a restriction cannot establish provider exit",
        )

    stop_evidence = _stop_fixture_provider(restrict_while_running)
    stopped_at = datetime.now(UTC)
    receipt = {
        "attestation": "care-link.provider-process-exited.v1",
        "issuer": _ISSUER,
        "target": _TARGET,
        "bridge_generation": _OLD,
        "fence_command": command,
        "restriction_generation": 1,
        "provider_instance_digest": sha256(f"{_OLD}:{stop_evidence['pid']}".encode()).hexdigest(),
        "stop_evidence_digest": sha256(_canonical(stop_evidence)).hexdigest(),
        "stopped_at": stopped_at.isoformat().replace("+00:00", "Z"),
    }
    signed = {**receipt, "signature": signer.sign(_canonical(receipt)).hex()}
    path = root / "receipts" / (_OLD + ".json")
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(_canonical(signed))
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    _require(
        _child(_VERIFY, _DATA, *verifier_args) == stopped_at.isoformat(),
        "verified hard stop was rejected",
    )
    return {
        **{key: value for key, value in stop_evidence.items() if key != "pid"},
        "fence_alone_denied": True,
        "verified_after_hard_exit": True,
    }


def main() -> None:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("Use an isolated Linux fixture with UID separation")
    with tempfile.TemporaryDirectory(prefix="imp06-stop-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        (root / "receipts").mkdir(mode=0o755)
        (root / "fence").mkdir(mode=0o700)
        (root / "socket").mkdir(mode=0o710)
        os.chown(root / "socket", 0, _GROUP)
        store = FenceStore(root / "fence", 0)
        store.initialize(frozenset({_INFERENCE}))
        fence_path = root / "socket" / "fence.sock"
        with FenceServer(
            fence_path,
            store,
            owner_uid=0,
            access_gid=_GROUP,
            read_uids=frozenset({_DATA}),
            restrict_uid=_CONTROL,
        ) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = _verify_stopped(root, fence_path)
            finally:
                server.shutdown()
                thread.join()
    print(
        json.dumps(
            {
                "scope": "isolated synthetic provider process and kernel-authenticated fence",
                "checks": result,
                "lm_studio_contacted": False,
                "database_contacted": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
