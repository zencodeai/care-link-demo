"""Primary-owned observations of the exact fresh continuation target."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from care_link_domain import JournalState
from care_link_recovery_control import EncryptedCaptures
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from tools.imp03_verification.extended import (
    TargetLease,
    capture_target,
    compare_snapshots,
    restore_target,
    snapshot_target,
)

from . import docker
from .continuation import require_profile
from .deployment import name
from .infrastructure import private_write
from .model import CONFIG, PRIVATE

EVIDENCE = Path(
    "doc/IMP/slices/IMP-03-protected-manual-service/sessions/003-live-qualification/evidence/continuation"
)


def lease() -> TargetLease:
    require_profile()
    receipt = json.loads((PRIVATE / "runtime-receipt.json").read_text())
    metadata = docker.inspect_container(name("postgres-ingress"))
    dsn = json.loads((PRIVATE / "host-admin.json").read_text())["dsn"]
    return TargetLease(
        name("postgres-ingress"),
        str(metadata["Id"]),
        dsn,
        receipt["journal_id"],
        receipt["policy_digest"],
    )


class CurrentJournal:
    def head(self) -> JournalState:
        script = (
            "from pathlib import Path;import json;from dataclasses import asdict;"
            "from tools.imp03_runtime.config import load;"
            "from tools.imp02_application.config import private_key;"
            "from care_link_recovery_control import FileJournal;"
            f"c=load(Path('{CONFIG}/journal/config.json'));"
            "j=FileJournal(Path(c['journal_directory']),private_key(c['signing_key']),"
            "c['signing_key_id'],expected_journal_id=c['journal_id']);"
            "print(json.dumps(asdict(j.head()),default=str))"
        )
        value = json.loads(docker.exec(name("journal-app"), ["python", "-c", script]))
        value["observed_at"] = datetime.fromisoformat(value["observed_at"])
        return JournalState(**value)


def capture_and_quarantine() -> dict[str, object]:
    target = lease()
    before = snapshot_target(target)
    key = os.urandom(32)
    signing = Ed25519PrivateKey.generate()
    private_write(PRIVATE / "capture.encryption.key", key)
    private_write(
        PRIVATE / "capture.signing.key",
        signing.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
    )
    directory = PRIVATE / "captures"
    EncryptedCaptures.provision(directory)
    captures = EncryptedCaptures(directory, key, signing, "cont1-capture-custodian")
    journal = CurrentJournal()
    artifact = str(docker.inspect_container(name("data-app"))["Image"]).removeprefix("sha256:")
    view = capture_target(
        target, captures, journal, Path("services/data/migrations/001_manual.sql"), artifact
    )
    stage = captures.restore_quarantine(
        str(view["id"]), PRIVATE / "quarantine-staging", journal.head()
    )
    imported = restore_target(target, stage, expected_audit_digest=str(view["audit_digest"]))
    after = snapshot_target(target)
    return {
        "capture": view,
        "quarantine_import": imported,
        "source_unchanged": compare_snapshots(before, after),
        "serving_promotion": False,
        "private_dump_and_keys": "owner-only operator custody; excluded from public evidence",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "capture"])
    args = parser.parse_args()
    os.umask(0o077)
    result = snapshot_target(lease()) if args.action == "snapshot" else capture_and_quarantine()
    destination = EVIDENCE / (args.action + ".json")
    private_write(destination, json.dumps(result, indent=2))
    completed = verified_capture(result) if args.action == "capture" else True
    print(json.dumps({"action": args.action, "evidence": str(destination), "completed": completed}))
    if not completed:
        raise SystemExit(1)


def verified_capture(result: dict[str, object]) -> bool:
    imported = result.get("quarantine_import")
    source = result.get("source_unchanged")
    return (
        isinstance(imported, dict)
        and imported.get("state") == "quarantined_unvalidated"
        and imported.get("serving_allowed") is False
        and imported.get("audit_chain_valid") is True
        and isinstance(source, dict)
        and source.get("no_prohibited_observed_effect") is True
        and result.get("serving_promotion") is False
    )


if __name__ == "__main__":
    main()
