"""Owner-only maintenance review with actual protocol ports, no ambient bypass."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from care_link_identity import IdentityError, OwnerAccessReview
from care_link_identity.crypto import digest
from care_link_identity.domain import stamp
from conftest import signed_in

pytestmark = pytest.mark.unit


def setup_owner(identity):
    service, store, provider, clock, _key = identity
    owner = str(uuid4())
    service.provision("main-owner", owner, ["operator"])
    provider.subject = "main-owner"
    recovery = OwnerAccessReview(service, owner)
    clock.advance(30 * 86400)
    return recovery, owner


def ceremony(recovery):
    binding = "owner-maintenance-binding-" + "x" * 32
    start = recovery.begin(binding)
    state = parse_qs(urlsplit(start["authorization_url"]).query)["state"][0]
    return start, state, binding


def test_overdue_owner_can_review_only_own_access_after_fresh_mfa_and_explicit_confirmation(
    identity,
):
    service, store, _provider, clock, _key = identity
    recovery, owner = setup_owner(identity)
    with pytest.raises(IdentityError):
        signed_in(service, "operator")
    before = {key for key in store.records if key[0] == "session"}
    start, state, binding = ceremony(recovery)
    proof = recovery.complete(state, "fresh-provider-code", binding)
    assert proof.account_id == owner and proof.purpose == "review_own_access"
    with pytest.raises(IdentityError):
        signed_in(service, "operator")
    with pytest.raises(IdentityError):
        service.current(proof.proof_id)
    assert {key for key in store.records if key[0] == "session"} == before
    assert recovery.confirm(proof.proof_id, binding, approve=True)
    assert signed_in(service, "operator")
    account = next(
        row
        for (kind, _), row in store.records.items()
        if kind == "account" and row.get("account_id") == owner
    )
    assert account["access_review_due_at"] == stamp(clock() + timedelta(days=30))
    with pytest.raises(IdentityError):
        recovery.confirm(proof.proof_id, binding, approve=True)


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_subject",
        "missing_mfa",
        "provider_down",
        "blocked",
        "disabled",
        "quarantined",
        "changed_revision",
    ],
)
def test_maintenance_review_rejects_missing_current_owner_authority(identity, failure):
    service, store, provider, _clock, _key = identity
    recovery, owner = setup_owner(identity)
    _start, state, binding = ceremony(recovery)
    if failure == "wrong_subject":
        provider.subject = "provider-subject"
    elif failure == "missing_mfa":
        provider.mfa = False
    elif failure == "provider_down":
        provider.is_active = False
    else:
        with store.transaction() as tx:
            account_key = next(
                key for key, row in tx.items("account") if row.get("account_id") == owner
            )
            row = tx.get("account", account_key)
            if failure == "quarantined":
                tx.put("issuer", service.issuer, {"quarantined": True})
            else:
                if failure == "blocked":
                    row["blocked"] = True
                elif failure == "disabled":
                    row["enabled"] = False
                else:
                    row["revision"] = "2"
                tx.put("account", account_key, row)
    with pytest.raises(IdentityError):
        recovery.complete(state, "code", binding)
    with pytest.raises(IdentityError):
        signed_in(service, "operator")


def test_ordinary_callback_cannot_turn_maintenance_intent_into_browser_session(identity):
    service, _store, provider, _clock, _key = identity
    recovery, _owner = setup_owner(identity)
    _start, state, binding = ceremony(recovery)
    with pytest.raises(IdentityError):
        service.callback(state, "code", binding)
    assert provider.exchanges == 0
    proof = recovery.complete(state, "code", binding)
    assert recovery.confirm(proof.proof_id, binding, approve=False) is False
    with pytest.raises(IdentityError):
        signed_in(service, "operator")


def test_maintenance_confirmation_rechecks_revocation_expiry_and_has_no_caller_target(identity):
    service, store, provider, clock, _key = identity
    recovery, owner = setup_owner(identity)
    _start, state, binding = ceremony(recovery)
    proof = recovery.complete(state, "code", binding)
    provider.is_active = False
    with pytest.raises(IdentityError):
        recovery.confirm(proof.proof_id, binding, approve=True)
    provider.is_active = True
    clock.advance(301)
    with pytest.raises(IdentityError):
        recovery.confirm(proof.proof_id, binding, approve=True)
    assert store.get("intent", digest(state))["review_consumed"] is False


def test_abandoned_completed_owner_review_disposes_encrypted_bearer_at_proof_expiry(identity):
    from test_retention import configured

    _service, store, _provider, clock, _key = identity
    recovery, _owner = setup_owner(identity)
    _start, state, binding = ceremony(recovery)
    proof = recovery.complete(state, "real-port-fixture-code", binding)
    assert store.get("intent", digest(state))["access_token"]
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    retention.expire_credentials()
    assert store.get("intent", digest(state))["access_token"]
    clock.advance(301)
    retention.expire_credentials()
    row = store.get("intent", digest(state))
    assert row["access_token"] == "" and row["verifier"] == "" and row["nonce"] == ""
    with pytest.raises(IdentityError):
        recovery.confirm(proof.proof_id, binding, approve=True)


def test_deprovision_fences_account_bound_maintenance_intent_and_clears_all_secrets(identity):
    from test_retention import configured

    _service, store, _provider, _clock, _key = identity
    recovery, owner = setup_owner(identity)
    _start, state, binding = ceremony(recovery)
    proof = recovery.complete(state, "real-port-fixture-code", binding)
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    # A separately scoped operator fixture executes the negative control; this
    # is not a claim of another independent human or a self-deprovision bypass.
    retention.deprovision(owner, str(uuid4()), "verified-operator-fixture")
    row = store.get("intent", digest(state))
    assert row["state"] == "failed" and row["access_token"] == ""
    assert row["nonce"] == "" and row["verifier"] == ""
    with pytest.raises(IdentityError):
        recovery.confirm(proof.proof_id, binding, approve=True)


@pytest.mark.parametrize("restriction", ["disabled", "blocked", "revision", "issuer_quarantined"])
def test_maintenance_bearer_disposed_on_current_local_restriction_before_expiry(
    identity, restriction
):
    from test_retention import configured

    service, store, _provider, _clock, _key = identity
    recovery, owner = setup_owner(identity)
    _start, state, binding = ceremony(recovery)
    recovery.complete(state, "fresh-provider-code", binding)
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    with store.transaction() as tx:
        key, account = next(
            (key, row) for key, row in tx.items("account") if row["account_id"] == owner
        )
        if restriction == "disabled":
            account["enabled"] = False
        elif restriction == "blocked":
            account["blocked"] = True
        elif restriction == "revision":
            account["revision"] = "2"
        else:
            tx.put("issuer", service.issuer, {"quarantined": True})
        tx.put("account", key, account)
    retention.expire_credentials()
    intent = store.get("intent", digest(state))
    assert intent["access_token"] == "" and intent["state"] == "failed"
