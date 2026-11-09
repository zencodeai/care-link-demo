"""Prove local public-placeholder process independence; no private/admitted service claim."""

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def request(port: int, path: str) -> tuple[int, str]:
    # Only child-owned loopback inherited sockets; never a caller-supplied URL.
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def main() -> None:
    processes: list[subprocess.Popen[bytes]] = []
    handles: list[socket.socket] = []

    def start(module: str) -> tuple[subprocess.Popen[bytes], int]:
        handle = socket.socket()
        handles.append(handle)
        handle.bind(("127.0.0.1", 0))
        handle.listen()
        port = handle.getsockname()[1]
        command = [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "uvicorn",
            module,
            "--factory",
            "--fd",
            str(handle.fileno()),
            "--no-access-log",
        ]
        process = subprocess.Popen(  # noqa: S603
            command,
            pass_fds=(handle.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Temporary process startup failed")
            try:
                request(port, "/")
                return process, port
            except (OSError, TimeoutError):
                time.sleep(0.05)
        raise RuntimeError("Temporary process startup timed out")

    try:
        core, core_port = start("care_link_core.app:create_app")
        static, static_port = start("care_link_static.app:create_app")
        if request(core_port, "/dev/health")[0] != 200:
            raise RuntimeError("Core developer health failed")
        before = request(static_port, "/fallback")
        if before[0] != 503 or "Reviewed fallback content is unavailable" not in before[1]:
            raise RuntimeError("Unreviewed fallback must show visible unavailability")
        core.terminate()
        core.wait(timeout=5)
        after = request(static_port, "/fallback")
        if before != after or static.poll() is not None:
            raise RuntimeError("Static process depended on core")
        if request(static_port, "/static/v1/manifest")[0] != 503:
            raise RuntimeError("Unreviewed manifest advertised availability")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "core_health_before": 200,
                    "static_before_after": [before[0], after[0]],
                    "core_process_stopped": True,
                    "static_process_still_alive": True,
                    "scope": "Independent local processes with unreviewed public placeholder; "
                    "not a cluster outage, approved crisis publication or private-help proof",
                    "resources": "Temporary inherited loopback sockets; "
                    "child processes stopped in finally",
                },
                indent=2,
            )
        )
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
