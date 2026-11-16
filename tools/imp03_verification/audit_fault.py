"""Reversible audit-append barrier for the exact separately bootstrapped IMP-03 DB."""

import argparse
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp03_runtime.config import Record, load, text

FUNCTION = (
    "audit.append_event(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb)"
)
DATABASE = "imp03_runtime_002"
LOGIN = "imp03_data_runtime_002"


def apply(root: Path, admin: Record, *, pause: bool) -> None:
    receipt = load(root / "receipt.json")
    runtime = load(root / "data/config.json", owned=False)
    if receipt.get("session") != "imp03-002" or runtime.get("session") != "imp03-002":
        raise ValueError("Wrong runtime lease")
    settings = conninfo_to_dict(text(admin, "data_admin_dsn"))
    serving = conninfo_to_dict(text(runtime, "store_dsn"))
    if (
        serving.get("dbname") != DATABASE
        or serving.get("user") != LOGIN
        or settings.get("sslmode") != "verify-full"
        or not settings.get("sslrootcert")
        or any(
            settings.get(k) != serving.get(k) for k in ("host", "hostaddr", "port", "sslrootcert")
        )
    ):
        raise ValueError("Exact independent admin/runtime TLS endpoint required")
    target = make_conninfo(
        **{key: str(value) for key, value in {**settings, "dbname": DATABASE}.items()}
    )
    with psycopg.connect(target, connect_timeout=1) as connection:
        guard = connection.execute(
            "SELECT journal_id FROM control.guard WHERE key='demo'"
        ).fetchone()
        if guard is None or str(guard[0]) != receipt.get("journal_id"):
            raise ValueError("Database journal binding does not match the leased runtime")
        role = connection.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s", (LOGIN,)
        ).fetchone()
        if role != (False, False):
            raise ValueError("Non-owning runtime role required")
        # Constants only: no user-controlled SQL identifier or function selection.
        connection.execute(
            ("REVOKE EXECUTE ON FUNCTION " + FUNCTION + " FROM care_link_data_runtime")
            if pause
            else ("GRANT EXECUTE ON FUNCTION " + FUNCTION + " TO care_link_data_runtime")
        )
        permitted = connection.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (LOGIN, FUNCTION)
        ).fetchone()
        if permitted != (not pause,):
            raise ValueError("Audit barrier did not have the exact requested runtime effect")
    print("Owned IMP-03 audit append barrier " + ("applied." if pause else "restored."))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--admin-config", type=Path, required=True)
    parser.add_argument("--action", choices=("pause", "resume"), required=True)
    args = parser.parse_args()
    apply(args.root, load(args.admin_config), pause=args.action == "pause")


if __name__ == "__main__":
    main()
