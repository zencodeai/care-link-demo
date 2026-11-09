"""Accepted Option B behavior; provider/backup custody are explicit fixtures."""

import copy
from datetime import timedelta
from uuid import uuid4

import pytest
from care_link_identity import IdentityError
from care_link_identity.crypto import digest
from care_link_identity.domain import stamp
from care_link_identity.retention import RetentionService
from care_link_identity.retention_ports import BackupClearance, RetentionGrant
from conftest import signed_in

pytestmark = pytest.mark.unit


class Authority:
    """Explicit fresh authority fixture, not provider/owner qualification."""

    def __init__(self, service, store, clock):
        self.operator = str(uuid4())
        self.allowed = True
        self.service, self.store, self.clock = service, store, clock
        self.session_hash = digest("retention-owner-fixture")
        self.on_authorize = lambda: None
        service.provision("retention-owner", self.operator, ["operator"])

    def authorize(self, actor_proof, action, account_id):
        if not self.allowed:
            raise IdentityError("fixture_authority_denied")
        now = self.clock()
        # This fixture models a freshly reauthenticated, reviewed operator. Real
        # SessionRetentionAuthority obtains those facts from the actual provider.
        with self.store.transaction() as tx:
            owner_key = digest(self.service.issuer + "\0retention-owner")
            owner = tx.get("account", owner_key)
            owner["access_review_due_at"] = stamp(now + timedelta(days=30))
            tx.put("account", owner_key, owner)
            tx.put(
                "session",
                self.session_hash,
                {
                    "account_id": self.operator,
                    "role": "operator",
                    "mfa": True,
                    "auth_time": stamp(now),
                    "expires_at": stamp(now + timedelta(hours=1)),
                    "revoked": False,
                    "revision": "1",
                    "role_revision": "1",
                },
            )
        grant = RetentionGrant(
            self.operator,
            self.service.issuer,
            "1",
            "1",
            self.session_hash,
            action,
            account_id,
            now,
            now + timedelta(seconds=1),
        )
        self.on_authorize()
        return grant


class Cleanup:
    def __init__(self):
        self.available = True
        self.disabled = []
        self.deleted = []

    def disable(self, subject, command_id):
        if not self.available:
            return False
        self.disabled.append((subject, command_id))
        return True

    def delete_profile(self, subject, command_id):
        if not self.available:
            return False
        self.deleted.append((subject, command_id))
        return True


class Backups:
    def __init__(self, clock):
        self.clock = clock
        self.copies = 1
        self.accounted = True
        self.immutable = True

    def clearance(self, account_id):
        return BackupClearance(
            account_id, self.accounted, self.copies, self.clock(), self.immutable
        )


def configured(identity):
    service, store, _provider, clock, _key = identity
    authority, cleanup = Authority(service, store, clock), Cleanup()
    backups = Backups(clock)
    retention = RetentionService(store, service.custody, authority, cleanup, backups, clock)
    account = next(record for (kind, _), record in store.records.items() if kind == "account")
    return retention, authority, cleanup, backups, account["account_id"]


def test_deprovision_fences_access_and_clears_credentials_before_provider_recovery(identity):
    service, store, _provider, clock, _key = identity
    raw = signed_in(service)
    proof = service.issue_help_proof(raw, service.origin)
    retention, _authority, cleanup, _backups, account = configured(identity)
    cleanup.available = False
    command = str(uuid4())
    result = retention.deprovision(account, command, "verified-operator")
    assert result["state"] == "pending" and result["local_access"] == "fenced"
    assert store.get("session", digest(raw))["access_token"] == ""
    assert store.get("proof", proof) is None
    with pytest.raises(IdentityError):
        service.current(raw)
    marker = store.get("account_marker", account)
    assert marker["blocked"] is True and marker["owner"] == "main"
    due = marker["profile_purge_due_at"]
    clock.advance(3600)
    cleanup.available = True
    assert retention.reconcile(command, "verified-operator")["provider_state"] == "confirmed"
    assert (
        retention.deprovision(account, command, "verified-operator")["provider_state"]
        == "confirmed"
    )
    assert store.get("account_marker", account)["profile_purge_due_at"] == due


def test_profile_thirty_day_cleanup_and_backup_pending_not_false_erasure(identity):
    service, store, _provider, clock, _key = identity
    retention, _authority, cleanup, backups, account = configured(identity)
    retention.deprovision(account, str(uuid4()), "operator")
    clock.advance(29 * 86400)
    assert retention.purge_due(account, "operator")["state"] == "not_due"
    clock.advance(86400)
    result = retention.purge_due(account, "operator")
    assert result["state"] == "active_profile_removed_backup_pending"
    active = next(record for (kind, _), record in store.records.items() if kind == "account")
    assert "subject" not in active and active["enabled"] is False
    assert cleanup.deleted and store.get("account_marker", account)["profile_removed"] is True
    backups.copies = 0
    assert (
        retention.reconcile("profile:" + account, "operator")["state"]
        == "active_profile_removed_known_copies_accounted"
    )
    with pytest.raises(IdentityError):
        service.provision("provider-subject", account, ["pid"])


def test_missing_external_cleanup_stays_pending_with_scoped_exception(identity):
    _service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    retention.cleanup = None
    retention.deprovision(account, str(uuid4()), "operator")
    clock.advance(30 * 86400)
    result = retention.purge_due(account, "operator")
    assert result["provider_state"] == "pending" and result["reason"] == "provider_cleanup_pending"
    assert result["owner"] == "main" and "review_date" in result
    assert "subject_ciphertext" not in result
    operation = store.get("retention_operation", "profile:" + account)
    assert operation["subject_ciphertext"] and "provider-subject" not in str(operation)


def test_overdue_review_denies_new_access_and_authorized_review_preserves_thirty_day_anchor(
    identity,
):
    service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    clock.advance(30 * 86400)
    with pytest.raises(IdentityError):
        signed_in(service)
    retention.review_access(account, "operator", "1")
    assert signed_in(service)
    record = next(record for (kind, _), record in store.records.items() if kind == "account")
    assert record["access_review_due_at"] == stamp(clock() + timedelta(days=30))
    retention.deprovision(account, str(uuid4()), "operator")
    with pytest.raises(IdentityError):
        retention.review_access(account, "operator", "2")


def test_hold_requires_owner_reason_review_and_overdue_never_silently_releases(identity):
    _service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    retention.deprovision(account, str(uuid4()), "operator")
    with pytest.raises(IdentityError):
        retention.add_hold(account, "", clock() + timedelta(days=1), "operator")
    hold = retention.add_hold(
        account, "recovery_obligation", clock() + timedelta(days=2), "operator"
    )
    clock.advance(30 * 86400)
    assert retention.purge_due(account, "operator") == {
        "state": "held",
        "owner": "main",
        "review_overdue": True,
    }
    assert not store.get("retention_hold", hold)["released"]
    retention.release_hold(hold, "operator")
    assert (
        retention.purge_due(account, "operator")["state"] == "active_profile_removed_backup_pending"
    )


def test_security_audit_and_reviewer_dependency_anchors_are_distinct(identity):
    _service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    security = retention.register_record(
        account, "security_log", {"action": "login_denied"}, clock(), "operator"
    )
    audit = retention.register_record(
        account, "minimal_audit", {"action": "account_provisioned"}, clock(), "operator"
    )
    reviewer = retention.register_record(
        account,
        "reviewer_evidence",
        {"action": "reviewed"},
        clock(),
        "operator",
        frozenset({"artifact-a"}),
    )
    with pytest.raises(IdentityError):
        retention.register_record(
            account, "security_log", {"transcript": "private"}, clock(), "operator"
        )
    with pytest.raises(IdentityError):
        retention.register_record(
            account, "security_log", {"action": {"token": "nested"}}, clock(), "operator"
        )
    clock.advance(30 * 86400)
    retention.purge_due(account, "operator")
    assert store.get("retention_record", security)["state"] == "active_removed_backup_pending"
    assert store.get("retention_record", audit)["state"] == "active"
    clock.advance(60 * 86400)
    retention.purge_due(account, "operator")
    assert store.get("retention_record", audit)["state"] == "active_removed_backup_pending"
    assert store.get("retention_record", reviewer)["state"] == "active"
    retention.end_dependency(reviewer, "artifact-a", "operator")
    clock.advance(89 * 86400)
    retention.purge_due(account, "operator")
    assert store.get("retention_record", reviewer)["state"] == "active"
    clock.advance(86400)
    retention.purge_due(account, "operator")
    assert store.get("retention_record", reviewer)["state"] == "active_removed_backup_pending"


def test_absent_authority_changes_nothing(identity):
    _service, store, _provider, _clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    retention.authority = None
    before = copy.deepcopy(store.records)
    with pytest.raises(IdentityError):
        retention.deprovision(account, str(uuid4()), "caller-label-main")
    assert store.records == before


def test_expired_credentials_are_disposed_without_waiting_profile_window(identity):
    service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    raw = signed_in(service)
    intent, state = service.login_start("pid", "browser")
    clock.advance(3601)
    assert retention.expire_credentials() >= 2
    assert store.get("session", digest(raw))["access_token"] == ""
    assert store.get("intent", digest(state))["verifier"] == ""
    assert store.get("intent", digest(state))["nonce"] == ""


def test_privileged_idle_credentials_and_only_their_dependent_material_are_fenced(identity):
    service, store, provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    privileged = signed_in(service, "worker")
    participant = signed_in(service, "pid", "another-browser")
    proof = service.issue_help_proof(privileged, service.origin)
    ceremony = str(uuid4())
    with store.transaction() as tx:
        tx.put("ceremony", ceremony, {"session_hash": digest(privileged), "state": "pending"})
    _intent, state = service.login_start("worker", "browser", ceremony, digest(privileged))
    provider.is_active = False  # maintenance has no provider/network dependency
    checks = provider.active_checks
    clock.advance(900)
    retention.expire_credentials()
    expired = store.get("session", digest(privileged))
    assert expired["access_token"] == "" and expired["revoked"] is True
    assert expired["csrf"]  # local protocol metadata permits reauthentication
    assert store.get("proof", proof) is None
    assert store.get("ceremony", ceremony)["state"] == "expired"
    assert store.get("intent", digest(state))["verifier"] == ""
    assert store.get("session", digest(participant))["access_token"]
    assert store.get("session", digest(participant))["revoked"] is False
    assert provider.active_checks == checks


@pytest.mark.parametrize(
    "restriction",
    [
        "disabled",
        "blocked",
        "revision",
        "role_revision",
        "role_removed",
        "review_expired",
        "issuer_quarantined",
    ],
)
def test_local_account_restriction_disposes_bearer_and_positive_proof(identity, restriction):
    service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account_id = configured(identity)
    raw = signed_in(service)
    proof = service.issue_help_proof(raw, service.origin)
    with store.transaction() as tx:
        key, account = next(
            (key, row) for key, row in tx.items("account") if row["account_id"] == account_id
        )
        if restriction == "disabled":
            account["enabled"] = False
        elif restriction == "blocked":
            account["blocked"] = True
        elif restriction in {"revision", "role_revision"}:
            account[restriction] = "2"
        elif restriction == "role_removed":
            account["roles"] = []
        elif restriction == "review_expired":
            account["access_review_due_at"] = stamp(clock())
        else:
            tx.put("issuer", service.issuer, {"quarantined": True})
        tx.put("account", key, account)
    retention.expire_credentials()
    assert store.get("session", digest(raw))["access_token"] == ""
    assert store.get("session", digest(raw))["revoked"] is True
    assert store.get("proof", proof) is None


def test_unrelated_issuer_quarantine_does_not_dispose_usable_credential(identity):
    service, store, provider, _clock, _key = identity
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    raw = signed_in(service)
    provider.is_active = False
    with store.transaction() as tx:
        tx.put("issuer", "https://unrelated.test", {"quarantined": True})
    retention.expire_credentials()
    assert store.get("session", digest(raw))["access_token"]
    assert store.get("session", digest(raw))["revoked"] is False


def test_restore_preserves_current_negative_rights_purge_holds_and_capture_expiry(identity):
    service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    signed_in(service)
    snapshot = [(kind, key, copy.deepcopy(row)) for (kind, key), row in store.records.items()]
    retention.deprovision(account, str(uuid4()), "operator")
    clock.advance(30 * 86400)
    retention.purge_due(account, "operator")
    hold = retention.add_hold(account, "recovery_marker", clock() + timedelta(days=1), "operator")
    restored = retention.quarantine_restore(snapshot, clock() - timedelta(days=1))
    assert not {kind for kind, _key, _row in restored} & {
        "session",
        "intent",
        "proof",
        "ceremony",
        "operation",
        "retention_operation",
    }
    profile = next(row for kind, _key, row in restored if kind == "account")
    assert profile["enabled"] is False and profile["roles"] == [] and "subject" not in profile
    assert any(kind == "retention_hold" and key == hold for kind, key, _row in restored)
    with pytest.raises(IdentityError):
        retention.quarantine_restore(snapshot, clock() - timedelta(days=7))


@pytest.mark.parametrize("failure", ["revoked", "expired"])
def test_operator_grant_is_rechecked_in_final_local_mutation_transaction(identity, failure):
    _service, store, _provider, clock, _key = identity
    retention, authority, _cleanup, _backups, account = configured(identity)

    def change():
        if failure == "expired":
            clock.advance(2)
        else:
            with store.transaction() as tx:
                session = tx.get("session", authority.session_hash)
                session["revoked"] = True
                tx.put("session", authority.session_hash, session)

    authority.on_authorize = change
    with pytest.raises(IdentityError):
        retention.deprovision(account, str(uuid4()), "operator")
    target = next(
        row
        for (kind, _), row in store.records.items()
        if kind == "account" and row.get("account_id") == account
    )
    assert target["enabled"] is True and "deprovisioned_at" not in target


def test_expired_protocol_metadata_disposal_keeps_current_negative_markers(identity):
    service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, account = configured(identity)
    raw = signed_in(service)
    _intent, state = service.login_start("pid", "browser")
    retention.deprovision(account, str(uuid4()), "operator")
    clock.advance(31 * 86400)
    retention.expire_credentials()
    assert retention.purge_expired_protocol_metadata() >= 2
    assert store.get("session", digest(raw)) is None
    assert store.get("intent", digest(state)) is None
    assert store.get("account_marker", account)["blocked"] is True


@pytest.mark.parametrize("restriction", ["hold", "profile_dependency"])
def test_pending_external_profile_delete_rechecks_new_restrictions_on_every_retry(
    identity, restriction
):
    _service, _store, _provider, clock, _key = identity
    retention, _authority, cleanup, _backups, account = configured(identity)
    retention.deprovision(account, str(uuid4()), "operator")
    clock.advance(30 * 86400)
    cleanup.available = False
    assert retention.purge_due(account, "operator")["provider_state"] == "pending"
    if restriction == "hold":
        reference = retention.add_hold(
            account, "pending_copy_recovery", clock() + timedelta(days=1), "operator"
        )
    else:
        reference = "restorable-copy-needs-linkage"
        retention.profile_dependency(account, reference, "operator")
    cleanup.available = True
    result = retention.reconcile("profile:" + account, "operator")
    assert result["state"] == "held_pending" and cleanup.deleted == []
    if restriction == "hold":
        retention.release_hold(reference, "operator")
    else:
        retention.profile_dependency(account, reference, "operator", remove=True)
    assert retention.reconcile("profile:" + account, "operator")["provider_state"] == "confirmed"
    assert len(cleanup.deleted) == 1


def test_single_owner_cannot_deprovision_itself_and_destroy_cleanup_authority(identity):
    _service, store, _provider, _clock, _key = identity
    retention, authority, _cleanup, _backups, _account = configured(identity)
    with pytest.raises(IdentityError):
        retention.deprovision(authority.operator, str(uuid4()), "operator")
    owner = next(
        row
        for (kind, _), row in store.records.items()
        if kind == "account" and row.get("account_id") == authority.operator
    )
    assert owner["enabled"] is True and owner["roles"] == ["operator"]
    assert store.get("account_marker", authority.operator) is None


def test_signed_source_quarantine_between_grant_and_commit_blocks_destructive_authority(identity):
    service, store, _provider, _clock, _key = identity
    retention, authority, _cleanup, _backups, account = configured(identity)

    def quarantine():
        with store.transaction() as tx:
            tx.put("issuer", service.issuer, {"quarantined": True})

    authority.on_authorize = quarantine
    with pytest.raises(IdentityError):
        retention.deprovision(account, str(uuid4()), "operator")
    target = next(
        row
        for (kind, _), row in store.records.items()
        if kind == "account" and row.get("account_id") == account
    )
    assert target["enabled"] is True and "deprovisioned_at" not in target
