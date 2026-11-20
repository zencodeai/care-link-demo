"""Real identity callbacks/proofs with temporary custody and typed service seams."""

import copy
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_contracts import validate_contract
from care_link_core.manual_channels import ManualChannels
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner
from care_link_identity.crypto import digest
from care_link_identity.domain import IdentityError
from care_link_identity.manual import ManualIdentityAuthority
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.data.tests.test_directory import feed, unit_projection
from tools.imp04_review.adapters import IdentityCustody, InProcessReviewActors, ServiceReviewAdapter
from tools.imp04_review.bootstrap import BootstrapAuthority, BootstrapIdentityFactory
from tools.imp04_review.directory import DirectoryReviewPreflight
from tools.imp04_review.fixtures import ServiceFixtureBuilder
from tools.imp04_review.lifecycle import PlansReviewLifecycle
from tools.imp04_review.storage import read_json


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def get(self, kind, key):
        return copy.deepcopy(self.rows.get((kind, key)))

    def put(self, kind, key, value):
        self.rows[kind, key] = copy.deepcopy(value)

    def delete(self, kind, key):
        self.rows.pop((kind, key), None)

    def items(self, kind):
        return [
            (key, copy.deepcopy(row)) for (table, key), row in self.rows.items() if table == kind
        ]

    @contextmanager
    def transaction(self):
        before = copy.deepcopy(self.rows)
        try:
            yield self
        except BaseException:
            self.rows = before
            raise


class NoProvider:
    """Fails if private preparation ever falls back to a real provider workflow."""

    def authorization_url(self, *_args):
        raise AssertionError("Base provider must never be used")


class Admin:
    def __init__(self):
        self.runs = {}
        self.events = []
        self.unavailable = False
        self.fail_retire = False
        self.principals = {}
        self.ensure_calls = 0

    def create(self, run_id, scenario, _operation_id):
        self.runs.setdefault(run_id, {"state": "active", "scenario": scenario})
        return self.runs[run_id]

    def inspect(self, run_id):
        return self.runs[run_id]

    def inspect_optional(self, run_id):
        if self.unavailable:
            raise RuntimeError("Owned database unavailable")
        return self.runs.get(run_id)

    def close(self, run_id, _operation_id):
        self.events.append("close")
        self.runs[run_id]["state"] = "closed"
        return self.runs[run_id]

    def retire_artifacts(self, _run_id):
        self.events.append("artifacts")
        if self.fail_retire:
            raise RuntimeError("Cleanup incomplete")
        return {}

    def ensure_principal(self, actor):
        run = self.runs.get(actor.review_run_id)
        if run is None or run["state"] != "active" or run["scenario"] != "plans-consent-directory":
            raise ValueError("Exact active plans run required")
        expected = {
            "id": actor.account_id,
            "role": actor.role,
            "identity_revision": actor.identity_revision,
            "role_revision": actor.role_revision,
            "revoked": False,
        }
        old = self.principals.get(actor.account_id)
        if old is not None and old != expected:
            raise ValueError("Existing principal authority cannot be changed or restored")
        self.principals.setdefault(actor.account_id, expected)
        self.ensure_calls += 1


class RecordingService:
    """Command contract and live actor seam; no claim of PostgreSQL qualification."""

    def __init__(self, factory, channels, load_run):
        self.factory, self.channels, self.load_run = factory, channels, load_run
        self.sessions, self.plans, self.calls = {}, {}, []
        now = datetime(2026, 11, 17, tzinfo=UTC)
        self.directory, self.directory_views = {}, {}
        for case in ("current", "stale", "suspended", "unknown"):
            data, manifest = feed(
                now - timedelta(seconds=301) if case == "stale" else now,
                state="api_failure" if case == "unknown" else "normal_operations",
            )
            view = unit_projection(data, manifest, now, suspended=case == "suspended")
            self.directory[case] = view["id"]
            self.directory_views[view["id"]] = view

    def _call(self, actor, key, contract, body):
        assert self.channels.current(
            actor.account_id, actor.browser_session_digest, actor.transport_generation
        )
        validate_contract(contract, body)
        self.calls.append((actor.role, key, contract, copy.deepcopy(body)))

    def session_create(self, actor, key, body):
        self._call(actor, key, "SessionCreate", body)
        session = {"id": str(uuid4()), "subject_id": str(uuid4()), "revision": "1"}
        self.sessions[session["id"]] = session
        return copy.deepcopy(session)

    def session_read(self, _actor, resource):
        return copy.deepcopy(self.sessions[resource])

    def session_assertions(self, actor, key, body, resource):
        self._call(actor, key, "AssertionCreate", body)
        self.sessions[resource]["revision"] = str(int(self.sessions[resource]["revision"]) + 1)
        return {"id": str(uuid4())}

    def plan_create(self, actor, key, body):
        self._call(actor, key, "PlanCreate", body)
        assert actor.role == "pid"
        plan = {"id": str(uuid4()), "revision": "1"}
        self.plans[plan["id"]] = plan
        return copy.deepcopy(plan)

    def plan_field_append(self, actor, key, body, resource):
        self._call(actor, key, "PlanFieldCreate", body)
        self.plans[resource]["revision"] = str(int(self.plans[resource]["revision"]) + 1)
        return {"id": str(uuid4())}

    def plan_read(self, _actor, resource):
        return copy.deepcopy(self.plans[resource])

    def session_human_request(self, actor, key, body, _resource):
        self._call(actor, key, "HumanRequest", body)
        return {"id": str(uuid4()), "revision": "1"}

    def workforce_reserve(self, actor, key, body, _resource):
        self._call(actor, key, "AssignmentCommand", body)
        return {"id": str(uuid4()), "revision": "1"}

    def workforce_accept(self, actor, key, body, _resource):
        self._call(actor, key, "RevisionCommand", body)
        return {"id": str(uuid4()), "revision": "2"}

    def consent_grant(self, actor, key, body):
        self._call(actor, key, "ConsentGrant", body)
        run = self.load_run(actor.review_run_id)
        self.factory(run, run["actors"]["pid"])
        # This invokes real ceremony/current-session validation. It detects both
        # a None proof placeholder and a session-ID/subject-ID resource swap.
        assert BootstrapAuthority(self.factory).current(actor).account_id == actor.account_id
        BootstrapAuthority(self.factory).consent_proof(
            actor,
            body["authority_proof_id"],
            body["subject_id"],
            body["session_id"],
            body["purpose"],
            body["basis"],
        )
        return {"id": str(uuid4())}

    def directory_search(self, actor, _key, body):
        validate_contract("DirectoryQuery", body)
        return {"items": list(self.directory_views.values()), "next_cursor": None}

    def directory_read(self, actor, resource):
        return copy.deepcopy(self.directory_views[resource])


@pytest.fixture
def composition(tmp_path):
    now = datetime(2026, 11, 17, tzinfo=UTC)
    store, channels, admin = MemoryStore(), ManualChannels(), Admin()
    base = IdentityService(
        store,
        NoProvider(),
        Custody(Fernet.generate_key()),
        ReceiptSigner(Ed25519PrivateKey.generate(), "temporary-identity-key"),
        "https://issuer.synthetic.test",
        "https://legacy.localhost",
        lambda: now,
    )
    state = tmp_path / "state"

    def load_run(run_id):
        return read_json(state / "runs" / (run_id + ".json"))

    factory = BootstrapIdentityFactory(base, load_run)
    actors = InProcessReviewActors(factory, channels, admin)
    service = RecordingService(factory, channels, load_run)
    directory = DirectoryReviewPreflight(
        service,
        service_ids=service.directory,
        queries=tuple(
            {"jurisdiction": "CA-XX", "locale": locale, "need": "client_support"}
            for locale in ("en-CA", "fr-CA")
        ),
    )
    fixtures = ServiceFixtureBuilder(service, actors, directory)
    identity = IdentityCustody(store, base.issuer, clock=base.clock)
    retired = []
    adapter = ServiceReviewAdapter(admin, identity, fixtures, retired.append)
    manager = PlansReviewLifecycle(
        state,
        tmp_path / "registry" / "origins.json",
        adapter,
        environment_id="synthetic-plans-test",
        target_id="temporary-test-store",
        port=30443,
        clock=lambda: now,
    )
    return manager, admin, identity, actors, service, factory, store, channels, retired


def test_real_identity_and_authority_build_four_exact_actor_workspaces(composition):
    manager, _admin, _custody, _actors, service, factory, store, channels, _retired = composition
    ready = manager.start_fresh(lifetime_seconds=7200)
    run = manager._current()
    assert ready["state"] == "ready"
    selections = run["selections"]
    assert selections["carer"]["plan_id"] is None
    assert selections["professional"]["plan_id"] is None
    calls = service.calls
    assert {role for role, _key, _contract, _body in calls} == {
        "pid",
        "carer",
        "professional_participant",
        "worker",
    }
    assert len({key for _role, key, _contract, _body in calls}) == len(calls)
    grant = next(body for _role, _key, contract, body in calls if contract == "ConsentGrant")
    assert grant["fields"] == ["plan.strategies"]
    medication = [
        (role, body)
        for role, _key, contract, body in calls
        if contract == "PlanFieldCreate" and body["field"] == "plan.medication_report"
    ]
    assert len(medication) == 1 and medication[0][0] == "pid"
    assert medication[0][1]["source"] is None and medication[0][1]["safety_relevant"] is True
    assert "Fictional self-report" in medication[0][1]["value"]["text"]
    assert "plan.medication_report" not in grant["fields"]
    assert grant["recipient"]["account_id"] == run["actors"]["worker1"]["account_id"]
    assert grant["authority_proof_id"] is not None
    assert run["steps"]["pid:grant"]["payload"]["authority_proof_id"] == grant["authority_proof_id"]
    assert all(row["factors"] == ["simulated_review"] for _key, row in store.items("session"))
    assert all(row["revoked"] is True for _key, row in store.items("session"))
    # Existing preparation providers re-read private state and fence on close.
    old = factory(run, run["actors"]["pid"])
    manager.close()
    with pytest.raises(IdentityError):
        old.provider.check()
    assert all(
        row["revoked"] is True and row["access_token"] == "" for _key, row in store.items("session")
    )
    assert all(
        not channels.current(account, session_hash, connection.generation)
        for (account, session_hash), connection in channels._connections.items()
    )


def test_scoped_retirement_preserves_unrelated_sessions_and_intents(composition):
    manager, _admin, custody, _actors, _service, _factory, store, _channels, _retired = composition
    manager.start_fresh(lifetime_seconds=3600)
    run = manager._current()
    unrelated = {
        "review_run_id": str(uuid4()),
        "revoked": False,
        "access_token": "unrelated-test-token",
    }
    store.put("session", "unrelated", unrelated)
    store.put(
        "intent",
        "other-intent",
        {"session_hash": "unrelated", "state": "pending", "verifier": "test-only"},
    )
    store.put("ceremony", "other-ceremony", {"session_hash": "unrelated", "state": "verified"})
    custody.retire(run)
    assert store.get("session", "unrelated") == unrelated
    assert store.get("intent", "other-intent")["state"] == "pending"
    assert store.get("ceremony", "other-ceremony")["state"] == "verified"


def test_crash_before_namespace_creation_can_close_and_start_again(composition):
    manager, admin, _custody, _actors, _service, _factory, _store, _channels, retired = composition
    prepare = manager.adapter.prepare
    manager.adapter.prepare = lambda *_args: (_ for _ in ()).throw(RuntimeError("Before namespace"))
    with pytest.raises(RuntimeError):
        manager.start_fresh(lifetime_seconds=3600)
    failed = manager._current()["run_id"]
    assert admin.runs == {}
    assert manager.close()["state"] == "closed"
    assert retired == [failed]
    manager.adapter.prepare = prepare
    assert manager.start_fresh(lifetime_seconds=3600)["state"] == "ready"


def test_cleanup_failure_is_retryable_and_blocks_following_run(composition):
    manager, admin, _custody, _actors, _service, _factory, _store, _channels, retired = composition
    manager.start_fresh(lifetime_seconds=3600)
    first = manager._current()["run_id"]
    admin.fail_retire = True
    with pytest.raises(RuntimeError, match="Cleanup"):
        manager.start_fresh(lifetime_seconds=3600)
    assert manager.inspect()["state"] == "closing"
    assert set(admin.runs) == {first}
    assert retired == []
    admin.fail_retire = False
    assert manager.start_fresh(lifetime_seconds=3600)["state"] == "ready"
    assert retired == [first]


def test_unknown_database_result_does_not_mark_close_complete(composition):
    manager, admin, _custody, _actors, _service, _factory, _store, _channels, _retired = composition
    manager.start_fresh(lifetime_seconds=3600)
    admin.unavailable = True
    with pytest.raises(RuntimeError, match="unavailable"):
        manager.close()
    assert manager.inspect()["state"] == "closing"


def test_real_authority_rejects_wrong_subject_even_with_verified_ceremony(composition):
    manager, _admin, _custody, actors, _service, factory, _store, _channels, _retired = composition
    manager.start_fresh(lifetime_seconds=3600)
    run = manager._current()
    correct = str(uuid4())
    with actors.open(
        run, "pid", {"purpose": "plan_edit", "resource_id": correct, "expected_revision": "0"}
    ) as lease:
        authority = ManualIdentityAuthority(factory(run, run["actors"]["pid"]))
        authority.consent_proof(lease.actor, lease.proof_id, correct, str(uuid4()), "plan", "self")
        with pytest.raises(ManualError):
            authority.consent_proof(
                lease.actor, lease.proof_id, str(uuid4()), str(uuid4()), "plan", "self"
            )
    assert digest(lease.actor.credential_ref)


def test_directory_case_failure_prevents_readiness_and_origin_publication(composition):
    manager, _admin, _custody, _actors, service, _factory, _store, _channels, _retired = composition
    service.directory_views[service.directory["unknown"]]["facts"]["availability"] = (
        "available_fixture"
    )
    with pytest.raises(ValueError, match="unknown availability"):
        manager.start_fresh(lifetime_seconds=3600)
    assert manager.inspect()["state"] == "preparing"
    assert not manager.registry_path.exists()


def test_private_fixture_engine_preserves_serving_dependencies(composition):
    from care_link_data.control import ManualService

    from tools.imp04_review.bootstrap import compose_fixture_service

    _manager, _admin, _custody, _actors, _service, factory, _store, channels, _retired = composition
    serving_authority, policy, journal, cipher, store = (object() for _ in range(5))
    base = ManualService(store, serving_authority, policy, journal, cipher, channel=channels)
    private_authority = BootstrapAuthority(factory)
    private = compose_fixture_service(base, private_authority, channels)
    assert private is not base and private.authority is private_authority
    assert base.authority is serving_authority
    for name in ("store", "policy", "journal", "cipher", "channel", "clock", "directory_artifacts"):
        assert getattr(private, name) is getattr(base, name)


def test_principal_custody_repeated_leases_and_adapter_restart_are_idempotent(composition):
    manager, admin, _custody, _actors, _service, factory, _store, channels, _retired = composition
    manager.start_fresh(lifetime_seconds=3600)
    run = manager._current()
    baseline = copy.deepcopy(admin.principals)
    assert len(baseline) == 4
    assert admin.ensure_calls > len(baseline)
    restarted = InProcessReviewActors(factory, channels, admin)
    for _ in range(2):
        with restarted.open(run, "pid") as lease:
            assert lease.actor.account_id == run["actors"]["pid"]["account_id"]
    assert admin.principals == baseline
    restarted.retire(run)


@pytest.mark.parametrize("change", [{"revoked": True}, {"role_revision": 2}, {"role": "operator"}])
def test_principal_custody_never_reactivates_or_overwrites_existing_authority(composition, change):
    manager, admin, _custody, _actors, _service, factory, _store, channels, _retired = composition
    manager.start_fresh(lifetime_seconds=3600)
    run = manager._current()
    account = run["actors"]["pid"]["account_id"]
    admin.principals[account].update(change)
    restricted = copy.deepcopy(admin.principals[account])
    restarted = InProcessReviewActors(factory, channels, admin)
    with pytest.raises(ValueError, match="cannot be changed or restored"):
        with restarted.open(run, "pid"):
            pytest.fail("Restricted principal must never obtain a fixture lease")
    assert admin.principals[account] == restricted
    restarted.retire(run)


def test_principal_custody_is_required_instead_of_an_arbitrary_provision_callback(composition):
    _manager, _admin, _custody, _actors, _service, factory, _store, channels, _retired = composition
    with pytest.raises(TypeError, match="principal custody"):
        InProcessReviewActors(factory, channels, [].append)
