"""Receiver, trainer and replay composition for the synthetic outage topology."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import httpx
import psycopg
from care_link_core.manual_envelopes import IdentityEvidencePort
from care_link_core.receiver_http import HttpReceiverGateway
from care_link_core.training_http import HttpTrainingGateway
from care_link_data import AESGCMContentCipher, PostgresStore
from care_link_data.evaluation import ReplayCreate, ReplayResult, replay_request
from care_link_data.referral_http import HttpReceiverPort
from care_link_data.store import Record
from care_link_data.training_replay import OfflineTrainingReplay, training_bundle
from care_link_domain import Actor
from care_link_simulators import ReceiverService
from care_link_simulators.app import create_app as receiver_app
from care_link_simulators.security import ReceiverIdentity
from care_link_simulators.training import TrainingService
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import Request

from services.data.tests.test_imp10_training_boundary import ARTIFACT, PIN, ROOT, fixture
from tools.imp10_runtime.training import admit_completed_capture, training_application

if TYPE_CHECKING:
    from services.data.tests.conftest import Harness
    from services.data.tests.imp10_outage_listeners import RoleTopology

type ReferralCase = tuple[
    "Harness", ReceiverService, Actor, Record, Record, Record, Record, Record, Record, Record
]
SCENARIOS = "/v1/training/scenarios"
REPLAYS = "/v1/evaluation/replays"


class ReplayAdmission:
    """Expose the product evaluator before a scenario has a committed capture."""

    def __init__(self) -> None:
        self.bundle = training_bundle(
            {
                "runner": (ROOT / "packages/domain/src/care_link_domain/training.py").read_bytes(),
                "artifact": ARTIFACT,
                "contracts": (
                    ROOT / "packages/contracts/python/src/care_link_contracts/schema.json"
                ).read_bytes(),
            }
        )
        self._evaluator = OfflineTrainingReplay([], bundle=self.bundle, artifact_digest=PIN)

    def admit(
        self, training: TrainingService, trainer: Actor, scenario: str, reviewers: frozenset[str]
    ) -> ReplayCreate:
        sealed, request = admit_completed_capture(
            training, trainer, scenario, bundle=self.bundle, reviewers=reviewers
        )
        self._evaluator = OfflineTrainingReplay([sealed], bundle=self.bundle, artifact_digest=PIN)
        return replay_request(request)

    def authorize(self, actor: Actor, request: ReplayCreate) -> None:
        self._evaluator.authorize(actor, request)

    def evaluate(self, request: ReplayCreate) -> ReplayResult:
        return self._evaluator.evaluate(request)


@dataclass(frozen=True)
class OutageRoles:
    receiver_actor: Actor
    other_receiver: Actor
    trainer: Actor
    other_trainer: Actor
    receiver_gateway: HttpReceiverGateway
    training_gateway: HttpTrainingGateway
    receiver: ReceiverService
    training: TrainingService
    replay_evaluator: ReplayAdmission

    def admit_replay(
        self, scenario_id: str, *, reviewers: frozenset[str] = frozenset()
    ) -> ReplayCreate:
        return self.replay_evaluator.admit(self.training, self.trainer, scenario_id, reviewers)


def start_roles(
    topology: RoleTopology,
    core_client: httpx.Client,
    data_client: httpx.Client,
    case: ReferralCase,
    training_dsn: str,
    *,
    core_key: Ed25519PrivateKey,
    identity_key: Ed25519PublicKey,
    evidence: IdentityEvidencePort,
    resolve: Callable[[Record], Actor],
    workload: Callable[[Request, str], bool],
) -> OutageRoles:
    h, seed_receiver, seed_receiver_actor, *_ = case

    def independent_actor(role: str) -> Actor:
        return replace(
            h.worker,
            role=role,
            account_id=str(uuid4()),
            browser_session_digest=secrets.token_hex(32),
            credential_ref=secrets.token_hex(32),
            identity_evidence_id=str(uuid4()),
        )

    receiver_actor = replace(
        independent_actor("receiver"), account_id=seed_receiver_actor.account_id
    )
    other_receiver = independent_actor("receiver")
    trainer, other_trainer = independent_actor("trainer"), independent_actor("trainer")
    data_admin = PostgresStore(h.database.admin)
    for actor in (trainer, other_trainer):
        data_admin.provision_principal(actor)

    sending_services = seed_receiver.services
    service_id = seed_receiver.actor_services[receiver_actor.account_id]
    other_service = str(uuid4())
    receiver = ReceiverService(
        seed_receiver.dsn,
        seed_receiver.cipher,
        h.authority,
        actor_services={
            receiver_actor.account_id: service_id,
            other_receiver.account_id: other_service,
        },
        services=sending_services | {other_service},
    )
    public_key = core_key.public_key()
    topology.start(
        "receiver",
        receiver_app(receiver, ReceiverIdentity(public_key, identity_key, resolve), workload),
    )
    receiver_origin = topology.origin("receiver")
    h.service.receiver = HttpReceiverPort(data_client, receiver_origin, sending_services)

    admitted = frozenset({trainer.account_id, other_trainer.account_id})

    class TrainerIdentity:
        current = h.authority.current

        @staticmethod
        def resolve(evidence: Record) -> Actor:
            return resolve(evidence)

    def training_permit(actor: Actor, action: str, target: str | None, _digest: str) -> bool:
        return actor.account_id in admitted and (
            action == "scenario_create"
            and target is None
            or action in {"scenario_read", "scenario_stop"}
            and target is not None
        )

    training_app, training = training_application(
        training_dsn,
        TrainerIdentity(),
        workload,
        training_permit,
        AESGCMContentCipher(secrets.token_bytes(32)),
        core_key=public_key,
        identity_key=identity_key,
        artifact=ARTIFACT,
        artifact_digest=PIN,
        admitted_trainers=admitted,
    )
    topology.start("training", training_app)
    replay = ReplayAdmission()
    h.service.replay_evaluator = replay
    return OutageRoles(
        receiver_actor,
        other_receiver,
        trainer,
        other_trainer,
        HttpReceiverGateway(core_client, receiver_origin, evidence, core_key),
        HttpTrainingGateway(core_client, topology.origin("training"), evidence, core_key),
        receiver,
        training,
        replay,
    )


def assert_receiver_scope(
    browser: httpx.Client,
    core: str,
    dispatch_id: str,
    *,
    owner: Mapping[str, str],
    other: Mapping[str, str],
    worker: Mapping[str, str],
) -> Record:
    inbox = core + "/v1/receiver/inbox"
    package = core + "/v1/receiver/packages/" + dispatch_id
    assigned = browser.get(inbox, headers=owner)
    assert assigned.status_code == 200, assigned.text
    assert dispatch_id in assigned.json()["dispatch_ids"]
    foreign = browser.get(inbox, headers=other)
    assert foreign.status_code == 200, foreign.text
    assert foreign.json() == {"dispatch_ids": [], "next_cursor": None}
    visible = browser.get(package + "/detail", headers=owner)
    assert visible.status_code == 200, visible.text
    for headers in (other, worker):
        denied = browser.get(package, headers=headers)
        assert denied.status_code == 403, denied.text
        assert "fields" not in denied.json()
    return cast(Record, visible.json())


def assert_training_capture(
    browser: httpx.Client,
    core: str,
    roles: OutageRoles,
    *,
    owner: Mapping[str, str],
    other: Mapping[str, str],
    worker: Mapping[str, str],
) -> str:
    route = core + SCENARIOS
    key, denied_key = str(uuid4()), str(uuid4())
    parameters = fixture("partial")
    denied = browser.post(route, headers={**worker, "Idempotency-Key": denied_key}, json=parameters)
    assert denied.status_code == 403, denied.text
    created = browser.post(route, headers={**owner, "Idempotency-Key": key}, json=parameters)
    assert created.status_code == 200, created.text
    scenario_id = created.json()["resource_id"]
    target = route + "/" + scenario_id
    admitted = browser.get(target, headers=owner)
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["state"] == "completed"
    forbidden = browser.get(target, headers=other)
    assert forbidden.status_code == 404, forbidden.text
    assert "evidence_digest" not in forbidden.json()
    with psycopg.connect(roles.training.dsn) as connection:
        row = connection.execute(
            "SELECT owner_id::text,state,projection_ciphertext,content_key_ref,evidence_digest "
            "FROM training.scenario WHERE id=%s",
            (scenario_id,),
        ).fetchone()
        operation = connection.execute(
            "SELECT action,owner_id::text FROM training.operation WHERE id=%s", (key,)
        ).fetchall()
        forbidden_operation = connection.execute(
            "SELECT id FROM training.operation WHERE id=%s", (denied_key,)
        ).fetchone()
    assert row is not None
    owner_id, state, ciphertext, key_ref, evidence_digest = row
    assert (owner_id, state) == (roles.trainer.account_id, "completed")
    assert ciphertext and "support_preference" not in ciphertext
    assert key_ref == roles.training.content_key_ref
    assert evidence_digest == admitted.json()["evidence_digest"]
    recording = json.loads(roles.training.cipher.decrypt(ciphertext))
    assert recording["capture_kind"] == "deterministic_fixture"
    assert recording["effects"] == {
        "external_contact": "suppressed",
        "emergency_target": "denied",
        "serving_write": "suppressed",
        "model_request": "suppressed",
        "identity_link": "disabled",
    }
    assert operation == [("scenario_create", owner_id)]
    assert forbidden_operation is None
    return cast(str, scenario_id)


def assert_replay_scope(
    browser: httpx.Client,
    core: str,
    h: Harness,
    roles: OutageRoles,
    request: ReplayCreate,
    *,
    owner: Mapping[str, str],
    other: Mapping[str, str],
    worker: Mapping[str, str],
) -> Record:
    route = core + REPLAYS
    metric_releases = h.read("SELECT count(*) FROM quality.metric_release")
    denied = browser.post(route, headers={**other, "Idempotency-Key": str(uuid4())}, json=request)
    assert denied.status_code == 403, denied.text
    headers = {**owner, "Idempotency-Key": str(uuid4())}
    accepted = browser.post(route, headers=headers, json=request)
    assert accepted.status_code == 200, accepted.text
    value = cast(Record, accepted.json())
    assert value["state"] == "completed" and value["evidence_digest"]
    assert value["clinical_claim"] is False
    retry = browser.post(route, headers=headers, json=request)
    assert retry.status_code == 200, retry.text
    assert retry.json() == value
    target = route + "/" + cast(str, value["id"])
    assert browser.get(target, headers=owner).json() == value
    for actor_headers in (other, worker):
        denied = browser.get(target, headers=actor_headers)
        assert denied.status_code == 403, denied.text
        assert "evidence_digest" not in denied.json()
    assert h.read(
        "SELECT id::text,principal_id::text,state,evidence_digest,input_manifest_digest,"
        "recorded_outputs_digest,bundle_digest FROM quality.evaluation WHERE scenario_id=%s",
        (request["scenario_id"],),
    ) == [
        (
            value["id"],
            roles.trainer.account_id,
            "completed",
            value["evidence_digest"],
            request["input_manifest_digest"],
            request["recorded_outputs_digest"],
            request["bundle_digest"],
        )
    ]
    assert h.read("SELECT count(*) FROM quality.metric_release") == metric_releases
    return value
