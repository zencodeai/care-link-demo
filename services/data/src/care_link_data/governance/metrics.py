"""Reviewed fixed aggregate releases with coupled, complementary suppression."""

from datetime import datetime
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import ManualError

from ..store import Record, Transaction, instant, text
from ..values import digest, object_value
from .authority import human_account

COHORTS = ("all", "en-CA", "fr-CA", "CA-XX", "CA-YY")
COMPANIONS = ("safety", "access", "equity", "police_avoidance", "exposure_aggregate")


def release_key(query: Record) -> str:
    return digest(
        {name: query[name] for name in ("definition_version", "period_start", "period_end")}
    )


def suppressed(version: str) -> Record:
    return {
        "definition_version": version,
        "cohort_size": None,
        "suppressed": True,
        **dict.fromkeys(COMPANIONS),
    }


def release_digest(release: Record) -> str:
    return digest(
        {
            "definition_version": release["definition_version"],
            "period_start": release["period_start"],
            "period_end": release["period_end"],
            "source_digest": release["source_digest"],
            "cells": release["cells"],
        }
    )


def project_release(release: Record, cohort: str) -> Record:
    """All fixed comparable cells must be safe before any value is disclosed.

    Overlapping periods and ad hoc filters are absent: callers can select only
    exact, independently reviewed releases. This conservative family suppression
    does not claim formal differential privacy.
    """
    version = text(release, "definition_version")
    cells = object_value(release["cells"])
    if set(cells) != set(COHORTS) or cohort not in COHORTS:
        raise ManualError("governance.metrics_release_invalid", 503)
    sizes: dict[str, int] = {}
    for name, raw in cells.items():
        cell = object_value(raw)
        size = cell.get("cohort_size")
        if type(size) is not int or not 0 <= size <= 1_000_000:
            raise ManualError("governance.metrics_release_invalid", 503)
        sizes[name] = size
        if set(cell) != {"cohort_size", *COMPANIONS}:
            raise ManualError("governance.metrics_release_invalid", 503)
        for metric in COMPANIONS:
            count = cell[metric]
            if count is None and metric == "exposure_aggregate":
                continue
            validate_contract("MetricCount", count)
            value = object_value(count)
            numerator, denominator, unknown = (
                cast(int, value[k]) for k in ("numerator", "denominator", "unknown")
            )
            if numerator > denominator or denominator + unknown != size:
                raise ManualError("governance.metrics_denominator_invalid", 503)
    total = sizes["all"]
    # A small complement is sensitive even when both published cell sizes are
    # individually >=30. Suppress the entire family including exact counts.
    unclassified = total - sizes["CA-XX"] - sizes["CA-YY"]
    if (
        (0 < unclassified < 30)
        or any(size < 30 for size in sizes.values())
        or any(not 30 <= total - size for name, size in sizes.items() if name != "all")
    ):
        return suppressed(version)
    if sizes["en-CA"] + sizes["fr-CA"] != total or sizes["CA-XX"] + sizes["CA-YY"] > total:
        raise ManualError("governance.metrics_partition_invalid", 503)
    result: Record = {
        "definition_version": version,
        "suppressed": False,
        **object_value(cells[cohort]),
    }
    validate_contract("MetricsView", result)
    return result


def read_metrics(tx: Transaction, query: Record, now: datetime) -> Record:
    release = tx.peek("gov_metric_release", release_key(query))
    if release is None:
        raise ManualError("governance.metrics_release_unavailable", 404)
    if instant(release, "expires_at") <= now:
        raise ManualError("governance.metrics_release_expired", 403)
    if (
        release["definition_version"] != query["definition_version"]
        or release["period_start"] != query["period_start"]
        or release["period_end"] != query["period_end"]
    ):
        raise ManualError("governance.metrics_release_invalid", 503)
    receipt = tx.peek("gov_approval", text(release, "disclosure_receipt_id"))
    if (
        receipt is None
        or receipt["active"] is not True
        or receipt["purpose"] != "metrics_release"
        or receipt["request_digest"] != release_digest(release)
        or instant(receipt, "expires_at") <= now
    ):
        raise ManualError("governance.metrics_disclosure_review_required", 403)
    reviewer = human_account(tx, text(receipt, "approver_account_id"), "privacy")
    if reviewer["human_id"] != receipt["approver_human_id"]:
        raise ManualError("governance.metrics_disclosure_review_required", 403)
    return project_release(release, text(query, "cohort"))
