"""Bind the source candidate and disposable evidence without collecting credentials."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "doc/IMP/slices/IMP-09-backup-and-recovery/sessions/001-implementation"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def command(arguments: list[str]) -> str:
    return subprocess.run(  # noqa: S603
        arguments, cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opa", type=Path, required=True)
    args = parser.parse_args()
    paths = command(["git", "ls-files", "--cached", "--others", "--exclude-standard"]).splitlines()
    prefixes = (
        "apps/",
        "services/",
        "packages/",
        "config/",
        "deploy/",
        "host/",
        "tools/",
        "tests/",
    )
    manifests = {
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "pnpm-lock.yaml",
        "pyrightconfig.json",
    }
    source = {
        name: digest((ROOT / name).read_bytes())
        for name in paths
        if (name.startswith(prefixes) or name in manifests) and (ROOT / name).is_file()
    }
    references = {
        name: digest((ROOT / name).read_bytes())
        for name in paths
        if name.startswith(("doc/REQ/", "doc/HLD/", "doc/LLD/")) and (ROOT / name).is_file()
    }
    builds = {
        str(path.relative_to(ROOT)): digest(path.read_bytes())
        for base in ("apps/web/dist", "packages/contracts/typescript/dist")
        for path in sorted((ROOT / base).rglob("*"))
        if path.is_file()
    }
    if not builds or not (ROOT / "apps/web/dist/index.html").is_file():
        raise ValueError("Actual web build required before candidate binding")
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "node": command(["node", "--version"]),
        "pnpm": command(["pnpm", "--version"]),
        "postgres_fixture": "owned loopback35439; TLS1.3 verify-full; disposable synthetic",
        "opa": command([str(args.opa.resolve()), "version"]),
        "opa_binary_sha256": digest(args.opa.read_bytes()),
        "postgres_image": (
            "postgres@sha256:80630f83606d8db77d30b3851b16a9f78be2d0d4dda6f7b82a1fdca5ebe3acba"
        ),
        "chromium_image_sha256": "847d0429ebe65559c9cc8cfb415f072fc9bf347050dc0fd7248d5cbcf0669a48",
        "credential_collection": False,
    }
    (SESSION / "environment.json").write_bytes(canonical(environment) + b"\n")
    candidate = {
        "commit": command(["git", "rev-parse", "HEAD"]),
        "diff_digest": digest(canonical(source)),
        "artifact_digest": digest(canonical(builds)),
        "configuration_digest": digest(
            canonical({k: v for k, v in source.items() if k.startswith("config/")})
        ),
        "contract_digest": digest(
            canonical({k: v for k, v in source.items() if k.startswith("packages/contracts/")})
        ),
        "environment_digest": digest((SESSION / "environment.json").read_bytes()),
        "fixture_digest": digest(
            canonical({k: v for k, v in source.items() if k.startswith("tests/") or "/tests/" in k})
        ),
    }
    manifest = {
        "candidate": candidate,
        "binding_encoding": "sha256 of sorted path-to-sha256 map; includes untracked source",
        "source_hashes": source,
        "reference_hashes": references,
        "build_hashes": builds,
        "deployment_applied": False,
        "human_review": "deferred_until_after_IMP10",
        "excluded_preexisting": ["doc/research/2026-11-20-agentic-care/resources/"],
    }
    (SESSION / "candidate-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Bound {len(source)} source files; no private fixture credentials collected.")


if __name__ == "__main__":
    main()
