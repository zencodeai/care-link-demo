"""Real native socket custody checks; requires the local Unix bind test lease."""

import os
import socket
import tempfile
from pathlib import Path

import pytest
from care_link_workload_trust import TrustDenied
from care_link_workload_trust.socket_custody import SocketCustody


def test_only_owned_refused_socket_is_recovered_and_listener_lease_is_exclusive() -> None:
    with tempfile.TemporaryDirectory(prefix="cl-socket-") as scratch:
        root = Path(scratch)
        root.chmod(0o710)
        path = root / "a.sock"
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(path))
        stale.close()
        assert path.exists()
        custody = SocketCustody(path, os.geteuid(), os.getegid())
        try:
            assert not path.exists()
            with pytest.raises(OSError):
                SocketCustody(path, os.geteuid(), os.getegid())
        finally:
            custody.close()
        active = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        active.bind(str(path))
        active.listen(1)
        try:
            with pytest.raises(TrustDenied, match="already active"):
                SocketCustody(path, os.geteuid(), os.getegid())
            assert path.exists()
        finally:
            active.close()


def test_listener_recovery_preserves_nonsocket_or_symlink() -> None:
    with tempfile.TemporaryDirectory(prefix="cl-socket-") as scratch:
        root = Path(scratch)
        root.chmod(0o710)
        path = root / "a.sock"
        path.write_text("preserve synthetic marker")
        with pytest.raises(TrustDenied):
            SocketCustody(path, os.geteuid(), os.getegid())
        assert path.read_text() == "preserve synthetic marker"
        path.unlink()
        target = root / "target"
        target.write_text("preserve target")
        path.symlink_to(target)
        with pytest.raises(TrustDenied):
            SocketCustody(path, os.geteuid(), os.getegid())
        assert path.is_symlink() and target.read_text() == "preserve target"
