"""Explicit operator profiles; import never selects an arbitrary resource scope."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    name: str
    prefix: str
    private: Path
    subnet: str
    mesh_prefix: str
    browser_port: int
    main_origin: str
    realm: str
    parent_prefix: str


PROFILES = {
    "original": Profile(
        "original",
        "care-link-imp03-003",
        Path("/private/tmp/care-link-imp03-003-shared"),
        "172.29.33.0/24",
        "172.29.33.",
        28443,
        "https://manual.localhost:28443",
        "care-link-imp03",
        "imp03-003-",
    ),
    "continuation-001": Profile(
        "continuation-001",
        "care-link-imp03-003-cont1",
        Path("/private/tmp/care-link-imp03-003-cont1"),
        "172.29.34.0/24",
        "172.29.34.",
        29443,
        "https://qualification.localhost:29443",
        "care-link-imp03-cont1",
        "imp03-003-cont1-",
    ),
}


def selected() -> Profile:
    name = os.environ.get("CARE_LINK_IMP03_PROFILE", "original")
    if name not in PROFILES:
        raise ValueError("Explicit known IMP-03 operator profile required")
    return PROFILES[name]


ACTIVE = selected()
