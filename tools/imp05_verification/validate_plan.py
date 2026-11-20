"""Run the frozen canonical validator with digest-bound archive link resolution."""

import importlib.util
from pathlib import Path

from .history_links import broken_links


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    path = repository / "doc/IMP/validate_plan.py"
    spec = importlib.util.spec_from_file_location("care_link_frozen_plan_validator", path)
    if spec is None or spec.loader is None:
        raise ValueError("Canonical planning validator unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_check = module.check

    def check(condition: bool, message: str) -> None:
        if message.startswith("broken local links:"):
            failures = broken_links(path.parent, repository)
            original_check(
                not failures, "broken local links after historical resolution: " + str(failures)
            )
        else:
            original_check(condition, message)

    # Keep all canonical plan/schema/DAG/hash checks. Only historical link
    # resolution follows the existing archive README and verified manifests.
    module.__dict__["check"] = check
    module.main()


if __name__ == "__main__":
    main()
