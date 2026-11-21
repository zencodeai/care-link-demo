"""Adverse aggregate disclosure and scope-bound cursor behavior."""

from copy import deepcopy

import pytest
from care_link_data.governance.evidence import cursor_decode, cursor_encode, query_filter
from care_link_data.governance.metrics import COHORTS, COMPANIONS, project_release
from care_link_domain import ManualError


def release():
    sizes = dict(zip(COHORTS, (120, 60, 60, 60, 60), strict=True))
    return {
        "definition_version": "synthetic-v1",
        "cells": {
            cohort: {
                "cohort_size": size,
                **{
                    metric: {"numerator": 0, "denominator": 0, "unknown": size}
                    for metric in COMPANIONS
                },
            }
            for cohort, size in sizes.items()
        },
    }


def test_coupled_visible_metrics_preserve_unknown_counts():
    view = project_release(release(), "fr-CA")
    assert view["suppressed"] is False
    assert all(
        view[name] == {"numerator": 0, "denominator": 0, "unknown": 60} for name in COMPANIONS
    )


@pytest.mark.parametrize("cohort", COHORTS)
def test_small_comparable_cell_suppresses_whole_family_including_total(cohort):
    value = release()
    value["cells"]["en-CA"]["cohort_size"] = 29
    for metric in COMPANIONS:
        value["cells"]["en-CA"][metric]["unknown"] = 29
    result = project_release(value, cohort)
    assert result["suppressed"] is True
    assert result["cohort_size"] is None
    assert all(result[name] is None for name in COMPANIONS)


def test_small_complement_is_suppressed():
    value = release()
    value["cells"]["en-CA"]["cohort_size"] = 100
    for metric in COMPANIONS:
        value["cells"]["en-CA"][metric]["unknown"] = 100
    assert project_release(value, "all")["suppressed"] is True


@pytest.mark.parametrize("metric", COMPANIONS)
def test_no_isolated_metric_or_individual_exposure_schema(metric):
    value = release()
    value["cells"]["all"].pop(metric)
    with pytest.raises(ManualError, match="metrics_release_invalid"):
        project_release(value, "all")
    value = release()
    value["cells"]["all"]["worker_id"] = "synthetic"
    with pytest.raises(ManualError, match="metrics_release_invalid"):
        project_release(value, "all")


def test_inconsistent_denominators_do_not_release_values():
    value = release()
    value["cells"]["all"]["safety"]["denominator"] = 1
    with pytest.raises(ManualError, match="metrics_denominator_invalid"):
        project_release(value, "all")


def test_cursor_is_bound_to_grant_window_action_not_page_size():
    key = b"synthetic-cursor-key" * 2
    query = {"grant_id": "synthetic-grant", "from": "start", "to": "end", "purpose": "audit"}
    token = cursor_encode(key, query, 45)
    assert cursor_decode(key, {**query, "cursor": token, "limit": 10}) == 45
    for name in query:
        with pytest.raises(ManualError, match="invalid_cursor"):
            cursor_decode(key, {**query, name: "changed", "cursor": token})
    with pytest.raises(ManualError, match="invalid_cursor"):
        cursor_decode(key, {**query, "cursor": token[:-2] + "XX"})


def test_export_scope_filter_keeps_grant_and_time_purpose_bindings():
    base = {"grant_id": "g", "purpose": "audit", "from": "f", "to": "t", "action": "a"}
    assert query_filter({**deepcopy(base), "cursor": "c", "limit": 10, "export_id": "e"}) == base
