"""Explicit fixed actor realm provisioning on the retained Keycloak server.

No shared server settings or original realm/user credentials are reconciled.
Callers retain the generated private plan before invoking installation.
"""

import json
import secrets
from pathlib import Path
from typing import cast
from uuid import uuid4

from tools.demo.models import Record, record, text

from .continuation import require_profile
from .provider import realm_document
from .review_provider import BASE, REALM, ReviewProviderError
from .review_provider_group import LABELS, ProviderGroup


def plan(base: Record) -> Record:
    """Generate once; preserve the result in durable secret custody before I/O."""
    value = record(json.loads(json.dumps(base)))
    if "slot_providers" in value:
        raise ValueError("Existing actor realm plan must be reused")
    providers: Record = {}
    users = record(value["users"])
    for slot, label in LABELS.items():
        actor = record(json.loads(json.dumps(users[label])))
        realm = REALM if slot == "participant" else REALM + "-" + slot
        if slot != "participant":
            actor["id"] = str(uuid4())
            users[label] = actor
        providers[slot] = {
            "session": "imp03-003",
            "realm": realm,
            "binding": value["binding"] if slot == "participant" else str(uuid4()),
            "main_origin": value["main_origin"],
            "users": {label: actor},
            "client": value["client"]
            if slot == "participant"
            else {
                "id": str(uuid4()),
                "client_id": realm + "-browser",
                "secret": secrets.token_urlsafe(48),
            },
        }
    value["slot_providers"] = providers
    return value


def documents(state: Record) -> dict[str, Record]:
    base = {key: value for key, value in state.items() if key != "slot_providers"}
    template = realm_document(
        base,
        realm=REALM,
        roles={
            "participant": "pid",
            "worker": "worker",
            "worker2": "worker",
            "supervisor": "supervisor",
            "security": "security",
        },
    )
    providers = record(state["slot_providers"])
    result: dict[str, Record] = {}
    for slot, label in LABELS.items():
        if slot == "participant":
            continue
        binding = record(providers[slot])
        realm = text(binding, "realm")
        desired = record(json.loads(json.dumps(template)))
        desired["realm"] = realm
        record(desired["attributes"])["care-link.imp03-binding"] = binding["binding"]
        desired["users"] = [
            item
            for item in cast(list[Record], desired["users"])
            if item["username"] == "imp03-" + label
        ]
        client = cast(list[Record], desired["clients"])[0]
        issued = record(binding["client"])
        client.update(
            id=issued["id"],
            clientId=issued["client_id"],
            name=issued["client_id"],
            secret=issued["secret"],
        )
        for mapper in cast(list[Record], client["protocolMappers"]):
            config = record(mapper["config"])
            for key, value in list(config.items()):
                if value == REALM + "-resource":
                    config[key] = realm + "-resource"
                elif value == REALM + "-browser":
                    config[key] = realm + "-browser"
        result[slot] = desired
    return result


def install(state: Record, admin_password: str, ca_file: Path) -> Record:
    """Create only absent exact realms; existing ones must match saved bindings."""
    require_profile()
    group = ProviderGroup(state, admin_password, ca_file)
    # Existing participant realm is the owned anchor; verify before additions.
    anchor = group.providers["participant"]
    with anchor.client_factory() as client:
        headers, _current = anchor.owned(client)
        for slot, desired in documents(state).items():
            provider = group.providers[slot]
            url = BASE + "/admin/realms/" + provider.realm
            response = client.get(url, headers=headers, timeout=10)
            if response.status_code == 404:
                response = client.post(
                    BASE + "/admin/realms", headers=headers, json=desired, timeout=20
                )
                if response.status_code != 201:
                    raise ReviewProviderError("provider_slot_install_unconfirmed")
            elif response.status_code != 200:
                raise ReviewProviderError("provider_slot_read_unavailable")
            current = provider.read_object(client.get(url, headers=headers, timeout=10))
            for key in (
                "realm",
                "enabled",
                "sslRequired",
                "browserFlow",
                "defaultSignatureAlgorithm",
                "otpPolicyCodeReusable",
            ):
                if current.get(key) != desired[key]:
                    raise ReviewProviderError("provider_slot_profile_changed")
            provider.owned(client)
            actor = next(iter(provider.actors.values()))
            provider.actor_current(client, headers, actor)
    return {"fixed_actor_realms": 4, "added_realms": 3, "shared_server_changed": False}
