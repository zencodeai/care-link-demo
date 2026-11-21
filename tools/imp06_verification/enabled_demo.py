"""Run the isolated IMP-06 worker-summary demo with live Qwen and a temporary TLS database."""

import argparse
import io
import json
import os
import secrets
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import psycopg
from care_link_inference_bridge.credentials import read_api_token
from psycopg.conninfo import make_conninfo

from tools.imp05_verification import database as fixture

ROOT = Path(__file__).resolve().parents[2]
PORT = 35449


def _tls_ready(dsn: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as connection:
                row = connection.execute(
                    "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
                ).fetchone()
                if row is not None and row[0] is True:
                    return
                raise RuntimeError("temporary TLS database did not negotiate TLS")
        except psycopg.OperationalError:
            time.sleep(0.25)
    raise RuntimeError("temporary TLS database did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact-dir", "model-index", "token-file", "image-receipt", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--run", action="store_true", required=True)
    args = parser.parse_args()
    if any(
        not path.is_absolute()
        for path in (args.artifact_dir, args.model_index, args.token_file, args.image_receipt)
    ):
        parser.error("artifact, model index, credential and image receipt require absolute paths")
    output = cast(Path, args.output).absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        parser.error("a fresh output path in an existing directory is required")
    read_api_token(args.token_file)

    run_id = "imp06-006-enabled-" + secrets.token_hex(4)
    with TemporaryDirectory(prefix="care-link-" + run_id + ".", dir="/private/tmp") as directory:
        fixture.NAME = "care-link-" + run_id + "-postgres"
        fixture.DIRECTORY = Path(directory) / "database"
        fixture.PORT = PORT
        fixture.LABEL = run_id
        try:
            with redirect_stdout(io.StringIO()):
                fixture.start()
            print(f"Started disposable TLS PostgreSQL on 127.0.0.1:{PORT}", flush=True)
            settings = cast(
                dict[str, str], json.loads((fixture.DIRECTORY / "connection.json").read_text())
            )
            if (
                settings["hostaddr"] != "127.0.0.1"
                or int(settings["port"]) != PORT
                or settings["sslmode"] != "verify-full"
            ):
                raise ValueError("exact disposable loopback TLS database required")
            dsn = make_conninfo(**settings)
            _tls_ready(dsn)
            env = {
                **os.environ,
                "CARE_LINK_MANUAL_TEST_DSN": dsn,
                "CARE_LINK_JOURNEY_PROVIDER": "live",
                "CARE_LINK_JOURNEY_MODEL_DIR": str(args.artifact_dir),
                "CARE_LINK_JOURNEY_MODEL_INDEX": str(args.model_index),
                "CARE_LINK_JOURNEY_TOKEN_FILE": str(args.token_file),
                "CARE_LINK_JOURNEY_IMAGE_RECEIPT": str(args.image_receipt),
                "CARE_LINK_JOURNEY_EVIDENCE": str(output),
            }
            result = subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-xq",
                    "--tb=short",
                    "tests/evaluation/qwen_combined_journey.py",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            print((result.stdout + result.stderr).replace(settings["password"], "[redacted]"))
            if result.returncode:
                raise SystemExit(result.returncode)
            if not output.is_file() or json.loads(output.read_text()).get("state") != "passed":
                raise RuntimeError("the live demo did not emit a passing receipt")
        finally:
            if fixture.run(["docker", "ps", "-aq", "--filter", f"label=care-link.scope={run_id}"]):
                fixture.stop()


if __name__ == "__main__":
    main()
