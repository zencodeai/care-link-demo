"""Create/remove only the explicitly named disposable IMP-05 TLS test fixture."""

import argparse
import shutil
import subprocess
from pathlib import Path

from tools.imp03_verification import database as tls_fixture

NAME = "care-link-imp05-001-postgres"
DIRECTORY = Path("/private/tmp/care-link-imp05-001/database")
PORT = 35435
LABEL = "imp05-001-verification"


def run(arguments: list[str]) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, check=True)  # noqa: S603
    return result.stdout.strip()


def start() -> None:
    if run(["docker", "ps", "-a", "--filter", "name=^/" + NAME + "$", "--format", "{{.ID}}"]):
        raise ValueError("Refusing to adopt any existing fixture")
    if DIRECTORY.exists() or DIRECTORY.is_symlink():
        raise ValueError(
            "Refusing existing credential directory; remove only the previous owned fixture"
        )
    # Reuse the established certificate generator with independent explicit custody.
    tls_fixture.DIRECTORY, tls_fixture.PORT = DIRECTORY, PORT
    tls_fixture.prepare()
    script = (
        "cp /fixture/server.key /tmp/server.key && cp /fixture/server.crt /tmp/server.crt && "
        "chown postgres:postgres /tmp/server.key /tmp/server.crt && chmod 600 /tmp/server.key && "
        "exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt "
        "-c ssl_key_file=/tmp/server.key -c ssl_min_protocol_version=TLSv1.3 "
        "-c ssl_max_protocol_version=TLSv1.3"
    )
    run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            NAME,
            "--label",
            "care-link.scope=" + LABEL,
            "--publish",
            f"127.0.0.1:{PORT}:5432",
            "--tmpfs",
            "/var/lib/postgresql:rw,noexec,nosuid",
            "--mount",
            f"type=bind,src={DIRECTORY},dst=/fixture,readonly",
            "--env-file",
            str(DIRECTORY / "postgres.env"),
            "--entrypoint",
            "sh",
            tls_fixture.IMAGE,
            "-c",
            script,
        ]
    )
    print("Started owned IMP-05 disposable TLS PostgreSQL on loopback35435")


def stop() -> None:
    label = run(
        ["docker", "inspect", "--format", '{{index .Config.Labels "care-link.scope"}}', NAME]
    )
    if label != LABEL:
        raise ValueError("Refusing cleanup of an unowned container")
    run(["docker", "rm", "--force", NAME])
    if DIRECTORY.is_symlink():
        raise ValueError("Refusing symlink credential cleanup")
    shutil.rmtree(DIRECTORY)
    print("Removed owned fixture and its temporary credentials")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    {"start": start, "stop": stop}[parser.parse_args().action]()


if __name__ == "__main__":
    main()
