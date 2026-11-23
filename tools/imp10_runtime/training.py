"""Opt-in compositions for the private synthetic training roles."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

import httpx
from care_link_core.evaluation_http import HttpEvaluationGateway
from care_link_core.manual_envelopes import IdentityEvidencePort
from care_link_core.manual_http import EnvelopeFactory
from care_link_core.training_http import HttpTrainingGateway
from care_link_data.training_replay import TrainingCapture, capture, sha256
from care_link_domain import Actor, AuthorityPort, CipherPort
from care_link_simulators.training import TrainingPermit, TrainingService
from care_link_simulators.training_app import TrainingIdentity, create_training_app
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import FastAPI, Request

Record = dict[str, object]


class TrainerIdentity(AuthorityPort, Protocol):
    def resolve(self, evidence: Record) -> Actor: ...


def training_application(
    dsn: str,
    identity: TrainerIdentity,
    workload: Callable[[Request, str], bool],
    permit: TrainingPermit,
    cipher: CipherPort,
    *,
    core_key: Ed25519PublicKey,
    identity_key: Ed25519PublicKey,
    artifact: bytes,
    artifact_digest: str,
    admitted_trainers: frozenset[str],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[FastAPI, TrainingService]:
    """Construct the simulator using distinct verified transport and storage custody."""
    service = TrainingService(
        dsn,
        identity,
        permit,
        cipher,
        artifact=artifact,
        artifact_digest=artifact_digest,
        admitted_trainers=admitted_trainers,
        complete_immediate_fixtures=True,
        clock=clock,
    )
    app = create_training_app(
        service, TrainingIdentity(core_key, identity_key, identity.resolve, clock=clock), workload
    )
    return app, service


def training_gateways(
    *,
    training_client: httpx.Client,
    training_origin: str,
    data_client: httpx.Client,
    data_origin: str,
    identity: IdentityEvidencePort,
    core_key: Ed25519PrivateKey,
    envelopes: EnvelopeFactory,
) -> tuple[HttpTrainingGateway, HttpEvaluationGateway]:
    """Ports for Core's opt-in named routes in an isolated synthetic topology."""
    return (
        HttpTrainingGateway(training_client, training_origin, identity, core_key),
        HttpEvaluationGateway(data_client, data_origin, envelopes),
    )


def admit_completed_capture(
    service: TrainingService,
    trainer: Actor,
    scenario_id: str,
    *,
    bundle: str,
    reviewers: frozenset[str],
) -> tuple[TrainingCapture, Record]:
    """Hand off a current, committed capture to the separately configured replay catalog."""
    fixture, observed, anchor = service.recording(trainer, scenario_id)
    sealed = capture(
        scenario_id,
        fixture,
        observed,
        anchor,
        bundle=bundle,
        owner_id=trainer.account_id,
        reviewers=reviewers,
    )
    return sealed, {
        "scenario_id": scenario_id,
        "input_manifest_digest": sha256(sealed.manifest),
        "recorded_outputs_digest": sha256(sealed.observations),
        "bundle_digest": bundle,
    }
