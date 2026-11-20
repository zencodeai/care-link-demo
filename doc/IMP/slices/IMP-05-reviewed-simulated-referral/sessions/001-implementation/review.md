# Integrated review and corrections

Focused specialists ran under the shared maximum of three concurrent threads: imp_scope (read-only), imp_python (data/receiver implementation and scoped transport verification), imp_web (actor UI/browser checks), imp_controls (new versioned policy and OPA tests) and imp_review (read-only integration). The coordinator owns shared contracts, Core, technical mapping/transport, runtime composition, integration, evidence and handoff. No nested delegation ran. Exact paths and later ownership transfers are recorded in the session packets and implementation decisions.

Resolved findings:

- Own PID draft reads now permit exact current subject scope, enabling client consent; dispatch/receipt metadata remains workforce scoped.
- Sender checks source-field sharing, consent and review intervals again after canonical audit before authorization/attempt/output can commit. Deterministic expiry tests cover these boundaries.
- Receiver performs current role/service/identity/browser/deadline checks before private output, replay and the final transaction commit, plus the final response boundary. A delayed final-write test proves expiry rolls back the decision.
- Exact signed receiver-audience envelopes bind action/key/path/body/current identity. Workload routes separate Core humans from Data sends. Identity resolve/current access is opt-in and narrowly enabled for receiver in both ordinary and review-origin composition; consent-proof/recovery are denied.
- Receipt shape plus semantic binding is checked: accepted requires all fields; partial requires a proper nonempty subset; no accepted fields on transport-only/refused/clarification outcomes. Malformed/mismatched post-send evidence records unknown, with a safe observation, and never infers connection.
- Receipt observations are append-only; stale received observations cannot erase known receiver decisions. Repeated logical IDs deduplicate; changed bodies/keys/digests reject rather than create a new effect.
- Both sender and receiver copies have explicit encrypted custody and pending purpose/parent/delivery anchors. Unknown delivery cannot inherit session-only cleanup.
- Signed mappings reject empty hosts, arbitrary source-derived routing, unsupported shapes, duplicate IDs and tampered targets. Runtime composition remains explicit opt-in, and credential boundaries remain separate.

Integrated test-harness correction: full pytest initially registered the same fixed receiver database fixture through two collected modules. Moved that fixture to the canonical data conftest, preserving one session owner. Attempt001 retains the failure; attempt002 retains an import/lint correction; the final source attempt records the reconciled candidate. Browser attempt001 separately retains a French locator timeout after the label switched to Langue; corrected harness selectors and retained the rerun. Neither failure is relabelled as a passing observation.

Deferred scope is explicit in implementation-deltas.md: human review after IMP-10; no automatic retry or scheduler; no deployed HTTPS/MFA/native zoom claim; coordinated rights/cleanup remains IMP-08. No product authority control was waived to pass checks.

Plan validation found an existing archive-resolution limitation: the frozen validator resolves moved Markdown links from their current folders. The compatibility runner preserves its exact bytes, schema, DAG and frozen-input checks, then resolves historical links only through existing verified SHA256 relocation manifests. Regression evidence proves active missing links and changed archived bytes still fail. The raw failure is retained in source attempt003. The first qualification image build also retained its missing-context failure; an explicit per-Dockerfile source allowlist corrected packaging without widening the restricted Core context.

The final read-only imp_review pass confirmed the identity composition flag, final receiver precommit check and retention anchors; no remaining blockers were found. The compatibility planning check passed with exact original validator bytes. The execution-status README was subsequently updated with its previous/new digest retained in planning-inventory.json execution_updates; frozen REQ/HLD/LLD inputs remain unchanged.
