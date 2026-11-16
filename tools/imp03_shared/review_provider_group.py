"""Fixed actor realms isolate provider browser cookies on the shared server."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from tools.demo.models import Record, record, text

from .review_provider import ProviderAdmin, ReviewProviderError

LABELS = {
    "participant": "participant",
    "worker1": "worker",
    "worker2": "worker2",
    "supervisor": "supervisor",
}


class ProviderGroup:
    def __init__(self, state: Record, password: str, ca_file: Path) -> None:
        value = record(json.loads(json.dumps(state)))
        providers = record(value.pop("slot_providers"))
        if set(providers) != set(LABELS):
            raise ReviewProviderError("provider_exact_slot_realms_required")
        current = record(value["users"])
        self.providers: dict[str, ProviderAdmin] = {}
        self.accounts: dict[str, ProviderAdmin] = {}
        for slot, label in LABELS.items():
            binding = record(providers[slot])
            actor = record(current[label])
            issued = record(record(binding["users"])[label])
            for key in ("id", "account_id", "username", "roles", "totp_secret"):
                if actor[key] != issued[key]:
                    raise ReviewProviderError("provider_slot_binding_changed")
            # The durable secret reference is current after password rotation.
            issued["password"] = actor["password"]
            provider = ProviderAdmin(binding, password, ca_file, namespace_slot=slot)
            account = text(actor, "account_id")
            if account in self.accounts:
                raise ReviewProviderError("provider_distinct_slot_accounts_required")
            self.providers[slot], self.accounts[account] = provider, provider

    def install_origins(self, origins: list[str]) -> Record:
        groups: dict[str, list[str]] = {slot: [] for slot in LABELS}
        for origin in origins:
            host = urlsplit(origin).hostname or ""
            matches = [
                slot for slot in LABELS if host.endswith("-" + slot + ".qualification.localhost")
            ]
            if len(matches) != 1:
                raise ReviewProviderError("provider_actor_origin_mismatch")
            groups[matches[0]].append(origin)
        for slot, requested in groups.items():
            if requested:
                self.providers[slot].install_origins(requested)
        return {"origins": sorted(set(origins)), "verified": True}

    def _account(self, account_id: str) -> ProviderAdmin:
        provider = self.accounts.get(account_id)
        if provider is None:
            raise ReviewProviderError("provider_actor_outside_lease")
        return provider

    def rotate(self, account_id: str, newpassword: str, totp_secret: str) -> Record:
        return self._account(account_id).rotate(account_id, newpassword, totp_secret)

    def verify_password(self, account_id: str, password: str, totp_secret: str) -> Record:
        return self._account(account_id).verify_password(account_id, password, totp_secret)


def provider_admin(state: Record, password: str, ca_file: Path) -> ProviderAdmin | ProviderGroup:
    return (
        ProviderGroup(state, password, ca_file)
        if "slot_providers" in state
        else ProviderAdmin(state, password, ca_file)
    )
