"""Actual kernel UID isolation, run inside the named disposable Linux lab image.

These tests never create host accounts: setuid applies only to child processes
inside an explicitly authorized UID0 Linux test container. Native nonroot runs
skip rather than manufacture a positive kernel-identity observation.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from care_link_workload_trust import FenceServer, FenceStore

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires explicitly authorized disposable Linux container UID0/setuid test harness",
)
PEER = "spiffe://care-link.demo/lab/help"
COMMAND = "a" * 64
GROUP, READER, WRITER = 21000, 21001, 21002


def child(socket: Path, uid: int, expression: str) -> subprocess.CompletedProcess[str]:
    code = "\n".join(
        [
            "import json, os",
            "from pathlib import Path",
            "from care_link_workload_trust import UnixFenceClient, TrustDenied",
            f"c=UnixFenceClient(Path({str(socket)!r}),0)",
            expression,
        ]
    )
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        user=uid,
        group=GROUP,
        extra_groups=[GROUP],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


def test_distinct_reader_writer_custodian_and_live_open_channel() -> None:
    with tempfile.TemporaryDirectory(prefix="care-link-fence-users-") as temp:
        root = Path(temp)
        root.chmod(0o711)
        ledger = root / "ledger"
        ledger.mkdir(mode=0o700)
        channel = root / "channel"
        channel.mkdir(mode=0o710)
        os.chown(channel, 0, GROUP)
        store = FenceStore(ledger, 0)
        store.initialize(frozenset({PEER}))
        socket = channel / "fence.sock"
        server = FenceServer(
            socket,
            store,
            owner_uid=0,
            access_gid=GROUP,
            read_uids=frozenset({READER}),
            restrict_uid=WRITER,
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            before = child(socket, READER, f"print(c.current().admits({PEER!r}))")
            assert before.returncode == 0 and before.stdout.strip() == "True"
            denied = child(socket, READER, f"c.restrict({PEER!r},{COMMAND!r},0)")
            assert denied.returncode != 0 and "TrustDenied" in denied.stderr
            persistent_code = "\n".join(
                [
                    "import http.client,socket as sockets,json,sys",
                    "class U(http.client.HTTPConnection):",
                    " def connect(self):",
                    "  self.sock=sockets.socket(sockets.AF_UNIX,sockets.SOCK_STREAM)",
                    "  self.sock.settimeout(2)",
                    f"  self.sock.connect({str(socket)!r})",
                    "u=U('localhost');u.request('GET','/v1/fence')",
                    "r=u.getresponse();print(json.loads(r.read())['generation'],flush=True)",
                    "sys.stdin.readline()",
                    "u.request('GET','/v1/fence');r=u.getresponse()",
                    "print(json.loads(r.read())['generation'],flush=True);u.close()",
                ]
            )
            persistent = subprocess.Popen(  # noqa: S603 - fixed synthetic program and scoped UIDs
                [sys.executable, "-u", "-c", persistent_code],
                user=READER,
                group=GROUP,
                extra_groups=[GROUP],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert persistent.stdout is not None
                assert persistent.stdout.readline().strip() == "0"
                write = child(socket, WRITER, f"print(c.restrict({PEER!r},{COMMAND!r},0).durable)")
                assert write.returncode == 0 and write.stdout.strip() == "True"
                remaining, errors = persistent.communicate("continue\n", timeout=5)
                assert persistent.returncode == 0 and remaining.strip() == "1" and not errors
            finally:
                if persistent.poll() is None:
                    persistent.kill()
                    persistent.wait(timeout=2)
            after = child(socket, READER, f"print(c.current().admits({PEER!r}))")
            assert after.returncode == 0 and after.stdout.strip() == "False"
            receipt = child(socket, WRITER, f"print(c.receipt({COMMAND!r}).durable)")
            assert receipt.returncode == 0 and receipt.stdout.strip() == "True"
            protected = child(socket, READER, f"open({str(ledger / store.filename)!r}).read()")
            assert protected.returncode != 0 and "PermissionError" in protected.stderr
            wrong_server = child(
                socket, READER, f"UnixFenceClient(Path({str(socket)!r}),1).current()"
            )
            assert wrong_server.returncode != 0 and "TrustDenied" in wrong_server.stderr
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        assert json.loads((ledger / store.filename).read_text().splitlines()[-1])["peer"] == PEER
