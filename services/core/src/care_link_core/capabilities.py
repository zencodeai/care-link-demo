"""Truthful developer capability projection; no business handlers exist yet."""

from care_link_contracts import DeveloperCapability, validate_contract


def developer_capability() -> DeveloperCapability:
    result: DeveloperCapability = {
        "contract_version": "dev-1",
        "status": "developer_only",
        "tags": {"environment": "demo", "population": "synthetic"},
        "participant_admission": False,
        "business_operations": "unavailable",
        "contract_validation": True,
    }
    validate_contract("DeveloperCapability", result)
    return result
