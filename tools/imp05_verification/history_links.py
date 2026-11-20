"""Validate Markdown links while honoring existing digest-bound historical relocations."""

import hashlib
import json
import re
from pathlib import Path


def broken_links(root: Path, repository: Path) -> list[tuple[str, str]]:
    origins: dict[Path, Path] = {}
    relocated: set[Path] = set()
    for path in [*root.rglob("relocations.json"), *root.rglob("historical-reference-map.json")]:
        data = json.loads(path.read_text())
        for item in data.get("entries", []):
            target = repository / item["path"]
            if (
                target.is_file()
                and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]
            ):
                origins[target.resolve()] = (repository / item["original_path"]).resolve()
                relocated.add((repository / item["original_path"]).resolve())
        for item in data.get("aliases", []):
            archive = item["archived_content"]
            target = repository / archive["path"]
            if (
                target.is_file()
                and hashlib.sha256(target.read_bytes()).hexdigest() == archive["sha256"]
            ):
                origins[target.resolve()] = (repository / item["original_path"]).resolve()
                relocated.add((repository / item["original_path"]).resolve())
    failures: list[tuple[str, str]] = []
    for path in root.rglob("*.md"):
        origin = origins.get(path.resolve(), path.resolve())
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith(("#", "tel:", "sms:", "mailto:")):
                continue
            local = target.split("#")[0].strip("<>")
            resolved = (origin.parent / local).resolve()
            if local and not resolved.exists() and resolved not in relocated:
                failures.append((str(path.relative_to(root)), local))
    return failures
