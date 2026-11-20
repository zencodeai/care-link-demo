"""Explicit IMP-04 public web build and pinned qualification image build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import PRIVATE
from .deploy import APP_IMAGE, image_id, private_write

REPOSITORY = Path(__file__).resolve().parents[2]
ORIGINS = {
    "VITE_OIDC_ORIGIN": "https://id.plans.localhost:31443",
    "VITE_HELP_ORIGIN": "https://help.localhost:19443",
    "VITE_STATIC_ORIGIN": "https://static.localhost:21443",
}


def executable(name: str) -> str:
    value = shutil.which(name)
    if value is None:
        raise RuntimeError("Required build executable unavailable")
    return value


def web() -> dict[str, object]:
    subprocess.run(  # noqa: S603 - fixed locked build argv
        [executable("pnpm"), "--filter", "@care-link/web", "build"],
        cwd=REPOSITORY,
        env={**os.environ, **ORIGINS},
        check=True,
        timeout=180,
    )  # noqa: S603,S607
    result: dict[str, object] = {
        "profile": "imp04-plans-002",
        "main_origin": "https://plans.localhost:30443",
        "origins": ORIGINS,
        "scope": "Public build configuration only; no actor credentials or tokens",
    }
    path = REPOSITORY / "apps/web/dist/qualification-origins.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    path.chmod(0o644)
    files = [
        {
            "path": str(p.relative_to(REPOSITORY)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(path.parent.rglob("*"))
        if p.is_file()
    ]
    result["files"] = files
    result["fingerprint"] = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def image() -> dict[str, object]:
    provenance = json.loads((REPOSITORY / "apps/web/dist/qualification-origins.json").read_text())
    if provenance.get("profile") != "imp04-plans-002" or provenance.get("origins") != ORIGINS:
        raise ValueError("Explicit IMP-04 web provenance required")
    log = PRIVATE / "application-build.log"
    fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        subprocess.run(  # noqa: S603 - fixed locked build argv
            [
                executable("docker"),
                "build",
                "--platform",
                "linux/arm64",
                "-f",
                "deploy/images/imp04/Dockerfile",
                "-t",
                APP_IMAGE,
                ".",
            ],
            cwd=REPOSITORY,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=900,
        )  # noqa: S603,S607
    return {
        "image_tag": APP_IMAGE,
        "image_id": image_id(APP_IMAGE),
        "recipe_sha256": hashlib.sha256(
            (REPOSITORY / "deploy/images/imp04/Dockerfile").read_bytes()
        ).hexdigest(),
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "scope": "Qualification workspace distribution, not minimal per-role packaging",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("web", "image"), required=True)
    args = parser.parse_args()
    result = web() if args.action == "web" else image()
    private_write(
        PRIVATE
        / ("web-build-result.json" if args.action == "web" else "application-build-result.json"),
        result,
    )
    print(
        json.dumps(
            result
            if args.action == "image"
            else {key: value for key, value in result.items() if key != "files"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
