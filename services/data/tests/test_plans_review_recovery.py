"""Real SQL tests; use only the explicit disposable PostgreSQL fixture."""

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from care_link_data import ReviewRunAdmin, apply_plans_review_migration
from care_link_domain import ManualError
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


def key():
    return str(uuid4())


def namespace(h, scenario="plans-consent-directory"):
    with psycopg.Connection[dict[str, object]].connect(h.database.admin, row_factory=dict_row) as c:
        apply_plans_review_migration(c)
        # Reapplying an exact pinned additive migration must be harmless.
        apply_plans_review_migration(c)
    admin = ReviewRunAdmin(
        h.database.admin,
        environment_id="plans-test-" + key(),
        expected_database=conninfo_to_dict(h.database.admin)["dbname"],
        expected_journal_id=h.journal.head().journal_id,
    )
    run = key()
    admin.create(run, scenario, key())
    h.participant = replace(
        h.participant,
        review_run_id=run,
        review_slot_id="pid",
        review_origin=f"https://r{run.replace('-', '')}-pid.plans.localhost",
    )
    return admin, run


def save(h, session, words="Fictional saved words"):
    return h.service.review_draft_save(
        h.participant,
        key(),
        {"kind": "plan", "text": words, "expected_revision": "0"},
        session,
    )


def test_plan_words_recover_only_with_exact_run_actor_and_namespace(harness):
    h = harness
    _admin, run = namespace(h)
    sid = str(h.create()["id"])
    saved = save(h, sid)
    result = h.service.review_workspace(h.participant, sid)
    assert result["drafts"] == [saved]
    assert result["drafts"][0]["text"] == "Fictional saved words"
    stored = h.read("SELECT text_ciphertext FROM core.review_draft WHERE id=%s", (saved["id"],))[0][
        0
    ]
    assert stored != "Fictional saved words"
    for actor in [
        replace(h.participant, review_run_id=key()),
        replace(h.participant, review_run_id=None),
    ]:
        with pytest.raises(ManualError):
            h.service.review_workspace(actor, sid)
    assert _admin.inspect_optional(run)["state"] == "active"
    assert _admin.inspect_optional(key()) is None


def test_manual_service_cannot_write_plan_draft(harness):
    h = harness
    namespace(h, "manual-service")
    sid = str(h.create()["id"])
    with pytest.raises(ManualError, match="review_context_required"):
        save(h, sid)
    assert h.read("SELECT count(*) FROM core.review_draft")[0][0] == 0


def test_review_principal_ensure_is_idempotent_and_never_restores_rights(harness):
    h = harness
    admin, run = namespace(h)
    for _retry in range(2):
        admin.ensure_principal(h.participant)
    fresh = replace(h.participant, account_id=key())
    for _retry in range(2):
        admin.ensure_principal(fresh)
    assert h.read(
        "SELECT count(*) FROM control.principal_guard WHERE principal_id=%s", (fresh.account_id,)
    ) == [(1,)]
    for changed in [replace(fresh, identity_revision=2), replace(fresh, role_revision=2)]:
        with pytest.raises(ValueError, match="cannot be replaced"):
            admin.ensure_principal(changed)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.principal_guard SET revoked=true WHERE principal_id=%s",
            (fresh.account_id,),
        )
    with pytest.raises(ValueError, match="cannot be replaced"):
        admin.ensure_principal(fresh)
    assert h.read(
        "SELECT revoked,identity_revision,role_revision FROM control.principal_guard "
        "WHERE principal_id=%s",
        (fresh.account_id,),
    ) == [(True, fresh.identity_revision, fresh.role_revision)]
    admin.close(run, key())
    with pytest.raises(ValueError, match="active owned plans namespace"):
        admin.ensure_principal(h.participant)


def test_cleanup_is_closed_exact_run_idempotent_and_preserves_business_rows(harness):
    h = harness
    first_admin, first = namespace(h)
    first_sid = str(h.create()["id"])
    first_draft = save(h, first_sid)
    with pytest.raises(ValueError, match="closed review run"):
        first_admin.retire_artifacts(first)
    other_admin, other = namespace(h)
    other_sid = str(h.create()["id"])
    other_draft = save(h, other_sid, "Other run's fictional words")
    first_admin.close(first, key())
    assert first_admin.retire_artifacts(first)["drafts_erased"] == 1
    assert first_admin.retire_artifacts(first)["drafts_erased"] == 0
    assert h.read(
        "SELECT text_ciphertext='' FROM core.review_draft WHERE id=%s", (first_draft["id"],)
    ) == [(True,)]
    assert h.read(
        "SELECT text_ciphertext<>'' FROM core.review_draft WHERE id=%s", (other_draft["id"],)
    ) == [(True,)]
    assert other_admin.inspect(other)["state"] == "active"
    assert h.read(
        "SELECT count(*) FROM core.session WHERE id IN (%s,%s)", (first_sid, other_sid)
    ) == [(2,)]
