"""Behavioral guard tests use captured Docker calls, never the live daemon."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from tools.imp04_deployment import docker
from tools.imp04_deployment.deploy import name, plan, specs

IMAGE = "sha256:" + "a" * 64


def test_render_exact_target_and_no_shared_networks() -> None:
    rendered = plan(IMAGE)
    assert len(rendered["containers"]) == 31
    assert len(rendered["volumes"]) == 48
    for item in rendered["containers"]:
        assert item["name"].startswith("care-link-imp04-002-")
        assert item.get("network", "none") not in {"kind", "host", "bridge"}
        assert all("source=care-link-imp04-002-" in mount for mount in item["mounts"])
        if item["name"].endswith("-app"):
            assert item.get("network", "none") == "none"
            assert "--role" in item["args"]
    data = next(x for x in specs(IMAGE) if x["name"] == name("data-app"))
    assert "environment" not in data
    assert "tools.imp04_deployment.serve" in data["args"]
    browser = next(x for x in specs(IMAGE) if x["name"] == name("review-chrome"))
    assert browser["init_process"] is True
    assert browser["pids_limit"] == 512
    assert browser["memory"] == "1536m"
    assert [x["name"] for x in specs(IMAGE) if x.get("init_process")] == [name("review-chrome")]


@pytest.mark.parametrize(
    "bad",
    [
        "care-link-imp03-003-core-app",
        "care-link-imp03-003-cont1-core-app",
        "care-link-imp02-002-control-plane",
        "care-link-imp04-002-unlisted",
    ],
)
def test_reject_other_or_unlisted_resources_before_docker(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(docker, "_run", lambda *_a, **_k: pytest.fail("Must reject before Docker"))
    with pytest.raises(ValueError):
        docker.inspect_container(bad)


def test_same_name_replacement_rejected_by_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = name("data-app")
    monkeypatch.setattr(
        docker,
        "_inspect",
        lambda *_: {
            "Name": "/" + owned,
            "Id": "a" * 64,
            "Config": {"Labels": {docker.LABEL_KEY: docker.LABEL_VALUE, docker.NONCE_KEY: "nonce"}},
            "HostConfig": {},
            "Mounts": [],
        },
    )
    monkeypatch.setattr(
        docker,
        "_receipts",
        lambda: {"container:" + owned: {"identity": "b" * 64, "nonce": "nonce"}},
    )
    with pytest.raises(ValueError, match="receipt-bound"):
        docker.start(owned)


def test_missing_receipt_is_not_adopted(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = name("data-app")
    monkeypatch.setattr(
        docker,
        "_inspect",
        lambda *_: {
            "Name": "/" + owned,
            "Id": "a" * 64,
            "Config": {"Labels": {docker.LABEL_KEY: docker.LABEL_VALUE, docker.NONCE_KEY: "nonce"}},
        },
    )
    monkeypatch.setattr(docker, "_receipts", lambda: {})
    with pytest.raises(RuntimeError):
        docker.inspect_container(owned)


def test_creation_receipt_is_private_and_duplicate_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "resources.json"
    monkeypatch.setattr(docker, "_receipt_path", lambda: receipt)
    docker._save_receipt("container", name("data-app"), {"Id": "a" * 64}, "nonce")
    assert receipt.stat().st_mode & 0o077 == 0
    assert json.loads(receipt.read_text())["container:" + name("data-app")]["identity"] == "a" * 64
    with pytest.raises(ValueError, match="Existing creation receipt"):
        docker._save_receipt("container", name("data-app"), {"Id": "b" * 64}, "different")


def test_replacement_scope_only_data_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker, "_run", lambda *_a, **_k: pytest.fail("Must reject before Docker"))
    with pytest.raises(ValueError, match="Only exact owned"):
        docker.replace_data_app({"name": name("core-app")})


def test_declines_unapproved_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker, "_network", lambda _: "none")
    with pytest.raises(ValueError, match="exact accepted loopback"):
        docker.create_container(
            name("core-app"), image=IMAGE, args=[], mounts=[], publish=["127.0.0.1:30443:30443"]
        )


def test_declines_host_volume_even_with_valid_target_name() -> None:
    with pytest.raises(ValueError, match="owned volume"):
        docker._volume_mount("type=bind,source=/tmp,target=/config")


def test_all_four_publications_match_accepted_descriptor() -> None:
    configured = {item["name"]: item["publish"] for item in specs(IMAGE) if "publish" in item}
    assert configured == {
        name("ingress"): ["127.0.0.1:30443:30443"],
        name("keycloak"): ["127.0.0.1:31443:8443"],
        name("postgres"): ["127.0.0.1:25436:5432"],
        name("review-chrome"): ["127.0.0.1:30900:29900"],
    }


@pytest.mark.parametrize(
    "resource", [name("data-app"), name("core-app"), "care-link-imp03-003-cont1-pdp-app"]
)
def test_freezer_rejects_any_other_resource_before_inspection(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    monkeypatch.setattr(docker, "inspect_container", lambda _name: pytest.fail("Must reject first"))
    for action in (docker.pause_dependency, docker.resume_dependency):
        with pytest.raises(ValueError, match="Only exact owned"):
            action(resource)


def test_freezer_uses_inspected_id_and_resume_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = name("pdp-app")
    identity = "a" * 64
    paused = False
    commands: list[list[str]] = []

    def inspect(_name: str) -> dict[str, object]:
        assert _name == resource
        return {"Id": identity, "State": {"Running": True, "Paused": paused}}

    def run(args: list[str], **_kwargs: object) -> str:
        nonlocal paused
        assert args[-1] == identity
        commands.append(args)
        paused = args[1] == "pause"
        return identity

    monkeypatch.setattr(docker, "inspect_container", inspect)
    monkeypatch.setattr(docker, "_run", run)
    assert docker.pause_dependency(resource)["paused"] is True
    assert docker.resume_dependency(resource)["paused"] is False
    assert docker.resume_dependency(resource)["paused"] is False
    assert commands == [["container", "pause", identity], ["container", "unpause", identity]]


def test_init_reaping_only_for_review_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker, "_run", lambda *_a, **_k: pytest.fail("Must reject before Docker"))
    with pytest.raises(ValueError, match="Init child reaping"):
        docker.create_container(
            name("core-app"), image=IMAGE, args=[], mounts=[], init_process=True
        )


def replacement_fixture(spec: docker.ContainerSpec) -> dict[str, object]:
    mounts = []
    for raw in spec["mounts"]:
        options = {part.partition("=")[0]: part.partition("=")[2] for part in raw.split(",")}
        mounts.append(
            {
                "Type": "volume",
                "Name": options["source"],
                "Destination": options["target"],
                "RW": "readonly" not in options,
            }
        )
    port_bindings = {}
    for publication in spec.get("publish") or []:
        address, external, internal = publication.split(":")
        port_bindings[internal + "/tcp"] = [{"HostIp": address, "HostPort": external}]
    return {
        "Id": "b" * 64,
        "Config": {
            "User": spec.get("user"),
            "Cmd": spec["args"],
            "Env": [f"{key}={value}" for key, value in (spec.get("environment") or {}).items()],
        },
        "HostConfig": {
            "Memory": int(spec.get("memory", "256m").removesuffix("m")) * 1024**2,
            "NanoCpus": int(float(spec.get("cpus", "1")) * 1_000_000_000),
            "PidsLimit": spec.get("pids_limit", 96),
            "PortBindings": port_bindings,
            "Init": False,
        },
        "Mounts": mounts,
        "NetworkSettings": {"Networks": {spec.get("network", "none"): {}}},
    }


def test_role_replacement_preserves_custody_and_resource_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = next(x for x in specs(IMAGE) if x["name"] == name("pdp-app"))
    before = replacement_fixture(spec)
    monkeypatch.setattr(docker, "inspect_container", lambda _: before)
    monkeypatch.setattr(docker, "_replace_qualification_container", lambda *_a: {"replaced": True})
    assert docker.replace_role_app(spec) == {"replaced": True}
    changed = {**spec, "memory": "512m"}
    with pytest.raises(ValueError, match="exact rendered"):
        docker.replace_role_app(changed)
    before["Mounts"] = []
    with pytest.raises(ValueError, match="mounted volumes"):
        docker.replace_role_app(spec)


def test_browser_replacement_retains_private_capability_and_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = deepcopy(next(x for x in specs(IMAGE) if x["name"] == name("review-chrome")))
    spec["environment"]["CARE_LINK_REVIEW_WS_PATH"] = "a" * 48
    before = replacement_fixture(spec)
    monkeypatch.setattr(docker, "inspect_container", lambda _: before)
    monkeypatch.setattr(docker, "_replace_qualification_container", lambda *_a: {"replaced": True})
    assert docker.replace_review_browser(spec) == {"replaced": True}
    changed = deepcopy(spec)
    changed["environment"]["CARE_LINK_REVIEW_WS_PATH"] = "b" * 48
    with pytest.raises(ValueError, match="exact rendered"):
        docker.replace_review_browser(changed)
    before["HostConfig"]["PortBindings"] = {}
    with pytest.raises(ValueError, match="port publication"):
        docker.replace_review_browser(spec)
