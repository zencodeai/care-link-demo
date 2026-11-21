# Independent review and resolution

Configured imp_review ran two read-only passes; imp_python, imp_platform, imp_web and a bounded imp_controls pass implemented exclusive paths without nested delegation. Primary integrated contracts, role factories, broker custody, source tests, packaging and records. No specialist supplied human approval.

Resolved findings with regressions:

- A task revision could leave an earlier draft reviewable: drafts now bind task revision, task fence and current draft identity. Superseded accept/edit is denied; rejecting it cannot complete the new task.
- The first profile accepted mismatched goals/completion predicates: worker_summary permits prepare_summary/draft_ready only, including revisions.
- A status request returning401/403 could leave private facts visible: the UI latches them hidden; unsent correction text alone survives. Fresh task and draft context must be authorized again before private projections return.503 follows the same privacy failure path.
- Runtime trust was checked only on incoming commands: stored lease workload/certificate/generation/expiry is rechecked against live trust before context, compute admission/completion and proposal completion. Core also re-verifies the actual runtime before sending a long-call response. The regression fences runtime during generation while manual service continues.
- UUID-bearing lease paths did not fit exact mesh route matching: only four explicitly named templates admit canonical lowercase UUIDs, across Enforcer, BackendVerifier and generated ingress/egress. Traversal, queries, encoding, uppercase IDs, suffixes and unknown templates remain denied.
- Ten-second mesh route timeouts would interrupt valid thirty-second model calls: the three fixed generation paths now have forty-second transport bounds. Other internal routes keep ten seconds; native tokenizer bridge operations have their own ten-second bound.
- Source factories initially lacked the complete remote chain: fixed signed Core/Data, current stored context, data-only job ledger, role graph and factories are implemented. The host-only SDK tokenizer was moved behind its authenticated fixed bridge route; inference has no direct model/tokenizer SDK path. Token receipts bind actual artifact SHA, loaded ID, tokenizer/template/window and request content. Actual bindings are still unavailable and are not represented as verified.

The missing real loaded model/tokenizer/template and deployed network/latency evidence remains an explicit qualification limitation, not a fabricated source success or a deferred-human-review gate. Existing model-file bytes and name alone do not establish admission. Human observations remain deferred_until_after_IMP10.
