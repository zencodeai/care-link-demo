"""Build the developer core image only with explicitly reviewed immutable image references."""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest_image(value: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("Supply a reviewed repository@sha256:<64 hex> image")
    return value


def main() -> None:
    pins = json.loads((ROOT / "services/core/image-inputs.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-image", type=digest_image, default=pins["python"]["image"])
    parser.add_argument("--uv-image", type=digest_image, default=pins["uv"]["image"])
    parser.add_argument("--tag", default="care-link-core:imp-01")
    parser.add_argument("--iid-file", type=Path)
    args = parser.parse_args()
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("Docker CLI unavailable")
    command = [
        docker,
        "build",
        "--file",
        "services/core/Dockerfile",
        "--tag",
        args.tag,
        "--progress=plain",
        "--build-arg",
        f"PYTHON_IMAGE={args.python_image}",
        "--build-arg",
        f"UV_IMAGE={args.uv_image}",
    ]
    if args.iid_file:
        command.extend(["--iidfile", str(args.iid_file.resolve())])
    command.append(".")
    subprocess.run(  # noqa: S603
        command,
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
