"""Wrong-target inputs fail before any resource creation or database connection."""

import copy
import json
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp04_deployment.config import (
    ACTORS,
    load,
    validate_binding,
    verify_sources,
    write,
)
from tools.imp04_deployment.prepare import make_binding, provider_state, realm_document


def binding() -> dict[str, object]:
    return make_binding(provider_state(), {"identity": "a" * 40, "data": "b" * 40})


def test_nine_real_mfa_actor_documents_without_role_claim_mapper() -> None:
    state = provider_state()
    document = realm_document(state)
    assert len(document["users"]) == 9
    assert document["browserFlow"] == "care-link-imp04-browser"
    for user in document["users"]:
        assert {x["type"] for x in user["credentials"]} == {"password", "otp"}
    client = document["clients"][0]
    assert client["directAccessGrantsEnabled"] is False
    assert client["implicitFlowEnabled"] is False
    assert not any("role" in mapper["protocolMapper"] for mapper in client["protocolMappers"])
    assert set(ACTORS.values()) >= {"pid", "carer", "professional_participant", "worker"}
    validate_binding(make_binding(state, {"identity": "a" * 40, "data": "b" * 40}))


def test_old_target_database_refused() -> None:
    value = binding()
    data = value["data"]
    dsn = conninfo_to_dict(data["store_dsn"])
    dsn["dbname"] = "imp03_runtime_002"
    data["store_dsn"] = make_conninfo(**dsn)
    with pytest.raises(ValueError, match="IMP-04 database"):
        validate_binding(value)


def test_overlapping_credentials_refused() -> None:
    value = binding()
    identity = conninfo_to_dict(value["identity"]["store_dsn"])
    data = conninfo_to_dict(value["data"]["store_dsn"])
    data["password"] = identity["password"]
    value["data"]["store_dsn"] = make_conninfo(**data)
    with pytest.raises(ValueError, match="Independent role credentials"):
        validate_binding(value)


def test_cross_role_secret_field_refused() -> None:
    value = binding()
    value["data"]["custody_key"] = "/private/accepted.key"
    with pytest.raises(ValueError, match="role-exclusive"):
        validate_binding(value)


def test_changed_mesh_namespace_and_uid_refused() -> None:
    value = binding()
    for key, replacement in [("address", "172.29.34.12"), ("authorization_uid", 22012)]:
        changed = copy.deepcopy(value)
        changed["mesh"]["core"][key] = replacement
        with pytest.raises(ValueError, match="independent mesh"):
            validate_binding(changed)


def test_unlisted_egress_refused() -> None:
    value = binding()
    value["roles"]["identity"]["outbound"] = {"data": {}}
    with pytest.raises(ValueError, match="role-specific egress"):
        validate_binding(value)


def test_shared_or_missing_actor_identity_refused() -> None:
    value = binding()
    value["actors"][1]["account_id"] = value["actors"][0]["account_id"]
    with pytest.raises(ValueError, match="Distinct canonical"):
        validate_binding(value)
    value = binding()
    value["actors"].pop()
    with pytest.raises(ValueError, match="Nine independently"):
        validate_binding(value)


def test_extra_postgresql_startup_options_refused() -> None:
    value = binding()
    dsn = conninfo_to_dict(value["data"]["store_dsn"])
    dsn["options"] = "-c search_path=pg_catalog"
    value["data"]["store_dsn"] = make_conninfo(**dsn)
    with pytest.raises(ValueError, match="IMP-04 database"):
        validate_binding(value)


def test_private_loader_rejects_symlink_duplicate_and_public_mode(tmp_path: Path) -> None:
    file = tmp_path / "private.json"
    write(file, '{"a":1,"a":2}')
    with pytest.raises(ValueError, match="Duplicate"):
        load(file)
    file.unlink()
    write(file, json.dumps({"safe": True}))
    link = tmp_path / "link.json"
    link.symlink_to(file)
    with pytest.raises(ValueError, match="regular configuration"):
        load(link)
    file.chmod(0o644)
    with pytest.raises(ValueError, match="Owner-only"):
        load(file)


def test_write_refuses_overwriting_issued_state(tmp_path: Path) -> None:
    path = tmp_path / "issued.json"
    write(path, "first")
    with pytest.raises(FileExistsError):
        write(path, "second")
    assert path.read_text() == "first"


def test_accepted_policy_and_independent_directory_pins_verify() -> None:
    verify_sources()


def test_changed_provider_endpoints_and_role_claim_inputs_refused() -> None:
    value = binding()
    value["identity"]["oidc"]["token_endpoint"] = "https://id.localhost:20443/token"  # noqa: S105 - public endpoint mutation
    with pytest.raises(ValueError, match="independent provider"):
        validate_binding(value)
    value = binding()
    value["identity"]["oidc"]["role"] = "operator"
    with pytest.raises(ValueError, match="independent provider"):
        validate_binding(value)


def test_reviewed_migration_sequence_and_digest_enforced() -> None:
    from tools.imp04_deployment.provision import MIGRATIONS, migration_bytes

    assert [name for name, _ in MIGRATIONS["data"]] == [
        "001_manual.sql",
        "002_review_recovery.sql",
        "003_plans_consent_directory.sql",
    ]
    for role, items in MIGRATIONS.items():
        for name, expected in items:
            assert migration_bytes(role, name, expected)
    with pytest.raises(ValueError, match="migration digest"):
        migration_bytes("data", "003_plans_consent_directory.sql", "0" * 64)


def test_delegation_admin_refuses_other_target_before_io(tmp_path: Path) -> None:
    from tools.imp04_deployment.provision import admit_delegation

    with pytest.raises(ValueError, match="Exact private new-target"):
        admit_delegation(tmp_path, "not-issued", "not-issued", "not-issued")


def test_transport_certificates_satisfy_native_strict_chain_verification(tmp_path: Path) -> None:
    import shutil
    import subprocess

    from tools.imp04_deployment.prepare import issue_tls

    executable = shutil.which("openssl")
    if executable is None:
        pytest.skip("Native OpenSSL unavailable")
    directory = tmp_path / "tls"
    issue_tls(directory)
    for cert in ("manual", "postgres", "keycloak"):
        result = subprocess.run(  # noqa: S603 - local verifier and test-generated public certs
            [
                executable,
                "verify",
                "-x509_strict",
                "-CAfile",
                str(directory / "ca.crt"),
                str(directory / (cert + ".crt")),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, result.stderr
