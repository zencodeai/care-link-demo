"""Validate the closed, deliberately unadmitted IMP-02 source candidate configuration."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/demo/imp-02-admission.json"


def validate(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["admission configuration must be an object"]
    expected = {
        "format_version",
        "environment",
        "participant_admission",
        "police_integration",
        "autonomous_emergency_contact",
        "deployment_status",
        "identity",
        "workload",
        "help",
        "static",
    }
    errors: list[str] = []
    if set(value) != expected:
        errors.append("closed admission configuration keys differ")
    fixed = {
        "format_version": "imp-02-admission-1",
        "environment": "synthetic-demo",
        "participant_admission": False,
        "police_integration": False,
        "autonomous_emergency_contact": False,
        "deployment_status": "not_deployed",
    }
    for key, expected_value in fixed.items():
        if type(value.get(key)) is not type(expected_value) or value.get(key) != expected_value:
            errors.append(f"{key} cannot activate the unqualified source candidate")
    sections = {
        "identity": {
            "issuer",
            "client_id",
            "redirect_uri",
            "provider_version",
            "identity_store",
            "account_retention_schedule",
            "positive_authority_cache",
            "workforce_requires_local_entitlement_and_mfa",
        },
        "workload": {
            "trust_domain",
            "selected_family",
            "spire_version",
            "envoy_version",
            "cni_version",
            "credential_lifetime_seconds",
            "attestation_evidence",
            "host_firewall_evidence",
            "route_probe_evidence",
            "require_current_fence_per_operation",
            "direct_backend_allowed",
            "untested_ipv6_allowed",
        },
        "help": {
            "separate_origin",
            "spool",
            "authority_budget_ms",
            "fresh_authority_each_operation",
            "store_private_story",
            "accept_state",
            "connection_confirmed",
        },
        "static": {
            "separate_origin",
            "public_content_review_receipt",
            "public_content_status",
            "request_time_identity_dependency",
        },
    }
    for section, keys in sections.items():
        data = value.get(section)
        if not isinstance(data, dict) or set(data) != keys:
            errors.append(f"{section} closed shape differs")
    constraints = {
        "identity": {
            "identity_store": "separate-postgresql",
            "positive_authority_cache": False,
            "workforce_requires_local_entitlement_and_mfa": True,
        },
        "workload": {
            "trust_domain": "care-link.demo",
            "require_current_fence_per_operation": True,
            "direct_backend_allowed": False,
            "untested_ipv6_allowed": False,
        },
        "help": {
            "spool": "sqlite-wal-full",
            "authority_budget_ms": 1000,
            "fresh_authority_each_operation": True,
            "store_private_story": False,
            "accept_state": "accepted_unconnected",
            "connection_confirmed": False,
        },
        "static": {
            "public_content_status": "unavailable",
            "request_time_identity_dependency": False,
        },
    }
    for section, rules in constraints.items():
        data = value.get(section)
        if isinstance(data, dict):
            for key, required in rules.items():
                if type(data.get(key)) is not type(required) or data.get(key) != required:
                    errors.append(f"{section}.{key} violates the bounded candidate")
    return errors


def main() -> None:
    failures = validate(json.loads(CONFIG.read_text()))
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        "IMP-02 source admission remains disabled; no live identity/network/content proof implied."
    )


if __name__ == "__main__":
    main()
