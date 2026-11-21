"""Cross-boundary contracts cannot widen runtime or knowledge authority."""

import pytest
from care_link_contracts import ContractError, validate_contract


def test_runtime_poll_is_empty_and_work_binding_is_all_or_nothing():
    validate_contract("RuntimeWorkRequest", {})
    validate_contract("RuntimeWorkItem", {"task_id": None, "task_revision": None, "fence": None})
    with pytest.raises(ContractError):
        validate_contract("RuntimeWorkRequest", {"actor_id": "model-selected"})
    with pytest.raises(ContractError):
        validate_contract("RuntimeWorkItem", {"task_id": None, "task_revision": "1", "fence": "0"})


def test_knowledge_lookup_cannot_request_another_role_or_patient():
    query = {"query": "shared decision", "locale": "en-CA"}
    validate_contract("KnowledgeQuery", query)
    for extra in (
        {"role": "worker"},
        {"patient_id": "another-person"},
        {"url": "https://example.com"},
    ):
        with pytest.raises(ContractError):
            validate_contract("KnowledgeQuery", {**query, **extra})
