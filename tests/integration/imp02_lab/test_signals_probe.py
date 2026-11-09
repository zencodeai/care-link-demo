"""Source fixture checks; no deployed fencing qualification is implied."""

import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from tools.imp02_lab import signals_probe
from tools.imp02_lab.model import LabInputs


def inputs(tmp_path: Path) -> LabInputs:
    image = "docker.io/library/synthetic-fixture@sha256:" + "a" * 64
    return LabInputs(
        dict.fromkeys(("envoy", "spire_agent", "python"), image),
        tmp_path / "kind",
        tmp_path / "calico",
        tmp_path / "state",
        "a" * 64,
        "b" * 64,
    )


def test_signal_fixture_keeps_signer_outside_and_peer_sockets_separate(tmp_path: Path) -> None:
    value = signals_probe.composition(inputs(tmp_path))
    services = value["services"]
    assert services["signal-proxy"]["pid"] == "container:care-link-imp02-002-host-agent"
    assert services["signal-proxy"]["user"] == "21004:21004"
    assert services["signal-client"]["user"] == "21005:21004"
    assert services["signal-cert-probe"]["user"] == "21004:21004"
    assert services["signal-client"]["network_mode"] == "none"
    assert services["signal-cert-probe"]["network_mode"] == "none"
    assert [v["source"] for v in services["signal-client"]["volumes"]] == ["signal-outbound"]
    assert [v["source"] for v in services["signal-cert-probe"]["volumes"]] == ["signal-admin"]
    for name, service in services.items():
        assert service["cap_drop"] == ["ALL"]
        assert all(v["type"] == "volume" for v in service["volumes"])
        if name != "signal-proxy":
            assert all(v["source"] != "workload-api" for v in service["volumes"])
    assert "key_file" not in str(value) and "docker.sock" not in str(value)
    compile(signals_probe.seed_script(), "signal-seed", "exec")
    compile(signals_probe.SENDER, "signal-sender", "exec")


def test_signal_egress_has_only_exact_route_and_fixed_peer_tls(tmp_path: Path) -> None:
    value = signals_probe.proxy_configuration(inputs(tmp_path))
    assert value["node"]["id"] == signals_probe.PEER
    resources = value["static_resources"]
    assert len(resources["listeners"]) == 1
    listener = resources["listeners"][0]
    assert listener["address"]["pipe"]["mode"] == 0o660
    hcm = listener["filter_chains"][0]["filters"][0]["typed_config"]
    routes = hcm["route_config"]["virtual_hosts"][0]["routes"]
    assert len(routes) == 1  # unmatched requests have no route
    assert routes[0]["match"]["path"] == signals_probe.PATH
    assert routes[0]["match"]["headers"][0]["string_match"] == {"exact": "POST"}
    mesh = next(c for c in resources["clusters"] if c["name"] == "identity_mesh")
    assert mesh["dns_lookup_family"] == "V4_ONLY"
    tls = mesh["transport_socket"]["typed_config"]["common_tls_context"]
    assert tls["tls_params"] == {
        "tls_minimum_protocol_version": "TLSv1_3",
        "tls_maximum_protocol_version": "TLSv1_3",
    }
    assert tls["tls_certificate_sds_secret_configs"][0]["name"] == signals_probe.PEER
    assert value["admin"]["address"]["pipe"]["mode"] == 0o600


def test_signed_signal_digest_and_signature_bind_every_event_field() -> None:
    key = Ed25519PrivateKey.generate()
    event = signals_probe.signed_event(
        key, "local-test-source", str(uuid4()), sequence=3, previous="1" * 64
    )
    signature = str(event.pop("signature"))
    key.public_key().verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        signals_probe.canonical(event),
    )
    digest = event.pop("digest")
    assert digest == hashlib.sha256(signals_probe.canonical(event)).hexdigest()
    event["digest"] = digest
    event["source_sequence"] = "4"
    with pytest.raises(InvalidSignature):
        key.public_key().verify(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
            signals_probe.canonical(event),
        )


def test_prepare_requires_private_custody_and_never_overwrites(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    signals_probe.prepare(inputs(tmp_path), tmp_path)
    assert (tmp_path / "envoy.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        signals_probe.prepare(inputs(tmp_path), tmp_path)
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="owner-only"):
        signals_probe.prepare(inputs(tmp_path), tmp_path)


def test_sql_oracle_refuses_default_database_before_connecting() -> None:
    with pytest.raises(ValueError, match="isolated identity database"):
        signals_probe.oracle(
            "dbname=postgres sslmode=verify-full sslrootcert=/unused", "postgres", "local", {}
        )


def test_exercise_rejects_any_other_workload_target_before_loading_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(signals_probe, "verify_session", lambda _: None)
    subject = str(uuid4())
    with pytest.raises(ValueError, match="only mapped identity_provider"):
        signals_probe.exercise(
            inputs(tmp_path),
            {
                "issuer_id": "local-test-source",
                "subject_id": subject,
                "workload_subjects": {subject: "spiffe://care-link.demo/lab/identity"},
            },
        )


def test_pod_oracle_keeps_credentials_inside_and_selects_only_requested_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, event_id = str(uuid4()), str(uuid4())
    seen = []

    def kubectl(_inputs: LabInputs, *args: str, stdin: str | None = None) -> str:
        seen.append((args, stdin))
        compile(args[-1], "pod-oracle", "exec")
        assert args[:10] == (
            "-n",
            "care-link-imp02-002",
            "exec",
            "-i",
            "deployment/identity",
            "-c",
            "application",
            "--",
            "python",
            "-c",
        )
        assert "/config/identity.json" in args[-1]
        assert "READ ONLY" in args[-1] and '"verify-full"' in args[-1]
        assert "WHERE kind=%s AND record_key=%s" in args[-1]
        assert json.loads(stdin) == {
            "expected_database": "identity_test",
            "issuer": "local-source",
            "event": {"jti": event_id, "subject_id": subject},
        }
        return '{"signal":null,"operation":null}'

    monkeypatch.setattr(signals_probe, "kubectl", kubectl)
    result = signals_probe.oracle_via_identity_pod(
        inputs(tmp_path),
        "identity_test",
        "local-source",
        {"jti": event_id, "subject_id": subject, "unused_private_field": "never-export"},
    )
    assert result == {"signal": None, "operation": None}
    assert "never-export" not in str(seen)


def test_pod_transport_requires_no_external_dsn_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(signals_probe, "verify_session", lambda _: None)
    key_file = tmp_path / "test-key.pem"
    key_file.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
    )
    key_file.chmod(0o600)
    subject = str(uuid4())

    def observed(*_args: object) -> dict[str, object]:
        raise ValueError("pod observer selected before any signal send")

    monkeypatch.setattr(signals_probe, "oracle_via_identity_pod", observed)
    with pytest.raises(ValueError, match="pod observer selected"):
        signals_probe.exercise(
            inputs(tmp_path),
            {
                "issuer_id": "local-source",
                "subject_id": subject,
                "workload_subjects": {subject: signals_probe.PEER},
                "signing_key_file": str(key_file),
                "expected_database": "identity_test",
                "verification_transport": "identity_pod",
            },
        )
