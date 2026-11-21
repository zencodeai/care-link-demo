package care_link.manual

import rego.v1

default allow := false

participant_actions := {"session_create", "session_disclosure", "session_turns", "session_assertions", "session_choices", "session_human_request", "session_end", "continuation_issue", "continuation_rotate", "continuation_recover"}
workforce_actions := {"queue_list", "workforce_reserve", "workforce_accept", "workforce_prepare_transfer", "workforce_confirm_transfer", "workforce_transfer_failed"}
read_actions := {"review_workspace", "review_draft_save", "review_intent_prepare", "review_intent_cancel", "session_read", "messages_read", "session_events", "operation_status", "channel_challenge_read", "channel_ack", "message_send"}
participants := {"pid", "carer", "professional_participant"}
workforce := {"worker", "supervisor"}

role_allowed if {
	input.action in participant_actions
	input.actor.role in participants
}

role_allowed if {
	input.action in workforce_actions
	input.actor.role in workforce
	input.actor.assurance in {"AL2", "AL3"}
}

role_allowed if {
	input.action in read_actions
	input.actor.role in (participants | workforce)
}

role_allowed if {
	input.action in {"workforce_observe", "workforce_takeover"}
	input.actor.role == "supervisor"
	input.actor.assurance in {"AL2", "AL3"}
}

role_allowed if {
	input.action in {"control_change", "manual_identity_restrict", "manual_queue_review"}
	input.actor.role in {"operator", "security"}
	input.actor.assurance in {"AL2", "AL3"}
}

mode_allowed if input.mode in {"normal", "ai_disabled"}

mode_allowed if {
	input.action in {"control_change", "manual_identity_restrict", "manual_queue_review"}
	input.mode in {"restricted", "quarantine"}
}

allow if {
	not input.action in referral_actions
	input.tags == {"environment": "demo", "population": "synthetic"}
	input.actor.kind == "human"
	input.actor.workload_id == "spiffe://care-link.demo/demo/data"
	input.authority_complete
	input.audit_ready
	mode_allowed
	assistance_mode_allowed
	role_allowed
	f := input.authority_facts
	f.actor_role_allowed
	f.resource_owned_or_assigned
	f.field_scope_allowed
	source_allowed
	f.jurisdiction_allowed
	f.workload_unfenced
	consent_allowed
	directory_binding_allowed
	not f.review.required
	f.exception_id == null
	purpose_allowed
}

# True workload duties are independently verified against the signed admitted registry.
# They never enter the human role/assurance branch or supply a human approval.
allow if {
	input.actor.kind == "workload"
	input.tags == {"environment": "demo", "population": "synthetic"}
	input.authority_complete
	input.audit_ready
	input.action in {"identity_revoke", "job_execute"}
	workload_duty_action
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
	count(input.artifact_digests) == 1
}

workload_duty_action if {
	input.action == "identity_revoke"
	input.actor.workload_id == "spiffe://care-link.demo/demo/identity"
	input.scope.purpose == "security"
}

workload_duty_action if {
	input.action == "job_execute"
	input.actor.workload_id == "spiffe://care-link.demo/demo/jobs"
	input.scope.purpose == "support"
	input.mode in {"normal", "ai_disabled"}
	input.actor.job_id != null
}

# IMP-04 additions. The gateway supplies current field/scope facts under locks;
# relationship labels and model-generated claims never provide authority.
role_allowed if {
	input.action in {"plan_create", "plan_retire"}
	input.actor.role == "pid"
	input.actor.assurance in {"AL2", "AL3"}
}

role_allowed if {
	input.action == "plan_field_append"
	input.actor.role in {"pid", "worker"}
	input.actor.assurance in {"AL2", "AL3"}
}

role_allowed if {
	input.action in {"plan_read", "consent_read", "directory_search", "directory_read"}
	input.actor.role in (participants | workforce)
}

role_allowed if {
	input.action == "consent_grant"
	input.actor.role in participants
	input.actor.assurance in {"AL2", "AL3"}
}

role_allowed if {
	input.action == "consent_revoke"
	input.actor.role in participants
}

role_allowed if {
	input.action == "directory_ingest"
	input.actor.role in {"operator", "governance"}
	input.actor.assurance in {"AL2", "AL3"}
}

role_allowed if {
	input.action == "directory_suspend"
	input.actor.role in {"security", "governance"}
	input.actor.assurance in {"AL2", "AL3"}
}

mode_allowed if {
	input.action in {"consent_revoke", "directory_suspend"}
	input.mode in {"restricted", "quarantine"}
}

purpose_allowed if {
	not startswith(input.action, "plan_")
	not input.action in {"directory_ingest", "directory_suspend"}
	input.scope.purpose in {"support", "service_operations"}
}

purpose_allowed if {
	startswith(input.action, "plan_")
	input.scope.purpose == "plan"
}

purpose_allowed if {
	input.action == "directory_ingest"
	input.scope.purpose == "governance"
}

purpose_allowed if {
	input.action == "directory_suspend"
	input.scope.purpose == "security"
}

# Directory operations expose qualified information or apply restrictions only;
# source failure must permit quarantine/unknown-state display, never dispatch.
source_allowed if {
	input.action in {"directory_search", "directory_read", "directory_ingest", "directory_suspend"}
}

source_allowed if {
	input.authority_facts.source_current
	input.authority_facts.artifact_admitted
}

consent_allowed if not input.authority_facts.consent.required

consent_allowed if {
	input.action in {"plan_read", "plan_field_append"}
	c := input.authority_facts.consent
	c.required
	c.valid
	c.grant_id == input.consent_id
	input.scope.recipient_id == input.actor.principal_id
	count(input.disclosure_grants) > 0
	every g in input.disclosure_grants {
		g.required
		g.valid
		g.recipient_id == input.scope.recipient_id
		g.subject_revision == input.versions.subject
		g.scope_digest != null
		g.subject_id == input.scope.subject_id
		g.session_id == input.scope.session_id
		g.purpose == input.scope.purpose
		g.grant_id != null
	}
	every field in input.scope.fields {
		field_covered(field)
	}
}

field_covered(field) if {
	some grant in input.disclosure_grants
	field in grant.fields
}

role_allowed if {
	input.action == "own_reports_read"
	input.actor.role in participants
}

directory_binding_allowed if {
	not input.action in {"directory_read", "directory_search", "directory_suspend"}
}

directory_binding_allowed if {
	input.action == "directory_search"
	every binding in input.directory_bindings {
		binding.artifact_digest in input.artifact_digests
	}
}

directory_binding_allowed if {
	input.action in {"directory_read", "directory_suspend"}
	count(input.directory_bindings) == 1
	binding := input.directory_bindings[0]
	binding.service_id == input.scope.recipient_id
	binding.revision == input.versions.directory
	binding.artifact_digest in input.artifact_digests
}

# IMP-05: actor-led synthetic referrals. These operations have a separate allow
# branch so legacy support-purpose rules cannot accidentally bypass their facts.
referral_actions := {"referral_sources", "referral_draft", "referral_read", "referral_context", "referral_review", "referral_dispatch", "dispatcher_send", "dispatch_authorize", "dispatch_consume", "dispatch_read", "receipt_read", "dispatch_reconcile", "dispatch_observe"}
referral_effect_actions := {"referral_draft", "referral_review", "referral_dispatch", "dispatcher_send", "dispatch_authorize", "dispatch_consume"}
referral_consent_actions := {"referral_review", "referral_dispatch", "dispatcher_send", "dispatch_authorize", "dispatch_consume"}
referral_review_actions := {"referral_dispatch", "dispatcher_send", "dispatch_authorize", "dispatch_consume"}
referral_status_actions := {"dispatch_read", "receipt_read", "dispatch_reconcile", "dispatch_observe"}

allow if {
	input.action in referral_actions
	input.tags == {"environment": "demo", "population": "synthetic"}
	input.actor.kind == "human"
	input.actor.workload_id == "spiffe://care-link.demo/demo/data"
	referral_assurance_allowed
	referral_role_allowed
	input.authority_complete
	input.audit_ready
	input.mode in {"normal", "ai_disabled"}
	input.scope.purpose == "referral"
	input.scope.session_id != null
	input.scope.subject_id != null
	f := input.authority_facts
	f.actor_role_allowed
	f.resource_owned_or_assigned
	f.field_scope_allowed
	f.jurisdiction_allowed
	f.workload_unfenced
	f.exception_id == null
	referral_source_allowed
	referral_consent_allowed
	referral_review_allowed
}

referral_assurance_allowed if {
	input.actor.role in workforce
	input.actor.assurance in {"AL2", "AL3"}
}

referral_assurance_allowed if {
	input.action == "referral_read"
	input.actor.role in participants
	input.actor.assurance in {"AL1", "AL2", "AL3"}
}

referral_role_allowed if input.actor.role in workforce

referral_role_allowed if {
	input.action == "referral_read"
	input.actor.role in participants
}

# Read/status projections must remain available for honest history and lost-reply
# reconciliation after consent/source changes. Current scope and disclosure facts
# above are still mandatory. These actions cannot send a new package.
referral_source_allowed if not input.action in referral_effect_actions

referral_source_allowed if {
	input.action in referral_effect_actions
	input.authority_facts.source_current
	input.authority_facts.artifact_admitted
	count(input.scope.fields) > 0
	input.scope.recipient_id != null
	count(input.directory_bindings) == 1
	binding := input.directory_bindings[0]
	binding.service_id == input.scope.recipient_id
	binding.revision == input.versions.directory
	binding.artifact_digest in input.artifact_digests
	binding.current
	not binding.suspended
}

referral_consent_allowed if {
	not input.action in referral_consent_actions
	not input.authority_facts.consent.required
}

referral_consent_allowed if {
	input.action in referral_consent_actions
	c := input.authority_facts.consent
	c.required
	c.valid
	c.grant_id != null
	c.grant_id == input.consent_id
	c.subject_revision == input.versions.subject
	c.scope_digest != null
	c.recipient_id == input.scope.recipient_id
	c.subject_id == input.scope.subject_id
	c.session_id == input.scope.session_id
	c.purpose == "referral"
	time.parse_rfc3339_ns(c.effective_at) <= time.now_ns()
	time.now_ns() < time.parse_rfc3339_ns(c.expires_at)
	time.parse_rfc3339_ns(c.expires_at) - time.parse_rfc3339_ns(c.effective_at) <= 900000000000
	every field in input.scope.fields {
		field in c.fields
	}
}

referral_review_allowed if {
	not input.action in referral_review_actions
	not input.authority_facts.review.required
}

referral_review_allowed if {
	input.action in referral_review_actions
	r := input.authority_facts.review
	r.required
	r.valid
	r.review_id != null
	r.review_id == input.review_id
	r.reviewer_id == input.actor.principal_id
	r.payload_digest != null
	r.payload_digest == input.referral_payload_digest
	time.now_ns() < time.parse_rfc3339_ns(r.expires_at)
	time.parse_rfc3339_ns(r.expires_at) - time.now_ns() <= 300000000000
}

# IMP-06: optional session-bound assistance; domain rechecks the profile and owner.
assistance_actions := {"task_create", "task_read", "task_cancel", "task_revise", "draft_read", "draft_review", "assistance_status", "assistance_task_context", "assistance_draft_context"}

role_allowed if {
	input.action in assistance_actions
	input.actor.role in (participants | workforce)
	input.scope.purpose == "support"
}

assistance_mode_allowed if {
	not input.action in {"task_create", "task_revise"}
}

assistance_mode_allowed if {
	input.action in {"task_create", "task_revise"}
	input.mode == "normal"
}
