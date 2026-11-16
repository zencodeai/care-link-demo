"""Guarded Docker primitives for the explicitly scoped Option B operator.

Calls capture output without printing it. Container mutations use the inspected
ID, so a same-name replacement cannot redirect a subsequent operation. Resource
creation carries a fresh nonce to detect silent adoption and name races.
"""

import ipaddress
import json
import re
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from uuid import uuid4

PREFIX = "care-link-imp03-003"
LABEL_KEY = "care-link.scope"
LABEL_VALUE = "imp03-003-option-b"
LABEL = LABEL_KEY + "=" + LABEL_VALUE
NONCE_KEY = "care-link.creation"
Record = dict[str, object]
Kind = Literal["container", "network", "volume"]


def _name(name: str) -> str:
    if not re.fullmatch(re.escape(PREFIX) + r"-[a-z0-9][a-z0-9_.-]{0,100}", name):
        raise ValueError("Exact IMP-03 resource namespace required")
    return name


def _record(value: object) -> Record:
    if not isinstance(value, dict):
        raise RuntimeError("Invalid Docker metadata object")
    return cast(Record, value)


def _id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError("Invalid Docker resource identity")
    return value


def _run(args: list[str], *, stdin: str | None = None) -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker executable unavailable")
    try:
        result = subprocess.run(  # noqa: S603 - list argv, fixed executable, scoped callers
            [executable, *args],
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RuntimeError("IMP-03 Docker operation failed: " + args[0]) from None
    if result.returncode:
        # Never echo argv, stdout or stderr: exec/copy may concern private input.
        raise RuntimeError(
            "IMP-03 Docker operation failed: " + args[0] + " (exit " + str(result.returncode) + ")"
        )
    return result.stdout


def _inspect(kind: Kind, reference: str) -> Record:
    try:
        value: object = json.loads(_run([kind, "inspect", reference]))
    except json.JSONDecodeError:
        raise RuntimeError("Invalid Docker inspection response") from None
    if not isinstance(value, list):
        raise RuntimeError("One exact Docker inspection result required")
    items = cast(list[object], value)
    if len(items) != 1:
        raise RuntimeError("One exact Docker inspection result required")
    return _record(items[0])


def _owned(kind: Kind, name: str) -> Record:
    _name(name)
    value = _inspect(kind, name)
    expected = "/" + name if kind == "container" else name
    labels = (
        _record(_record(value["Config"]).get("Labels"))
        if kind == "container"
        else _record(value.get("Labels"))
    )
    if value.get("Name") != expected or labels.get(LABEL_KEY) != LABEL_VALUE:
        raise ValueError("Docker resource is outside the exact IMP-03 ownership binding")
    if kind == "container":
        host = _record(value.get("HostConfig", {}))
        if (
            host.get("PidMode") == "host"
            or host.get("NetworkMode") == "host"
            or host.get("Privileged")
            or host.get("Binds")
        ):
            raise ValueError("Host namespaces, privileged mode and host binds are forbidden")
        mounts = value.get("Mounts", [])
        if not isinstance(mounts, list) or any(
            _record(mount).get("Type") == "bind" for mount in cast(list[object], mounts)
        ):
            raise ValueError("Host filesystem binds are forbidden")
    return value


def inspect_container(name: str) -> Record:
    return _owned("container", name)


def _fresh(kind: Kind, name: str) -> str:
    _name(name)
    selector = "name=^" + ("/" if kind == "container" else "") + re.escape(name) + "$"
    listing = [
        kind,
        "ls",
        "--filter",
        selector,
        "--format",
        "{{.Name}}" if kind == "volume" else "{{.ID}}",
    ]
    if kind == "container":
        listing.insert(2, "--all")
    if _run(listing).strip():
        raise ValueError("Existing named Docker resource refused")
    return uuid4().hex


def _created(kind: Kind, name: str, reference: str, nonce: str) -> Record:
    value = _inspect(kind, reference)
    expected = "/" + name if kind == "container" else name
    labels = (
        _record(_record(value["Config"]).get("Labels"))
        if kind == "container"
        else _record(value.get("Labels"))
    )
    if (
        value.get("Name") != expected
        or labels.get(LABEL_KEY) != LABEL_VALUE
        or labels.get(NONCE_KEY) != nonce
    ):
        raise ValueError("New Docker resource creation binding differs; inspect without adoption")
    return value


def create_network(
    name: str, *, subnet: str | None = None, internal: bool = False, isolated: bool = False
) -> str:
    _name(name)
    if isolated and not internal:
        raise ValueError("Isolated bridge gateway requires an internal network")
    args = ["network", "create", "--driver", "bridge", "--label", LABEL]
    if subnet is not None:
        block = ipaddress.ip_network(subnet, strict=True)
        if block.version != 4 or not block.is_private:
            raise ValueError("Explicit private IPv4 subnet required")
        args.extend(["--subnet", str(block)])
    if internal:
        args.append("--internal")
    if isolated:
        args.extend(["--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated"])
    nonce = _fresh("network", name)
    identifier = _id(_run([*args, "--label", NONCE_KEY + "=" + nonce, name]).strip())
    _created("network", name, identifier, nonce)
    return identifier


def create_volume(name: str) -> str:
    nonce = _fresh("volume", name)
    actual = _run(
        ["volume", "create", "--label", LABEL, "--label", NONCE_KEY + "=" + nonce, name]
    ).strip()
    if actual != name:
        raise RuntimeError("Docker volume name differs from requested binding")
    _created("volume", name, name, nonce)
    return name


def _network(name: str) -> str:
    if name == "none":
        return name
    value = _inspect("network", "kind") if name == "kind" else _owned("network", name)
    if value.get("Name") != name or value.get("Driver") != "bridge":
        raise ValueError("Only the existing kind or owned IMP-03 bridge is permitted")
    return _id(value.get("Id"))


def _network_caller(name: str, network: str) -> None:
    if network == "kind" and not name.endswith(("-agent", "-connector")):
        raise ValueError("Only new agents and fixed-target connectors may join kind")


def _absolute(path: str) -> str:
    parsed = PurePosixPath(path)
    if (
        not parsed.is_absolute()
        or ".." in parsed.parts
        or str(parsed) != path
        or any(character in path for character in ("\0", "\n", ","))
        or parsed.name == "docker.sock"
    ):
        raise ValueError("Exact absolute container path without Docker socket required")
    return path


def _volume_mount(raw: str) -> tuple[str, Record]:
    options: dict[str, str] = {}
    aliases = {"src": "source", "dst": "target", "destination": "target", "read-only": "readonly"}
    for part in raw.split(","):
        key, _, value = part.partition("=")
        key = aliases.get(key, key)
        if key in options or key not in {"type", "source", "target", "readonly"}:
            raise ValueError("Only an exact owned volume mount is permitted")
        options[key] = value
    if options.get("type") != "volume" or set(options) - {"readonly"} != {
        "type",
        "source",
        "target",
    }:
        raise ValueError("Only an exact owned volume mount is permitted")
    if "readonly" in options and options["readonly"] not in {"", "true"}:
        raise ValueError("Readonly mount flag must be affirmative")
    volume = _owned("volume", options["source"])
    if volume.get("Driver") != "local" or volume.get("Options"):
        raise ValueError("Default local named volume required; host/device options refused")
    target = _absolute(options["target"])
    normalized = "type=volume,source=" + options["source"] + ",target=" + target
    return normalized + (",readonly" if "readonly" in options else ""), volume


def _numeric(value: str) -> str:
    if not re.fullmatch(r"0|[1-9][0-9]{0,9}", value) or int(value) >= 4294967295:
        raise ValueError("Numeric Linux identity required")
    return value


def create_container(
    name: str,
    *,
    image: str,
    args: list[str],
    mounts: list[str],
    user: str = "65532:65532",
    network: str = "none",
    ip: str | None = None,
    pid_container: str | None = None,
    groups: list[str] | None = None,
    publish: list[str] | None = None,
    tmpfs: list[str] | None = None,
    cap_add: list[str] | None = None,
    entrypoint: str | None = None,
    cpus: str = "1",
    memory: str = "256m",
    pids_limit: int = 96,
    environment: dict[str, str] | None = None,
) -> str:
    _name(name)
    _network_caller(name, network)
    if not image or image.startswith("-") or any(c.isspace() for c in image):
        raise ValueError("Explicit existing image reference required")
    identities = user.split(":")
    if len(identities) != 2:
        raise ValueError("Exact numeric UID:GID required")
    for identity in identities:
        _numeric(identity)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", cpus) or not 0 < float(cpus) <= 14:
        raise ValueError("Bounded positive CPU limit required")
    if not re.fullmatch(r"[1-9][0-9]*(?:[kmg])?", memory):
        raise ValueError("Explicit positive memory limit required")
    maximum_pids = 512 if name.endswith("-browser-ingress") else 96
    if type(pids_limit) is not int or not 16 <= pids_limit <= maximum_pids:
        raise ValueError("Bounded PID limit for the exact container class required")
    command = [
        "container",
        "create",
        "--pull=never",
        "--name",
        name,
        "--label",
        LABEL,
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=" + str(pids_limit),
        "--cpus",
        cpus,
        "--memory",
        memory,
        "--user",
        user,
        "--network",
        _network(network),
    ]
    if ip is not None:
        address = ipaddress.ip_address(ip)
        if network == "none" or address.version != 4 or not address.is_private:
            raise ValueError("Private IPv4 address on a selected bridge required")
        command.extend(["--ip", str(address)])
    if pid_container is not None:
        if not _name(pid_container).endswith("-agent"):
            raise ValueError("PID sharing is restricted to new IMP-03 agent containers")
        command.extend(["--pid", "container:" + _id(inspect_container(pid_container).get("Id"))])
    snapshots: list[Record] = []
    for raw in mounts:
        normalized, snapshot = _volume_mount(raw)
        snapshots.append(snapshot)
        command.extend(["--mount", normalized])
    for group in groups or []:
        command.extend(["--group-add", _numeric(group)])
    for port in publish or []:
        if not name.endswith(("-ingress", "-ingress-relay")):
            raise ValueError("Only the new ingress connector may publish loopback TCP")
        match = re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5}):([0-9]{1,5})(?:/tcp)?", port)
        if not match or any(not 1 <= int(value) <= 65535 for value in match.groups()):
            raise ValueError("Only explicit loopback TCP publication is permitted")
        command.extend(["--publish", port])
    for mount in tmpfs or []:
        _absolute(mount.partition(":")[0])
        if any(c in mount for c in ("\0", "\n")):
            raise ValueError("Invalid temporary mount")
        command.extend(["--tmpfs", mount])
    for capability in cap_add or []:
        value = capability.removeprefix("CAP_")
        if value not in {"CHOWN", "DAC_OVERRIDE"} or not name.endswith(("-seed", "-tlsmaint")):
            raise ValueError("Only the exact seed/maintenance ownership capabilities are permitted")
        command.extend(["--cap-add", value])
    if entrypoint is not None:
        if not entrypoint or "\0" in entrypoint:
            raise ValueError("Explicit executable entrypoint required")
        command.extend(["--entrypoint", entrypoint])
    if environment:
        if name != PREFIX + "-cont1-data-app" or environment != {
            "CARE_LINK_IMP03_COMMIT_ACK_FAULT": "cont1"
        }:
            raise ValueError("Only the exact continuation data fault capability is permitted")
        command.extend(["--env", "CARE_LINK_IMP03_COMMIT_ACK_FAULT=cont1"])
    nonce = _fresh("container", name)
    identifier = _id(_run([*command, "--label", NONCE_KEY + "=" + nonce, image, *args]).strip())
    _created("container", name, identifier, nonce)
    # Once the container references each volume Docker prevents ordinary volume
    # deletion. Detect replacement between preflight and create before any start.
    for snapshot in snapshots:
        if _owned("volume", cast(str, snapshot["Name"])) != snapshot:
            raise ValueError("Volume changed during container creation; container left unstarted")
    return identifier


def start(name: str) -> str:
    return _run(["container", "start", _id(inspect_container(name).get("Id"))])


def exec(name: str, args: list[str], *, stdin: str | None = None, root: bool = False) -> str:
    identifier = _id(inspect_container(name).get("Id"))
    command = ["container", "exec"]
    if stdin is not None:
        command.append("--interactive")
    if root:
        command.extend(["--user", "0:0"])
    return _run([*command, identifier, *args], stdin=stdin)


def copy_into(name: str, source: Path, destination: str) -> None:
    target = _absolute(destination)
    if not source.is_absolute() or source.is_symlink():
        raise ValueError("Absolute nonsymlink copy source required")
    paths = [source, *source.rglob("*")] if source.is_dir() else [source]
    if any(not (stat.S_ISDIR(p.lstat().st_mode) or stat.S_ISREG(p.lstat().st_mode)) for p in paths):
        raise ValueError("Only regular files/directories may be copied")
    identifier = _id(inspect_container(name).get("Id"))
    # The daemon archive API cannot see some process-mounted tmpfs paths.
    # Transfer through the seed's own mount namespace, with bounded streaming
    # and exclusive file creation. Nothing is embedded in command arguments.
    if not name.endswith("-seed"):
        raise ValueError("Private input transfer is restricted to the owned seed")
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker executable unavailable")
    if source.is_dir():
        for path in paths:
            if path.is_dir():
                relative = path.relative_to(source)
                directory = _absolute(str(PurePosixPath(target) / relative))
                _run(
                    [
                        "container",
                        "exec",
                        identifier,
                        "python",
                        "-c",
                        "import pathlib,sys;pathlib.Path(sys.argv[1]).mkdir(mode=0o700)",
                        directory,
                    ]
                )
    for path in paths:
        if not path.is_file():
            continue
        filename = (
            target if source.is_file() else str(PurePosixPath(target) / path.relative_to(source))
        )
        filename = _absolute(filename)
        script = (
            "import os,shutil,sys;"
            "f=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);"
            "o=os.fdopen(f,'wb');shutil.copyfileobj(sys.stdin.buffer,o,65536);"
            "o.flush();os.fsync(o.fileno());o.close()"
        )
        with path.open("rb") as stream:
            result = subprocess.run(  # noqa: S603 - fixed seed and raw stdin, no shell
                [
                    executable,
                    "container",
                    "exec",
                    "--interactive",
                    identifier,
                    "python",
                    "-c",
                    script,
                    filename,
                ],
                stdin=stream,
                capture_output=True,
                timeout=300,
                check=False,
            )
        if result.returncode:
            raise RuntimeError("Private seed stream transfer failed; partial file retained")


def connect_network(name: str, network: str, ip: str | None = None) -> None:
    _name(name)
    _network_caller(name, network)
    if network == "none":
        raise ValueError("Cannot attach the none network")
    identifier = _id(inspect_container(name).get("Id"))
    target = _network(network)
    command = ["network", "connect"]
    if ip is not None:
        address = ipaddress.ip_address(ip)
        if address.version != 4 or not address.is_private:
            raise ValueError("Explicit private IPv4 address required")
        command.extend(["--ip", str(address)])
    _run([*command, target, identifier])


def stop(name: str) -> None:
    _run(["container", "stop", "--time", "10", _id(inspect_container(name).get("Id"))])


def remove_owned(name: str) -> None:
    _run(["container", "rm", "--force", _id(inspect_container(name).get("Id"))])
