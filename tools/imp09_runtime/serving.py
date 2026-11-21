"""Bind the same host generation gate at edge and business authorization."""

from collections.abc import Callable

from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_ports import BrowserSecurity, ManualGateway
from care_link_domain import JournalPort
from care_link_recovery_control import BoundGenerationJournal, RecoveryCoordinator
from fastapi import FastAPI


def manual_target_app(
    coordinator: RecoveryCoordinator,
    target_id: str,
    generation: int,
    gateway_factory: Callable[[JournalPort], ManualGateway],
    security: BrowserSecurity,
    channels: ManualChannels,
) -> FastAPI:
    """The factory injects this journal into ManualService and its dispatch path.

    The edge rechecks each operation and SSE disclosure; data/dispatch recheck
    the same effective host generation under their existing final transaction
    guard. Recovery runs on its separate authenticated origin during maintenance.
    """
    gate = BoundGenerationJournal(coordinator, target_id)
    gateway = gateway_factory(gate)
    return create_manual_app(
        gateway, security, channels, generation_admission=lambda: gate.require(generation)
    )
