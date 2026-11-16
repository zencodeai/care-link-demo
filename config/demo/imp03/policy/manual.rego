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
    input.actor.role in participants | workforce
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
    input.tags == {"environment": "demo", "population": "synthetic"}
    input.actor.kind == "human"
    input.actor.workload_id == "spiffe://care-link.demo/demo/data"
    input.authority_complete
    input.audit_ready
    mode_allowed
    role_allowed
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
    input.scope.purpose in {"support", "service_operations"}
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
