from pathlib import Path

from tools.check_boundaries import check, violations


def test_runtime_data_and_domain_framework_imports_are_denied():
    assert violations("runtime", ["care_link_data.gateway"])
    assert violations("core", ["psycopg"])
    assert violations("domain", ["fastapi"])
    assert violations("core", ["care_link_contracts"]) == []


def test_forbidden_import_in_source_is_found(tmp_path: Path):
    source = tmp_path / "services/runtime/src/care_link_runtime"
    source.mkdir(parents=True)
    (source / "bad.py").write_text("from care_link_data import gateway\n")
    assert check(tmp_path)


def test_private_typescript_path_is_found(tmp_path: Path):
    source = tmp_path / "apps/web/src"
    source.mkdir(parents=True)
    (source / "bad.ts").write_text('import x from "../../../services/data/private";\n')
    assert check(tmp_path)


def test_private_and_namespace_cross_owner_imports_are_denied():
    assert violations("runtime", ["data.gateway"])
    assert violations("runtime", ["care_link_contracts.validation"])
    assert violations("core", ["services.data.gateway"])


def test_relative_python_escape_is_found(tmp_path: Path):
    source = tmp_path / "services/runtime/src/care_link_runtime"
    source.mkdir(parents=True)
    (source / "bad.py").write_text("from ....data import gateway\n")
    assert check(tmp_path)
