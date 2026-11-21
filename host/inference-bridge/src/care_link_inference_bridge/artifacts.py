"""Read-only artifact pinning for an explicitly selected installed MLX model."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

Fingerprint = tuple[int, int, int, int, int]
_MODEL_FILE_TYPES = {".json", ".jinja", ".model", ".safetensors", ".txt", ".tiktoken"}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _fingerprint(info: os.stat_result) -> Fingerprint:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("ordinary installed artifact files required")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _snapshot(path: Path) -> tuple[str, Fingerprint]:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        before = _fingerprint(os.fstat(source.fileno()))
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        after = _fingerprint(os.fstat(source.fileno()))
    if before != after or after != _fingerprint(path.lstat()):
        raise ValueError("artifact changed while hashing")
    return digest, after


def file_digest(path: Path) -> str:
    return _snapshot(path)[0]


def _model_files(directory: Path) -> set[str]:
    return {
        path.name
        for path in directory.iterdir()
        if not path.name.startswith(".") and path.suffix in _MODEL_FILE_TYPES
    }


@dataclass(frozen=True)
class ArtifactPins:
    directory: Path
    files: tuple[tuple[str, str], ...]
    fingerprints: tuple[tuple[str, Fingerprint], ...]
    artifact_digest: str
    tokenizer_digest: str
    template_digest: str

    def current(self) -> bool:
        try:
            return _model_files(self.directory) == {name for name, _ in self.fingerprints} and all(
                _fingerprint((self.directory / name).lstat()) == fingerprint
                for name, fingerprint in self.fingerprints
            )
        except (OSError, ValueError):
            return False


def pin_artifact(directory: Path) -> ArtifactPins:
    directory = directory.expanduser().resolve(strict=True)
    index_path = directory / "model.safetensors.index.json"
    if not stat.S_ISREG(index_path.lstat().st_mode):
        raise ValueError("ordinary installed artifact files required")
    index = json.loads(index_path.read_text())
    weights = set(index["weight_map"].values())
    if not weights or any(
        not isinstance(name, str) or Path(name).name != name or not name.endswith(".safetensors")
        for name in weights
    ):
        raise ValueError("closed local Safetensors shard index required")
    names = _model_files(directory)
    tokenizer = {
        name
        for name in names
        if name.startswith("tokenizer") or name in {"vocab.json", "merges.txt"}
    }
    if "tokenizer_config.json" not in tokenizer or not tokenizer & {
        "tokenizer.json",
        "tokenizer.model",
    }:
        raise ValueError("installed tokenizer files required")
    required = weights | {"config.json", "chat_template.jinja", index_path.name}
    if not required <= names:
        raise ValueError("installed model files required")
    digests: list[tuple[str, str]] = []
    fingerprints: list[tuple[str, Fingerprint]] = []
    for name in sorted(names):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("ordinary installed artifact files required")
        digest, fingerprint = _snapshot(path)
        digests.append((name, digest))
        fingerprints.append((name, fingerprint))
    pins = ArtifactPins(
        directory,
        tuple(digests),
        tuple(fingerprints),
        hashlib.sha256(canonical(digests)).hexdigest(),
        hashlib.sha256(canonical([item for item in digests if item[0] in tokenizer])).hexdigest(),
        dict(digests)["chat_template.jinja"],
    )
    if not pins.current():
        raise ValueError("installed artifact changed while pinning")
    return pins
