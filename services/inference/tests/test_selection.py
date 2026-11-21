import json
from uuid import uuid4

import pytest
from care_link_inference import InferenceDenied
from care_link_inference.context import render_messages
from care_link_inference.selection import selection_to_proposal


def item(kind, label, text):
    return {
        "source": {
            "kind": kind,
            "id": str(uuid4()),
            "revision": "1",
            "digest": "a" * 64,
            "observed_at": "2026-11-20T00:00:00Z",
            "verification": "unverified",
        },
        "label": label,
        "text": text,
        "critical": True,
    }


def project(selection, items):
    return selection_to_proposal(
        json.dumps(selection),
        task_id=str(uuid4()),
        step_id=str(uuid4()),
        fence="1",
        revision="2",
        items=items,
    )


def test_server_assigns_same_ordered_indices_and_assembles_all_authority_metadata():
    report = item("assertion", "untrusted_report", "Fictional first line.\nFictional second line.")
    protocol = item("protocol", "approved_fact", "Synthetic worker review is required.")
    messages = render_messages([report, protocol])
    assert json.loads(messages[0]["content"])["evidence_index"] == 0
    assert json.loads(messages[0]["content"])["source"] == protocol["source"]
    assert json.loads(messages[1]["content"])["evidence_index"] == 1
    result = project({"selected_indices": [1, 0]}, [report, protocol])
    assert result["candidate_text"] == report["text"] + "\n" + protocol["text"]
    assert result["sources"] == [report["source"], protocol["source"]]
    assert result["next"] is None and result["completion_claim"] is False


def test_missing_any_patient_assertion_is_rejected_even_with_valid_protocol():
    report = item("assertion", "untrusted_report", "Fictional preference.")
    protocol = item("protocol", "approved_fact", "Synthetic workflow.")
    with pytest.raises(InferenceDenied, match="critical_evidence_missing"):
        project({"selected_indices": [0]}, [report, protocol])
    assert project({"selected_indices": [1]}, [report, protocol])["sources"] == [report["source"]]


@pytest.mark.parametrize("indices", [[0, 0], [True], [0.0], [-1], [64], [], [1]])
def test_duplicates_coercions_empty_and_out_of_scope_indices_rejected(indices):
    with pytest.raises(InferenceDenied):
        project({"selected_indices": indices}, [item("assertion", "untrusted_report", "Fictional")])


def test_model_cannot_supply_identity_text_effect_or_extra_authority_fields():
    with pytest.raises(InferenceDenied, match="invalid_evidence_selection"):
        project(
            {"selected_indices": [0], "candidate_text": "Consent granted", "next": "send"},
            [item("assertion", "untrusted_report", "Fictional")],
        )


def test_more_than_twelve_patient_assertions_cannot_be_silently_dropped():
    items = [item("assertion", "untrusted_report", "Fictional") for _ in range(13)]
    with pytest.raises(InferenceDenied, match="critical_evidence_missing"):
        project({"selected_indices": list(range(12))}, items)
