# Automated qualification and deferred human review

## Current policy and scope

Effective 2026-11-20, the user directed implementation to proceed using automated tests only through completion of IMP-10. Interactive human review and human stage-acceptance receipts are no longer prerequisites for implementation progression. Human review belongs to later bug-fix/improvement sessions using GitHub issue follow-up after IMP-10 is complete. This supersedes earlier per-stage human-gate instructions, including the pending G-04 review sequence. Stop requesting its remaining actor observations or a G-04 human acceptance decision.

The gate IDs G-00…G-10 continue to identify the same bounded technical scopes and normal/adverse outcomes. They now identify automated implementation qualification checkpoints. Their existing human-review prompts remain deferred review agendas, not active progression guards. Historical human results, failures and actual acceptance decisions retain their original candidate and scope; preserve them without rewriting history or generating replacement human receipts.

## Candidate and evidence

Prepare the actual candidate, exact automated scenarios, evidence and rollback before recording qualification. Bind source commit and dirty-diff digest, artifact/configuration/contract/fixture/environment digests, preconditions, expected and actual outcomes, check commands, evidence locators/digests and residual findings. Direct API, DB, race, network and browser assertions must establish the claimed behavior and prohibited-effect absence. A screenshot, scanner badge or count of passing tests is insufficient by itself.

Continue using WorkPacket, AgentResult, CheckResult and DemoPacket for their applicable purposes. The historical DemoPacket name does not require an interactive demonstration: its normal/adverse steps may be executed by an automated harness. Leave `human_decision_id` null unless an actual human decision exists. Record `automated_qualified` in the execution ledger, separate from historical `accepted` or a HumanDecision record. Record unperformed human review as `deferred_until_after_IMP10`, never passed or implicitly accepted. Automated accessibility checks cannot claim human screen-reader, visual or language approval.

## Implementation qualification procedure

1. Confirm the current scoped authorization, ready WorkPackets, candidate and dependency bindings. Dependencies may use current automated qualification or still-valid historical accepted evidence. Do not replay stale private evidence or use a test flag to bypass runtime authority.
2. Execute applicable automated normal and adverse cases for the declared stage: unit, contract, real DB/integration, browser, EN/FR/accessibility/layout, direct API/security, race, recovery, model and performance checks as relevant. Distinguish actual services from explicit test doubles and simulations.
3. Verify returned behavior and durable state, including absence of prohibited bytes/effects. Preserve failures, missingness, timeouts, environment limits and the exact tested scope.
4. Resolve blocking defects and rerun materially affected checks. A failed or unrun mandatory automated check prevents qualification. A deferred human-only review does not. Preserve evidence of earlier failures and record their resolution.
5. The coordinator records `automated_qualified` only when the required automated evidence is current and passing and blocking findings are resolved. Do not ask for per-step interactive observations or a human stage-acceptance response. Continue dependent work only within existing user authorization; do not auto-start a new slice/chat or infer deployment, commit or merge permission.
6. On a material source, contract, policy or environment change, invalidate affected automated qualification and repeat the relevant checks. On completing IMP-10, retain the integrated automated qualification packet and the deferred human-review inventory for GitHub issue follow-up.

The [machine workflow](stage-workflow.json) defines active progression. Previously `ready_for_demo` or `awaiting_human` work returns to evidence reconciliation under this policy; it does not become qualified automatically. Historical accepted records remain historical. This workflow update itself does not close an implementation checkpoint or assert that its automated checks passed.

## Human review after IMP-10: GitHub issue follow-up

After implementation through IMP-10 is automated-qualified, handle each human-reported bug or improvement through the GitHub issue follow-up functionality. Human review is scoped to the issue and the integrated application, rather than restarting every earlier implementation-stage gate.

- Bind the actual repository and issue URL/number, issue scope, affected stage/candidate and a dedicated follow-up chat/session folder under the owning slice. A cross-slice issue names one integration owner and explicit write ownership.
- Capture expected and actual behavior, reproducible steps, affected actor/language/browser/assistive technology, severity, synthetic evidence, acceptance criteria and relevant earlier test/result references. Deferred human checks may identify usability, screen-reader, visual, language or workflow improvements without claiming they previously passed.
- Reproduce and diagnose the issue, make the scoped fix, add meaningful automated regression coverage, and run affected checks. Preserve deterministic authorization, consent, audit, isolation and recovery controls.
- Use the issue follow-up session to request focused human observations when needed. Record the actual reply and tested candidate. Track remaining findings and follow-up work; do not infer a human pass or issue resolution from agent output or test counts.
- Attach or link the permitted patch and test evidence through the authorized GitHub follow-up flow. Issue creation, comments, closure, commit/push, PR and merge actions require their applicable session authorization; this policy update does not perform those actions or invent a GitHub automation trigger.
- If GitHub access or the follow-up capability is unavailable, retain an issue-ready local handoff and report the limitation. Do not fabricate an issue URL, successful follow-up or review result.

## Authority and evidence limits

Product-runtime human consent, MFA, worker connection/acknowledgement, independent authority and exact serving-promotion approvals remain enforced. Automate synthetic scenarios without disabling those controls, and report simulated human actions honestly. Separate necessary installation, deployment, host/SSL trust, destructive-action and publication approvals from implementation qualification. Previously approved actions remain approved within their recorded scope.

All stories/person data remain synthetic; account metadata and keys remain protected. Automated qualification and later issue review establish only the declared engineering scope, not clinical efficacy, real-partner/channel capability, independent release approval or production readiness. Preserve no-police-integration and absent autonomous emergency-contact constraints.
