# Independent review and corrections

The configured read-only `imp_review` specialist inspected the integrated source. Its final re-review reported no remaining concrete defects. The primary also integrated independent `imp_verifier` findings and actual PostgreSQL evidence; this is engineering review, not human G-04 acceptance.

| Finding | Correction and evidence |
| --- | --- |
| Expiry during decryption could outlive the initial share check | Final guarded output authorization checks every selected field after content work/audit. Ten independent database adverse tests include full expiry and a narrower surviving grant. |
| Suspension key omitted service path | The service ID now participates in the logical payload digest; a cross-service replay conflicts. |
| Generic PDP scope omitted fields/recipients/consent/source references | Typed target discovery and `planning_policy` produce current exact bindings. Core forwards them; final lock validation recomputes full input equality. Real OPA tests deny changed fields, recipient, subject, grant and source revision/artifact. |
| Raw source-admission boolean lacked signature verification | `VerifiedDirectoryAdmission` verifies closed canonical envelopes with independently supplied Ed25519 keys; 18 focused tests cover mutation, wrong/missing keys, authority scope and detached copies. |
| Saved carer reports disappeared after acknowledgement/reload | Narrow current author-owned report transport and UI refresh/rendering added; tests cover save/reload, lost acknowledgement, account changes and denied access. |
| Authored fields could exceed a narrowed grant | Shared plan output is strictly filtered by current fields. Historical authorship adds no share authority; own reports use their separate endpoint. |
| Append returned more fields than its PDP scope named | Append policy now binds the full permitted response plus the new field. Final checks also reject emitted fields outside evaluated scope. |
| Retrying plan creation after later edits lost its policy disclosure scope | Signed metadata includes the original logical operation ID. Replay resolves that operation's plan and original session anchor, then binds the current permitted fields. The real signed gateway regression includes later edits and a second support session. |

Early verification failures were corrected rather than credited as passes: a noncanonical test value, retirement clock microsecond drift, a race expectation that did not allow stale-authority rejection, a duplicate test principal and an invalid test reason. The standalone-validator CSP test now permits Ajv's pinned static equality helper required by the new schemas; string code generation remains disabled and no `eval`/`Function` use is accepted.

Follow-up self-consent proof uses a separately named MFA ceremony because the accepted grant DTO already includes that purpose. This activates no future follow-up behavior. Source and policy signatures establish integrity only. Live deployment, browser/mesh qualification and human review are explicitly outstanding.
