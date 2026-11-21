"""Install Core broker with role-exclusive signing/inference transport custody."""

import ssl
from collections.abc import Callable
from pathlib import Path

import httpx
from care_link_core.assistance import HttpAssistanceGateway
from care_link_core.assistance_broker import (
    HttpCoordinator,
    InferenceBroker,
    ReleasedFunction,
    TaskDelegationSigner,
)
from care_link_core.assistance_broker.actors import ActorTasks, BoundTaskGateway
from care_link_core.assistance_broker.work import WorkQueue
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_envelopes import IdentityEvidencePort
from care_link_core.manual_http import EnvelopeFactory
from care_link_core.manual_ports import BrowserSecurity, ManualGateway
from care_link_core.planning_ports import PlanningGateway
from care_link_core.plans_review_context import PlansReviewContexts
from care_link_core.referral_ports import ReceiverGateway, ReferralGateway
from care_link_core.review_channels import ReviewViews
from care_link_core.review_context import ReviewContexts
from care_link_domain import Actor, WorkloadPeer
from care_link_inference import HttpInferencePort
from care_link_knowledge import KnowledgeCatalog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request

from tools.imp02_application.mesh import MeshTransport

from .releases import Record, ReleaseBindings


def core_application(
    gateway: ManualGateway,
    security: BrowserSecurity,
    channels: ManualChannels,
    *,
    data_client: httpx.Client,
    data_origin: str,
    envelopes: EnvelopeFactory,
    identity: IdentityEvidencePort,
    signing_key: Ed25519PrivateKey,
    inference_tls: ssl.SSLContext,
    releases: ReleaseBindings,
    runtime_verify: Callable[[Request], WorkloadPeer],
    planning: PlanningGateway | None = None,
    referrals: ReferralGateway | None = None,
    receiver: ReceiverGateway | None = None,
    knowledge: KnowledgeCatalog | None = None,
    inference_socket: Path | None = None,
    review_contexts: ReviewContexts | None = None,
    plans_review_contexts: PlansReviewContexts | None = None,
    review_views: ReviewViews | None = None,
) -> FastAPI:
    actors = ActorTasks()
    task_gateway = HttpAssistanceGateway(data_client, data_origin, envelopes)
    work = WorkQueue(actors, task_gateway)
    bound = BoundTaskGateway(
        task_gateway, actors, enqueue=work.enqueue, remove=work.remove, knowledge=knowledge
    )
    coordinator = HttpCoordinator(
        data_client, TaskDelegationSigner(identity, signing_key), task_gateway
    )
    inference = HttpInferencePort(
        inference_tls,
        transport=(
            MeshTransport(inference_socket, "https://inference:8443")
            if inference_socket is not None
            else None
        ),
    )

    def release(function: str) -> ReleasedFunction:
        return releases.release_for_knowledge(function, knowledge.digest if knowledge else None)

    broker = InferenceBroker(
        coordinator,
        inference,
        actor_for_task=actors.resolve,
        release=release,
        work=work.claim,
    )

    def availability(actor: Actor) -> Record:
        available = actor.role == "worker" and releases.admitted_for_knowledge(
            "worker_summary", knowledge.digest if knowledge else None
        )
        return {
            "available": available,
            "functions": ["worker_summary"] if available else [],
            "reason": None if available else "assistance.function_disabled",
        }

    app = create_manual_app(
        gateway,
        security,
        channels,
        assistance=bound,
        assistance_availability=availability,
        assistance_broker=broker,
        runtime_verify=runtime_verify,
        planning=planning,
        referrals=referrals,
        receiver=receiver,
        review_contexts=review_contexts,
        plans_review_contexts=plans_review_contexts,
        review_views=review_views,
    )
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            inference.close()

    app.router.lifespan_context = lifespan
    return app
