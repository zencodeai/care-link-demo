"""Fixed session resource names and immutable acquisition inputs."""

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SESSION = "imp02-002"
CLUSTER = "care-link-" + SESSION
NAMESPACE = CLUSTER
LABELS = {"care-link.session": SESSION}
IMAGE = re.compile(r"[a-z0-9./_-]+(?::[a-zA-Z0-9._-]+)?@sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class LabInputs:
    images: dict[str, str]
    kind_binary: Path
    calico_manifest: Path
    state_dir: Path
    kind_sha256: str
    calico_sha256: str

    def image(self, name: str) -> str:
        value = self.images[name]
        if IMAGE.fullmatch(value) is None:
            raise ValueError("immutable image required: " + name)
        return value


def load_inputs(path: Path) -> LabInputs:
    value = cast(dict[str, object], json.loads(path.read_text()))
    if value.get("session") != SESSION:
        raise ValueError("wrong lab session")
    images = value.get("images")
    if not isinstance(images, dict):
        raise ValueError("pinned lab images required")
    typed: dict[str, str] = {}
    for key, item in cast(dict[str, object], images).items():
        if not isinstance(item, str) or IMAGE.fullmatch(item) is None:
            raise ValueError("invalid immutable lab image")
        typed[key] = item
    paths: list[Path] = []
    for field in ("kind_binary", "calico_manifest", "state_dir"):
        item = value.get(field)
        if not isinstance(item, str):
            raise ValueError("explicit lab path required")
        result = Path(item).resolve()
        if not result.is_relative_to(Path("/private/tmp")) and not result.is_relative_to(
            Path(tempfile.gettempdir()).resolve()
        ):
            raise ValueError("lab acquisitions and state belong only in temporary session storage")
        paths.append(result)
    digests: list[str] = []
    for field in ("kind_sha256", "calico_sha256"):
        item = value.get(field)
        if not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None:
            raise ValueError("verified acquisition digest required")
        digests.append(item)
    return LabInputs(typed, paths[0], paths[1], paths[2], *digests)


def document(kind: str, name: str, *, api: str = "v1", **fields: object) -> dict[str, object]:
    return {
        "apiVersion": api,
        "kind": kind,
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": LABELS},
        **fields,
    }


def pod_security(uid: int = 65532) -> dict[str, object]:
    return {
        "runAsUser": uid,
        "runAsGroup": uid,
        "runAsNonRoot": True,
        "seccompProfile": {"type": "RuntimeDefault"},
    }


def container_security() -> dict[str, object]:
    return {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
