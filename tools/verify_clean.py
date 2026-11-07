"""Verify clean, offline locked setup and negative guards in a disposable source copy."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    git = shutil.which("git")
    uv = shutil.which("uv")
    pnpm = shutil.which("pnpm")
    if not git or not uv or not pnpm:
        raise SystemExit("git, uv and pinned pnpm must already be on PATH")
    result = subprocess.run(  # noqa: S603
        [git, "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    environment = {**os.environ, "CI": "true", "UV_PYTHON_DOWNLOADS": "never"}
    with tempfile.TemporaryDirectory(prefix="care-link-clean-") as directory:
        target = Path(directory)
        for filename in result.stdout.decode().split("\0"):
            if not filename:
                continue
            destination = target / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / filename, destination)

        def run(command: list[str], *, succeeds: bool = True) -> None:
            print("+ " + " ".join(command), flush=True)
            check = subprocess.run(command, cwd=target, env=environment, check=False)  # noqa: S603
            if (check.returncode == 0) != succeeds:
                raise SystemExit(f"Unexpected exit {check.returncode}")

        run([uv, "sync", "--offline", "--locked", "--all-packages", "--all-groups"])
        command = [pnpm, "install", "--offline", "--frozen-lockfile", "--ignore-scripts"]
        store = os.environ.get("CARE_LINK_PNPM_STORE")
        if store:
            command.extend(["--store-dir", store])
        run(command)
        run([str(target / ".venv/bin/python"), "tools/check.py"])
        manifest = target / "pyproject.toml"
        original = manifest.read_text()
        manifest.write_text(original.replace('"httpx==0.28.1"', '"httpx>=0.28.1"'))
        run([uv, "lock", "--offline", "--check"], succeeds=False)
        manifest.write_text(original)
        package = target / "package.json"
        content = json.loads(package.read_text())
        content["devDependencies"]["prettier"] = "3.6.1"
        package.write_text(json.dumps(content))
        run([pnpm, "install", "--offline", "--frozen-lockfile", "--lockfile-only"], succeeds=False)
        schema = target / "packages/contracts/typescript/src/schema.json"
        content = json.loads(schema.read_text())
        content["$defs"]["SessionCreate"]["additionalProperties"] = True
        schema.write_text(json.dumps(content))
        run(
            [str(target / ".venv/bin/python"), "tools/generate_contracts.py", "--check"],
            succeeds=False,
        )
        print(
            "PASS: clean offline setup/checks; "
            "mismatched Python/pnpm locks and schema loosening rejected."
        )


if __name__ == "__main__":
    main()
