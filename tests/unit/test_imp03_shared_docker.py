"""Mocked Docker boundary regressions; no daemon/resource operations run here."""

import json
import subprocess

import pytest

from tools.imp03_shared import docker

NAME = docker.PREFIX + "-core"
ID = "a" * 64
NETWORK_ID = "b" * 64


def metadata(kind, name, *, nonce=None, identifier=ID, owned=True):
    labels = {docker.LABEL_KEY: docker.LABEL_VALUE if owned else "foreign"}
    if nonce is not None:
        labels[docker.NONCE_KEY] = nonce
    value = {"Name": "/" + name if kind == "container" else name, "Id": identifier}
    if kind == "container":
        value["Config"] = {"Labels": labels}
    else:
        value.update(Labels=labels, Driver="bridge" if kind == "network" else "local", Options=None)
    return value


@pytest.fixture
def daemon(monkeypatch):
    calls = []
    stored = {}
    hooks = {}
    monkeypatch.setattr(docker.shutil, "which", lambda _: "/fixture/docker")

    def run(command, **kwargs):
        args = command[1:]
        calls.append((args, kwargs))
        kind, action = args[:2]
        if hook := hooks.get((kind, action)):
            return hook(args, kwargs)
        if action == "ls":
            return subprocess.CompletedProcess(command, 0, "", "")
        if action == "inspect":
            value = stored[(kind, args[2])]
            return subprocess.CompletedProcess(command, 0, json.dumps([value]), "")
        if action == "create":
            name = args[args.index("--name") + 1] if kind == "container" else args[-1]
            nonce = next(x.split("=", 1)[1] for x in args if x.startswith(docker.NONCE_KEY + "="))
            value = metadata(kind, name, nonce=nonce)
            stored[(kind, name)] = stored[(kind, ID)] = value
            return subprocess.CompletedProcess(command, 0, name if kind == "volume" else ID, "")
        return subprocess.CompletedProcess(command, 0, "private-captured-output", "")

    monkeypatch.setattr(docker.subprocess, "run", run)
    return calls, stored, hooks


@pytest.mark.parametrize(
    "name", ["care-link-imp02-002-main", "foreign", docker.PREFIX, NAME + "/x"]
)
def test_wrong_namespace_rejected_before_any_daemon_call(daemon, name):
    calls, _, _ = daemon
    for operation in (docker.create_volume, docker.start, docker.stop, docker.remove_owned):
        with pytest.raises(ValueError, match="namespace"):
            operation(name)
    assert not calls


def test_new_container_has_required_restrictions_and_never_pulls(daemon):
    calls, _, _ = daemon
    assert docker.create_container(NAME, image="qualified:source", args=["--help"], mounts=[]) == ID
    command = next(args for args, _ in calls if args[:2] == ["container", "create"])
    for flag in (
        "--pull=never",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=96",
    ):
        assert flag in command
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "65532:65532"


@pytest.mark.parametrize("operation", [docker.start, docker.stop, docker.remove_owned])
def test_foreign_same_prefix_resource_cannot_be_mutated(daemon, operation):
    calls, stored, _ = daemon
    stored[("container", NAME)] = metadata("container", NAME, owned=False)
    with pytest.raises(ValueError, match="ownership"):
        operation(NAME)
    assert all(args[1] == "inspect" for args, _ in calls)


def test_existing_named_resource_refused_without_create_or_adoption(daemon):
    calls, _, hooks = daemon
    hooks[("volume", "ls")] = lambda args, _: subprocess.CompletedProcess(args, 0, NAME, "")
    with pytest.raises(ValueError, match="Existing"):
        docker.create_volume(NAME)
    assert not any(args[1] == "create" for args, _ in calls)


def test_volume_creation_race_detects_silent_adoption(daemon):
    calls, stored, hooks = daemon

    def raced(args, _):
        stored[("volume", NAME)] = metadata("volume", NAME, nonce="another-operation")
        return subprocess.CompletedProcess(args, 0, NAME, "")

    hooks[("volume", "create")] = raced
    with pytest.raises(ValueError, match="creation binding"):
        docker.create_volume(NAME)
    assert not any(args[1] in {"start", "rm"} for args, _ in calls)


def test_remove_uses_inspected_id_not_a_replaceable_name(daemon):
    calls, stored, _ = daemon
    stored[("container", NAME)] = metadata("container", NAME)
    docker.remove_owned(NAME)
    assert calls[-1][0] == ["container", "rm", "--force", ID]


def test_volume_replacement_during_container_creation_leaves_it_unstarted(daemon):
    calls, stored, hooks = daemon
    volume = NAME + "-config"
    value = metadata("volume", volume)
    value["CreatedAt"] = "original-creation"
    stored[("volume", volume)] = value

    def raced(args, _):
        nonce = next(x.split("=", 1)[1] for x in args if x.startswith(docker.NONCE_KEY + "="))
        stored[("container", ID)] = metadata("container", NAME, nonce=nonce)
        stored[("volume", volume)]["CreatedAt"] = "replacement-creation"
        return subprocess.CompletedProcess(args, 0, ID, "")

    hooks[("container", "create")] = raced
    with pytest.raises(ValueError, match="Volume changed"):
        docker.create_container(
            NAME, image="image", args=[], mounts=[f"type=volume,src={volume},dst=/config,readonly"]
        )
    assert not any(args[1] in {"start", "rm"} for args, _ in calls)


@pytest.mark.parametrize("network", ["host", "bridge", "care-link-imp02-002", "container:old"])
def test_unscoped_network_rejected(daemon, network):
    calls, _, _ = daemon
    with pytest.raises(ValueError):
        docker.create_container(NAME, image="image", args=[], mounts=[], network=network)
    assert not any(args[1] == "create" for args, _ in calls)


def test_kind_attachment_only_new_agent_or_connector_and_uses_ids(daemon):
    calls, stored, _ = daemon
    stored[("network", "kind")] = {"Name": "kind", "Driver": "bridge", "Id": NETWORK_ID}
    for name in (NAME, NAME + "-proxy"):
        with pytest.raises(ValueError, match="fixed-target connectors"):
            docker.create_container(name, image="image", args=[], mounts=[], network="kind")
    connector = NAME + "-connector"
    stored[("container", connector)] = metadata("container", connector)
    docker.connect_network(connector, "kind", ip="172.19.0.23")
    assert calls[-1][0] == ["network", "connect", "--ip", "172.19.0.23", NETWORK_ID, ID]


def test_only_new_ingress_publishes_loopback_and_seed_capabilities_are_explicit(daemon):
    calls, _, _ = daemon
    with pytest.raises(ValueError, match="ingress"):
        docker.create_container(
            NAME, image="image", args=[], mounts=[], publish=["127.0.0.1:28443:28443"]
        )
    docker.create_container(
        NAME + "-ingress", image="image", args=[], mounts=[], publish=["127.0.0.1:28443:28443"]
    )
    command = next(args for args, _ in calls if args[:2] == ["container", "create"])
    assert command[command.index("--publish") + 1] == "127.0.0.1:28443:28443"
    docker.create_container(
        NAME + "-seed",
        image="image",
        args=[],
        mounts=[],
        user="0:0",
        cap_add=["CHOWN", "DAC_OVERRIDE"],
    )
    command = [args for args, _ in calls if args[:2] == ["container", "create"]][-1]
    assert command[command.index("--user") + 1] == "0:0"
    assert command.count("--cap-add") == 2


def test_isolated_gateway_keeps_peer_communication_and_requires_internal(daemon):
    calls, _, _ = daemon
    with pytest.raises(ValueError, match="internal"):
        docker.create_network(NAME, isolated=True)
    assert not calls
    docker.create_network(NAME, subnet="172.30.33.0/24", internal=True, isolated=True)
    command = next(args for args, _ in calls if args[:2] == ["network", "create"])
    assert "--internal" in command
    assert "com.docker.network.bridge.gateway_mode_ipv4=isolated" in command
    assert not any("enable_icc" in value for value in command)


@pytest.mark.parametrize(
    "mount",
    [
        "type=bind,src=/Users/main/private,dst=/config,readonly",
        "type=volume,src=care-link-imp02-002-data,dst=/config",
        "type=volume,src=" + NAME + ",dst=/var/run/docker.sock",
        "type=volume,src=" + NAME + ",dst=/config,volume-driver=local",
        "type=volume,src=" + NAME + ",dst=relative",
        "type=volume,src=" + NAME + ",dst=/config,readonly=false",
    ],
)
def test_unsafe_mounts_never_reach_container_creation(daemon, mount):
    calls, stored, _ = daemon
    stored[("volume", NAME)] = metadata("volume", NAME)
    with pytest.raises(ValueError):
        docker.create_container(NAME, image="image", args=[], mounts=[mount])
    assert not any(args[1] == "create" for args, _ in calls)


def test_owned_named_volume_with_host_bind_options_is_refused(daemon):
    calls, stored, _ = daemon
    value = metadata("volume", NAME)
    value["Options"] = {"type": "none", "o": "bind", "device": "/private"}
    stored[("volume", NAME)] = value
    with pytest.raises(ValueError, match="host/device"):
        docker.create_container(
            NAME, image="image", args=[], mounts=[f"type=volume,src={NAME},dst=/config"]
        )
    assert not any(args[1] == "create" for args, _ in calls)


def test_exec_root_stdin_output_capture_and_errors_are_sanitized(daemon, capsys):
    calls, stored, hooks = daemon
    stored[("container", NAME)] = metadata("container", NAME)
    assert (
        docker.exec(NAME, ["python", "-"], stdin="private-input", root=True)
        == "private-captured-output"
    )
    args, kwargs = calls[-1]
    assert args == ["container", "exec", "--interactive", "--user", "0:0", ID, "python", "-"]
    assert kwargs["input"] == "private-input"
    assert capsys.readouterr().out == ""
    hooks[("container", "exec")] = lambda args, _: subprocess.CompletedProcess(
        args, 1, "private-output", "private-error"
    )
    with pytest.raises(RuntimeError) as error:
        docker.exec(NAME, ["private-argument"])
    assert "private" not in str(error.value)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "capability,name", [("NET_ADMIN", NAME + "-seed"), ("CHOWN", NAME), ("SETUID", NAME + "-seed")]
)
def test_capabilities_are_not_a_general_privilege_escape(daemon, capability, name):
    calls, _, _ = daemon
    with pytest.raises(ValueError, match="capabilities"):
        docker.create_container(name, image="image", args=[], mounts=[], cap_add=[capability])
    assert not any(args[1] == "create" for args, _ in calls)


def test_pid_join_accepts_only_owned_new_agent_identity(daemon):
    calls, stored, _ = daemon
    agent = NAME + "-agent"
    stored[("container", agent)] = metadata("container", agent, identifier=NETWORK_ID)
    docker.create_container(NAME, image="image", args=[], mounts=[], pid_container=agent)
    command = next(args for args, _ in calls if args[:2] == ["container", "create"])
    assert command[command.index("--pid") + 1] == "container:" + NETWORK_ID
    with pytest.raises(ValueError):
        docker.create_container(
            NAME, image="image", args=[], mounts=[], pid_container="care-link-imp02-002-host-agent"
        )


@pytest.mark.parametrize(
    "host",
    [
        {"PidMode": "host"},
        {"NetworkMode": "host"},
        {"Privileged": True},
        {"Binds": ["/private:/private"]},
    ],
)
def test_correct_label_cannot_smuggle_host_namespace_or_bind_access(daemon, host):
    calls, stored, _ = daemon
    agent = NAME + "-agent"
    value = metadata("container", agent)
    value["HostConfig"] = host
    stored[("container", agent)] = value
    with pytest.raises(ValueError, match="Host namespaces"):
        docker.create_container(NAME, image="image", args=[], mounts=[], pid_container=agent)
    assert not any(args[1] == "create" for args, _ in calls)


def test_copy_rejects_symlink_or_socket_destination_before_daemon_operation(daemon, tmp_path):
    calls, _, _ = daemon
    source = tmp_path / "private"
    source.write_text("private-input")
    alias = tmp_path / "alias"
    alias.symlink_to(source)
    for path, destination in [(alias, "/config"), (source, "/var/run/docker.sock")]:
        with pytest.raises(ValueError):
            docker.copy_into(NAME, path, destination)
    assert not calls
