package care_link.manual

import rego.v1

# Intended as an additive module in the independently staged, signed candidate.
# Current exact custody is supplied and revalidated by the guarded Data transaction.
allow if {
	input.action in {"replay_create", "evaluation_read"}
	input.tags == {"environment": "demo", "population": "synthetic"}
	input.actor.kind == "human"
	input.actor.workload_id == "spiffe://care-link.demo/demo/data"
	input.actor.role in {"trainer", "governance"}
	input.actor.assurance in {"AL2", "AL3"}
	input.scope == {"purpose": "training", "session_id": null, "subject_id": null, "fields": [], "recipient_id": null}
	input.mode in {"normal", "ai_disabled"}
	input.authority_complete
	input.audit_ready
	count(input.artifact_digests) == 3
	f := input.authority_facts
	f.actor_role_allowed
	f.resource_owned_or_assigned
	f.field_scope_allowed
	f.source_current
	f.artifact_admitted
	f.jurisdiction_allowed
	f.workload_unfenced
	not f.consent.required
	not f.review.required
	f.exception_id == null
}
