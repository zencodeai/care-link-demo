"""Probe guard/error classification, not evidence of deployed control behavior."""

import errno
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.imp03_shared import negative


def test_missing_credential_path_is_not_accepted_as_permission_enforcement(tmp_path):
    assert negative.denied_permission(tmp_path / "absent") == {
        "permission_denied": False,
        "errno": errno.ENOENT,
    }
    existing = tmp_path / "credential"
    existing.write_text("private fixture value")
    assert negative.denied_permission(existing)["permission_denied"] is False


def test_only_permission_errors_count_for_sibling_access(monkeypatch):
    def deny(_path, *_args, **_kwargs):
        raise PermissionError(errno.EACCES, "fixture denial")

    monkeypatch.setattr(Path, "open", deny)
    assert negative.denied_permission(Path("/probe/data/configuration/config.json")) == {
        "permission_denied": True,
        "errno": errno.EACCES,
    }


def ssl_failure(reason):
    error = ssl.SSLError("private TLS diagnostic")
    error.reason = reason
    return error


@pytest.mark.parametrize(
    "reason,passed",
    [("TLSV13_ALERT_CERTIFICATE_REQUIRED", True), ("CERTIFICATE_VERIFY_FAILED", False)],
)
def test_absent_svid_does_not_mislabel_untrusted_server_as_client_denial(
    monkeypatch, reason, passed
):
    monkeypatch.setattr(negative, "_context", lambda _bundle: object())

    def connect(*_args):
        raise ssl_failure(reason)

    monkeypatch.setattr(negative, "_connect", connect)
    result = negative.no_svid_probe(Path("/fixture/bundle.pem"))
    assert result["passed"] is passed
    assert "private TLS diagnostic" not in str(result)


def test_mesh_probe_refuses_outside_continuation_addresses():
    with pytest.raises(ValueError, match="continuation mesh"):
        negative._connect(None, "172.29.33.13", "data")


def test_absent_svid_reads_delayed_tls13_alert_before_http_write(monkeypatch):
    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def recv(self, _count):
            raise ssl_failure("TLSV13_ALERT_CERTIFICATE_REQUIRED")

    monkeypatch.setattr(negative, "_context", lambda _bundle: object())
    monkeypatch.setattr(negative, "_connect", lambda *_args: Stream())
    monkeypatch.setattr(
        negative, "_request", lambda *_args, **_kwargs: pytest.fail("HTTP write raced TLS alert")
    )
    assert negative.no_svid_probe(Path("/fixture/bundle.pem"))["passed"] is True


@pytest.mark.parametrize(
    "remote_alert", ["SSLV3_ALERT_CERTIFICATE_EXPIRED", "SSLV3_ALERT_CERTIFICATE_UNKNOWN"]
)
@pytest.mark.parametrize("close_before_expiry", [False, True])
def test_expiry_claim_requires_the_same_connection_survive_until_expiry(
    monkeypatch, close_before_expiry, remote_alert
):
    now = [datetime(2026, 11, 13, 12, 0, tzinfo=UTC)]
    expires = now[0] + timedelta(seconds=5)

    class Clock:
        @staticmethod
        def now(_zone):
            return now[0]

    class Stream:
        def fileno(self):
            return 7

        def close(self):
            pass

    stream = Stream()
    connections = []
    requests = []

    def connect(*_args):
        connections.append(True)
        if len(connections) == 1:
            return stream
        raise ssl_failure(remote_alert)

    def request(actual, _path, **_kwargs):
        assert actual is stream
        requests.append(now[0])
        if close_before_expiry and len(requests) > 1:
            raise ConnectionResetError("fixture closed before expiry")
        return 403 if now[0] >= expires else 422

    def sleep(seconds):
        now[0] += timedelta(seconds=seconds)

    leaf = SimpleNamespace(not_valid_after_utc=expires, public_bytes=lambda _encoding: b"leaf")
    monkeypatch.setattr(negative, "datetime", Clock)
    monkeypatch.setattr(negative.time, "sleep", sleep)
    monkeypatch.setattr(negative, "_issued_svid", lambda *_args: (Path("cert"), Path("key"), leaf))
    monkeypatch.setattr(negative, "_context", lambda *_args: object())
    monkeypatch.setattr(negative, "_connect", connect)
    monkeypatch.setattr(negative, "_request", request)
    monkeypatch.setattr(
        negative,
        "LAST_RESPONSE",
        {"code": "INVALID_REQUEST", "message_key": "manual.invalid_request"},
    )
    result = negative.expiry_probe(Path("api"), Path("binary"), Path("bundle"))
    assert len(connections) == 2
    assert result["same_connection_preserved_until_expiry"] is not close_before_expiry
    assert result["passed"] is not close_before_expiry
    assert result["new_connection_tls_expiry_rejected"] is True
