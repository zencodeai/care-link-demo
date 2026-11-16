"""Build the qualification UI with explicit reviewed public HTTPS origins."""

import json
import os
import subprocess
from pathlib import Path

from .profiles import ACTIVE

ROOT = Path(__file__).resolve().parents[2]
APPROVED = {
    "VITE_OIDC_ORIGIN": "https://id.localhost:20443",
    "VITE_HELP_ORIGIN": "https://help.localhost:19443",
    "VITE_STATIC_ORIGIN": "https://static.localhost:21443",
}


def build() -> dict[str, object]:
    configured = json.loads((ROOT / "config/demo/imp03/web-origins.json").read_text())
    if configured != APPROVED:
        raise ValueError("Exact reviewed public qualification origins required")
    subprocess.run(  # noqa: S603 - fixed existing locked workspace builder
        ["pnpm", "--filter", "@care-link/web", "build"],  # noqa: S607
        cwd=ROOT,
        env={**os.environ, **APPROVED},
        check=True,
        timeout=180,
    )
    result: dict[str, object] = {
        "profile": ACTIVE.name,
        "main_origin": ACTIVE.main_origin,
        "origins": configured,
        "scope": "Public build configuration only; no actor credentials or tokens",
    }
    target = ROOT / "apps/web/dist/qualification-origins.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    target.chmod(0o644)
    return result


if __name__ == "__main__":
    print(json.dumps(build()))
