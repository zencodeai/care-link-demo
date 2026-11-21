# IMP-08 CI follow-up handoff

PR15 head9fa9b25a1dd263c123735a9fd95c3c22e4be5913 had a failing Foundation push job44927973473 and a passing PR job44927980573. Failure: ManualService.test.tsx asserted an EventSource existed immediately after an async DOM projection; the subscription effect had not completed. Both container jobs passed.

The fixture now waits for actual stream creation and cleanup, and invokes the external stream update inside act. It still requires exactly one stream, liveness through ACK, immediate private-message removal on revoked authority, and eventual closure. No runtime code, roles, permissions, timeout budget or retry policy changed.

Local verification: all17 manual tests passed; the failed case passed five independent runs; the full223 frontend tests, type checks, lint and formatting passed. The offline evidence verifier supports selecting a current follow-up candidate and rejects copied historical manifest/results bindings. Positive and adverse binding checks passed. See [results](results.json), [source continuity](source-continuity.json) and [failed run](evidence/run-44927973473.json).

Exactly two source paths changed: the manual-service test and offline evidence verifier. The other898 source hashes,58 requirement/design references and3 build hashes match the original qualified candidate. Original G-08 qualification files and failed CI logs are preserved. Backend/database/browser behavior was not rerun because its executable source and build bytes are unchanged; original scoped evidence remains applicable.

The correction is for the existing feat/imp-08-operational-governance branch and [PR #15](https://github.com/zencodeai/care-link-demo/pull/15). Remote CI must be read from the corrected head; the archived original passing PR run is not a pass for a new commit. Human review remains deferred_until_after_IMP10. No merge, deployment, model/host change or IMP-09 activation.

Next chat: inspect current PR head/CI and this follow-up candidate, use the current-session evidence verifier, then follow only newly assigned scope. The pre-existing untracked research resources are excluded and untouched.
