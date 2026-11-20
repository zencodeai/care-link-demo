"""Private observation must not change results or copy input/output content."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from tools.imp04_deployment import diagnostics
from tools.imp04_deployment.config import PREFIX


def marker(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "CONFIG", str(tmp_path))
    folder = tmp_path / "core"
    folder.mkdir(mode=0o700)
    path = folder / "qualification-trace.json"
    path.write_text(
        json.dumps(
            {
                "version": "imp04.trace.v1",
                "target": PREFIX,
                "role": "core",
                "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            }
        )
    )
    path.chmod(0o600)
    return path


def test_observer_is_default_off(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "CONFIG", str(tmp_path))
    client = httpx.Client()
    diagnostics.install(tmp_path, "core", [client])
    assert not client.event_hooks["request"] and not client.event_hooks["response"]


def test_trace_emits_only_fixed_metadata_and_preserves_error_response(tmp_path, monkeypatch):
    path = marker(tmp_path, monkeypatch)
    reply = {
        "code": "DEPENDENCY_UNAVAILABLE",
        "message_key": "manual.deadline",
        "private": "secret-output",
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json=reply))
    )
    diagnostics.install(tmp_path, "core", [client])
    operation = str(uuid4())
    response = client.post(
        "https://data.imp04.mesh/internal/v1/data/plan_read",
        headers={"Authorization": "secret-header"},
        json={"operation_id": operation, "private": "secret-input"},
    )
    assert response.status_code == 503 and response.json() == reply
    raw = path.with_suffix(".jsonl").read_text()
    assert all(secret not in raw for secret in ["secret-input", "secret-output", "secret-header"])
    row = json.loads(raw)
    assert row["operation_id"] == operation and row["message_key"] == "manual.deadline"
    assert path.with_suffix(".jsonl").stat().st_mode & 0o077 == 0


def test_arbitrary_error_keys_are_suppressed(tmp_path, monkeypatch):
    path = marker(tmp_path, monkeypatch)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"message_key": "manual.secret_content"})
        )
    )
    diagnostics.install(tmp_path, "core", [client])
    client.post("https://pdp.imp04.mesh/internal/v1/policy/evaluate", json={})
    assert "secret_content" not in path.with_suffix(".jsonl").read_text()


def test_removing_marker_immediately_stops_observation(tmp_path, monkeypatch):
    path = marker(tmp_path, monkeypatch)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    diagnostics.install(tmp_path, "core", [client])
    client.post("https://pdp.imp04.mesh/internal/v1/policy/evaluate", json={})
    previous = path.with_suffix(".jsonl").read_bytes()
    path.unlink()
    client.post("https://pdp.imp04.mesh/internal/v1/policy/evaluate", json={})
    assert path.with_suffix(".jsonl").read_bytes() == previous


def test_plain_proxy_failure_is_observed_without_copying_body(tmp_path, monkeypatch):
    path = marker(tmp_path, monkeypatch)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="upstream connect error secret-content")
        )
    )
    diagnostics.install(tmp_path, "core", [client])
    client.post("https://identity.imp04.mesh/internal/v1/manual-identity/authenticate", json={})
    raw = path.with_suffix(".jsonl").read_text()
    assert "secret-content" not in raw
    assert json.loads(raw)["proxy_error_category"] == "upstream_connect"
