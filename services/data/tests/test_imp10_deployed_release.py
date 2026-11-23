"""Exercise the portable qualification ledger and current signed role boots."""

import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from tests.evaluation.qwen_combined_journey import release_artifact
from tools.imp06_runtime.release_custody import ReleaseDenied
from tools.imp06_runtime.release_custody_records import (
    EVALUATORS,
    ReleaseArtifact,
    ReleaseObservation,
)
from tools.imp10_verification.deployed_release import (
    LEDGER,
    OBSERVATION,
    SIGNER,
    TARGET,
    TRUST,
    QualificationOperator,
    load_qualification_bindings,
)


@pytest.fixture
def artifact() -> ReleaseArtifact:
    return release_artifact().model_copy(update={"target": TARGET, "signer": SIGNER})


def acknowledge_all(operator: QualificationOperator) -> dict[str, str]:
    ids = {role: str(uuid4()) for role in EVALUATORS}
    for role, boot_id in ids.items():
        operator.register_boot(role, boot_id)
        operator.acknowledge(role, boot_id, operator.observation, "ready")
    return ids


def test_portable_public_bindings_and_independent_activation(
    tmp_path: Path, artifact: ReleaseArtifact
):
    directory = tmp_path / "qualification"
    operator = QualificationOperator.initialize(directory, artifact, readers_gid=os.getegid())
    with pytest.raises(ReleaseDenied):
        operator.activate()
    private = directory / "operator"
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert {path.name for path in operator.shared.iterdir()} == {LEDGER, OBSERVATION, TRUST}
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in private.glob("*.key"))
    assert len({path.read_bytes() for path in private.glob("*.key")}) == len(EVALUATORS)
    ids = acknowledge_all(QualificationOperator(directory))
    with pytest.raises(ReleaseDenied):
        QualificationOperator.initialize(
            directory / "serving",
            artifact.model_copy(
                update={
                    "target": "serving",
                    "purpose": "serving",
                }
            ),
        )
    operator.activate()

    # A separate Python process reconstructs authority from only the portable
    # public files and its own expected observation path.
    expected = tmp_path / "expected.json"
    expected.write_bytes(artifact.observation.signing_bytes())
    (tmp_path / "operator-detached").mkdir()
    private.rename(tmp_path / "operator-detached" / "keys")
    reader = (
        "import os,sys; from pathlib import Path;"
        "from tools.imp06_runtime.release_custody_records import ReleaseObservation;"
        "from tools.imp10_verification.deployed_release import load_qualification_bindings;"
        "observed=ReleaseObservation.model_validate_json(Path(sys.argv[2]).read_bytes());"
        "bindings=load_qualification_bindings(Path(sys.argv[1]),owner_uid=os.geteuid(),"
        "role='core',boot_id=sys.argv[3],expected_observation=observed);"
        "print(bindings.release('worker_summary').function)"
    )
    output = subprocess.run(  # noqa: S603 - fixed test script and owned fixture paths
        [sys.executable, "-c", reader, str(operator.shared), str(expected), ids["core"]],
        check=True,
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert output.stdout.strip() == "worker_summary"


def test_bridge_boot_renewal_preserves_only_current_qualification(
    tmp_path: Path, artifact: ReleaseArtifact
):
    now = datetime.now(UTC)

    def clock() -> datetime:
        return now

    operator = QualificationOperator.initialize(tmp_path / "qualification", artifact, clock=clock)
    ids = acknowledge_all(operator)
    operator.activate()

    def reader(role: str, boot: str):
        return load_qualification_bindings(
            operator.shared,
            owner_uid=os.geteuid(),
            role=role,
            boot_id=boot,
            expected_observation=artifact.observation,
            clock=clock,
        )

    role = "host-inference-bridge"
    core, old_bridge = reader("core", ids["core"]), reader(role, ids[role])
    assert core.current() and old_bridge.current()

    new_boot = str(uuid4())
    update = operator.register_boot(role, new_boot)
    assert update.previous_boot_id == ids[role]
    assert not core.current() and not old_bridge.current()
    with pytest.raises(ReleaseDenied):
        operator.acknowledge(role, ids[role], artifact.observation, "ready")
    altered = artifact.observation.model_copy(update={"image_digest": "0" * 64})
    with pytest.raises(ReleaseDenied):
        operator.acknowledge(role, new_boot, altered, "ready")

    first = operator.acknowledge(role, new_boot, artifact.observation, "ready")
    replacement = reader(role, new_boot)
    assert core.current() and replacement.current() and not old_bridge.current()
    now += timedelta(minutes=3)
    second = operator.acknowledge(role, new_boot, artifact.observation, "ready")
    assert first.epoch == second.epoch == operator.activation.epoch
    assert second.expires_at > first.expires_at
    now += timedelta(minutes=2)
    # Renewing one role alone cannot preserve expired authority for another.
    assert not core.current() and not replacement.current()


def test_readonly_role_denies_wrong_pins_and_symlink_trust(
    tmp_path: Path, artifact: ReleaseArtifact
):
    operator = QualificationOperator.initialize(tmp_path / "qualification", artifact)
    ids = acknowledge_all(operator)
    operator.activate()

    def reader(observation: ReleaseObservation):
        return load_qualification_bindings(
            operator.shared,
            owner_uid=os.geteuid(),
            role="runtime",
            boot_id=ids["runtime"],
            expected_observation=observation,
        )

    altered = artifact.observation.model_copy(update={"catalog_digest": "0" * 64})
    with pytest.raises(ReleaseDenied, match="independently"):
        reader(altered)
    trust = operator.shared / TRUST
    trust.rename(operator.shared / "moved.json")
    trust.symlink_to("moved.json")
    with pytest.raises(OSError):
        reader(artifact.observation)
