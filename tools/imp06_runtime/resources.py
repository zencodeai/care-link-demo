"""Load trusted, explicit synthetic knowledge resources; never fetch or admit."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from care_link_knowledge import KnowledgeCatalog

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class KnowledgeResources:
    catalog: KnowledgeCatalog
    regions: Mapping[str, str]


def load_knowledge_resources(directory: Path | None = None) -> KnowledgeResources:
    """Composition-owned input only; no request/model-controlled file paths."""
    directory = directory or ROOT / "config/demo/knowledge"
    if directory.is_symlink():
        raise ValueError("explicit trusted knowledge directory required")
    raw = (directory / "scenario-binding.json").read_bytes()
    if len(raw) > 1024:
        raise ValueError("bounded synthetic scenario binding required")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate scenario binding")
            value[key] = item
        return value

    value: object = json.loads(raw, object_pairs_hook=unique)
    if value != {
        "scenario_jurisdiction": "CA-XX",
        "knowledge_jurisdiction": "CA-ON",
        "population": "synthetic-demo",
    }:
        raise ValueError("exact authored synthetic scenario binding required")
    return KnowledgeResources(
        KnowledgeCatalog.from_path(directory / "catalog.json"),
        MappingProxyType({"CA-XX": "CA-ON"}),
    )


if __name__ == "__main__":
    resources = load_knowledge_resources()
    print(
        json.dumps({"catalog_digest": resources.catalog.digest, "regions": dict(resources.regions)})
    )
