"""Read-only preflight against explicitly selected admitted directory fixtures."""

from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import validate_contract
from care_link_data.control import ManualService
from care_link_data.store import text
from care_link_data.values import object_value
from care_link_domain import Actor

from .types import JsonRecord

CASES = {"current", "stale", "suspended", "unknown"}


class DirectoryReviewPreflight:
    def __init__(
        self,
        service: ManualService,
        *,
        service_ids: dict[str, str],
        queries: tuple[JsonRecord, ...],
    ) -> None:
        if set(service_ids) != CASES or len(set(service_ids.values())) != 4:
            raise ValueError("Four explicitly selected directory cases required")
        for value in service_ids.values():
            if str(UUID(value)) != value:
                raise ValueError("Canonical directory service IDs required")
        if {query.get("locale") for query in queries} != {"en-CA", "fr-CA"}:
            raise ValueError("Explicit English and French directory queries required")
        for query in queries:
            validate_contract("DirectoryQuery", query)
            if "cursor" in query:
                raise ValueError("Directory preflight must begin with the first page")
        self.service, self.service_ids, self.queries = service, dict(service_ids), queries

    def __call__(self, run: JsonRecord, actor: Actor) -> JsonRecord:
        if actor.review_run_id != run["run_id"]:
            raise ValueError("Exact run actor required for directory preflight")
        observed: dict[str, set[str]] = {"en-CA": set(), "fr-CA": set()}
        for query in self.queries:
            body = dict(query)
            for _page in range(20):
                page = self.service.directory_search(actor, str(uuid4()), body)
                validate_contract("DirectoryPage", page)
                items = page["items"]
                if not isinstance(items, list):
                    raise ValueError("Directory page items required")
                for raw_item in cast(list[object], items):
                    item = object_value(raw_item)
                    observed[body["locale"]].add(text(item, "id"))
                cursor = page.get("next_cursor")
                if cursor is None:
                    break
                body["cursor"] = cursor
            else:
                raise ValueError("Directory preflight exceeded bounded paging")
        required = set(self.service_ids.values())
        if any(not required <= ids for ids in observed.values()):
            raise ValueError("Selected directory review cases are not populated in both languages")
        for case, service_id in self.service_ids.items():
            view = self.service.directory_read(actor, service_id)
            validate_contract("DirectoryView", view)
            state, facts = view["state"], object_value(view["facts"])
            expected_state = {
                "current": "verified",
                "stale": "stale",
                "suspended": "suspended",
            }.get(case)
            if expected_state is not None and state != expected_state:
                raise ValueError("Directory review fixture has changed state")
            if case == "unknown" and facts["availability"] != "unknown":
                raise ValueError("Directory review requires truthful unknown availability")
            if case in {"stale", "suspended"} and facts["availability"] not in {
                "unknown",
                "unavailable",
            }:
                raise ValueError("Noncurrent directory cases cannot imply availability")
            if case == "current" and facts["availability"] != "available_fixture":
                raise ValueError("Current directory review fixture is not currently available")
        return {
            "confirmed": True,
            "cases": sorted(CASES),
            "locales": sorted(observed),
            "service_ids": dict(self.service_ids),
        }
