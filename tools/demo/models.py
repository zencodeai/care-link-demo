"""Versioned non-secret environment and scenario bindings."""

import re
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from .errors import DemoError

Record = dict[str, object]
SCHEMA_VERSION = 1
CORE_PROTOCOL = "care.review.v1"
SLOTS = {"participant": "pid", "worker1": "worker", "worker2": "worker", "supervisor": "supervisor"}


def record(value: object) -> Record:
    if not isinstance(value, dict):
        raise DemoError("invalid_object")
    items = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in items):
        raise DemoError("invalid_object")
    return cast(Record, items)


def text(value: Record, key: str, *, limit: int = 512) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not 1 <= len(item) <= limit:
        raise DemoError("invalid_field_" + key)
    return item


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", value):
        raise DemoError("invalid_identifier")
    return value


def uuid(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise DemoError("invalid_uuid")


def https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise DemoError("invalid_origin")
    return value


@dataclass(frozen=True)
class Environment:
    value: Record

    @classmethod
    def parse(cls, raw: object) -> Environment:
        value = record(raw)
        if (
            set(value)
            != {
                "schema_version",
                "environment_id",
                "core_protocol",
                "scenario_version",
                "base_domain",
                "port",
                "actors",
                "ownership",
                "lifecycle",
            }
            or type(value["schema_version"]) is not int
            or value["schema_version"] != SCHEMA_VERSION
        ):
            raise DemoError("environment_schema_incompatible")
        identifier(text(value, "environment_id", limit=96))
        if value["core_protocol"] != CORE_PROTOCOL or value["scenario_version"] != "1":
            raise DemoError("environment_version_incompatible")
        domain = text(value, "base_domain", limit=190)
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or ".." in domain:
            raise DemoError("invalid_base_domain")
        if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
            raise DemoError("invalid_port")
        actors = record(value["actors"])
        if set(actors) != set(SLOTS):
            raise DemoError("exact_actor_slots_required")
        accounts: set[str] = set()
        subjects: set[str] = set()
        for slot, role in SLOTS.items():
            actor = record(actors[slot])
            if set(actor) != {"account_id", "provider_subject", "role", "username", "secret_ref"}:
                raise DemoError("invalid_actor_binding")
            accounts.add(uuid(text(actor, "account_id")))
            subjects.add(text(actor, "provider_subject"))
            text(actor, "username", limit=128)
            identifier(text(actor, "secret_ref", limit=96))
            if actor["role"] != role:
                raise DemoError("actor_role_mismatch")
        if len(accounts) != len(SLOTS) or len(subjects) != len(SLOTS):
            raise DemoError("actors_must_be_distinct")
        ownership = record(value["ownership"])
        kind = ownership.get("kind")
        if kind == "receipt":
            if set(ownership) != {"kind", "resource_id", "receipt_path", "receipt_sha256"}:
                raise DemoError("invalid_ownership_receipt")
            text(ownership, "resource_id")
            text(ownership, "receipt_path")
            if not re.fullmatch(r"[0-9a-f]{64}", text(ownership, "receipt_sha256")):
                raise DemoError("invalid_ownership_digest")
        elif kind == "docker":
            if set(ownership) != {"kind", "resource_id", "labels"}:
                raise DemoError("invalid_ownership_receipt")
            if not re.fullmatch(r"[0-9a-f]{64}", text(ownership, "resource_id")):
                raise DemoError("invalid_docker_identity")
            labels = record(ownership["labels"])
            if not labels or any(not isinstance(v, str) or not v for v in labels.values()):
                raise DemoError("invalid_ownership_labels")
        else:
            raise DemoError("unsupported_ownership")
        lifecycle = record(value["lifecycle"])
        if set(lifecycle) != {"socket", "peer_uid"} or (
            type(lifecycle["peer_uid"]) is not int or lifecycle["peer_uid"] < 0
        ):
            raise DemoError("invalid_lifecycle_binding")
        text(lifecycle, "socket")
        return cls(value)

    @property
    def id(self) -> str:
        return text(self.value, "environment_id")

    def origins(self, run_id: str) -> dict[str, str]:
        # The full UUID avoids collisions even when many retained runs share a host.
        label = UUID(uuid(run_id)).hex
        suffix = ":" + str(self.value["port"]) if self.value["port"] != 443 else ""
        return {
            slot: https_origin(f"https://r{label}-{slot}.{self.value['base_domain']}{suffix}")
            for slot in SLOTS
        }
