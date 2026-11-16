"""Fixed realm planning and exact actor/provider bindings, without live I/O."""

import base64
from pathlib import Path
from uuid import uuid4

import pytest
from test_demo_review_provider import ProviderFixture

from tools.imp03_shared.review_provider import REALM, ReviewProviderError
from tools.imp03_shared.review_provider_group import LABELS, ProviderGroup
from tools.imp03_shared.review_realms import documents, plan


def issued_state():
    state = ProviderFixture().state
    for index, actor in enumerate(state["users"].values()):
        actor["password"] += str(index)
        actor["totp_secret"] = base64.b32encode(bytes([index + 1]) * 20).decode()
    return state


def test_fixed_slot_realms_have_distinct_issuer_subject_and_client_without_server_changes() -> None:
    base = issued_state()
    state = plan(base)
    group = ProviderGroup(state, "private-admin", Path("/unused-ca"))
    assert len({item.issuer for item in group.providers.values()}) == 4
    assert len(group.accounts) == 4
    assert state["users"]["participant"] == base["users"]["participant"]
    for slot, label in LABELS.items():
        provider = group.providers[slot]
        assert provider.namespace_slot == slot
        assert (
            provider.actors[state["users"][label]["account_id"]]["id"]
            == state["users"][label]["id"]
        )
        if slot != "participant":
            assert state["users"][label]["id"] != base["users"][label]["id"]
            assert state["users"][label]["account_id"] == base["users"][label]["account_id"]
    generated = documents(state)
    assert set(generated) == {"worker1", "worker2", "supervisor"}
    for slot, document in generated.items():
        assert document["realm"] == REALM + "-" + slot
        assert len(document["users"]) == 1
        client = document["clients"][0]
        assert client["directAccessGrantsEnabled"] is False
        assert client["attributes"]["pkce.code.challenge.method"] == "S256"
        assert {m["config"].get("included.custom.audience") for m in client["protocolMappers"]} >= {
            REALM + "-" + slot + "-resource"
        }


def test_slot_provider_denies_cross_slot_origin_and_modified_binding_before_io() -> None:
    state = plan(issued_state())
    group = ProviderGroup(state, "private-admin", Path("/unused-ca"))
    origin = "https://r" + uuid4().hex + "-participant.qualification.localhost:29443"
    with pytest.raises(ReviewProviderError, match="actor_origin_mismatch"):
        group.providers["worker1"].install_origins([origin])
    state["slot_providers"]["worker1"]["realm"] = "care-link-imp02"
    with pytest.raises(ReviewProviderError, match="realm_outside_lease"):
        ProviderGroup(state, "private-admin", Path("/unused-ca"))
