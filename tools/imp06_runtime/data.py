"""Data-only business credentials and durable inference capacity composition."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager

from care_link_data import (
    AssistanceCoordinator,
    ManualService,
    RuntimeAuthenticator,
    StoredInferenceAuthority,
    attach_inference_ledger_gateway,
)
from care_link_data.app import GatewaySecurity, create_app
from care_link_data.assistance.runtime_app import attach_assistance_runtime_gateway
from care_link_data.assistance_jobs import PostgresJobLedger
from care_link_domain import ManualError, WorkloadPeer
from care_link_knowledge import KnowledgeCatalog
from care_link_policy_input import DelegationVerifier
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from .provider_stop import ProviderStopAuthority
from .releases import ReleaseBindings


async def _reconcile(ledger: PostgresJobLedger, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await run_in_threadpool(ledger.reconcile_stopped)
        except ManualError:
            # An unavailable or uncertain transaction cannot create capacity.
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass


def data_application(
    service: ManualService,
    security: GatewaySecurity,
    *,
    releases: ReleaseBindings,
    delegations: DelegationVerifier,
    verify: Callable[[Request, str], bool],
    runtime_current: Callable[[WorkloadPeer], bool],
    bridge_generation: str,
    knowledge: KnowledgeCatalog | None = None,
    knowledge_regions: Mapping[str, str] | None = None,
    provider_stop: ProviderStopAuthority | None = None,
) -> FastAPI:
    if provider_stop is not None and provider_stop.current_generation != bridge_generation:
        raise ValueError("provider stop authority must bind the current Data generation")
    coordinator = AssistanceCoordinator(
        service,
        admitted=lambda function: releases.admitted_for_knowledge(
            function, knowledge.digest if knowledge else None
        ),
        runtime_current=runtime_current,
        knowledge=knowledge,
        knowledge_regions=knowledge_regions,
    )
    app = create_app(service, security, assistance=coordinator)
    attach_assistance_runtime_gateway(
        app, coordinator, RuntimeAuthenticator(delegations, verify, runtime_current)
    )
    authority = StoredInferenceAuthority(
        coordinator,
        coordinator.actor_for_task,
        lambda: releases.records()
        if releases.knowledge_matches(knowledge.digest if knowledge else None)
        else {},
        bridge_generation,
    )
    ledger = PostgresJobLedger(
        service.store,
        current=lambda tx, job: coordinator.inference_current(tx, job, coordinator.actor_for_task),
        verified_stop_time=provider_stop.verified_stop_time
        if provider_stop is not None
        else lambda _generation: None,
        bridge_generation=bridge_generation,
    )
    attach_inference_ledger_gateway(app, ledger, verify, authority)
    if provider_stop is not None:
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application: FastAPI) -> AsyncIterator[None]:
            async with original_lifespan(application):
                stop = asyncio.Event()
                worker = asyncio.create_task(_reconcile(ledger, stop))
                try:
                    yield
                finally:
                    stop.set()
                    await worker

        app.router.lifespan_context = lifespan
    return app
