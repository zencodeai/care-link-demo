# IMP-03 — review, recovery and demo-toolkit design

2026-11-15. **Proposed design and implementation plan only.** The user requests investigation of unstable/confusing review UI, repeatable fresh sequences in ordinary tabs of one browser, and a durable reference toolkit for state/credentials. No implementation, provisioning, credential change, deployment or acceptance is performed.

Read [review and design](review-and-design.md), then [implementation plan](implementation-plan.md). [Work packet](work-packet.json) binds source inputs and the documentation-only scope.

Key proposal: one registered HTTPS hostname per actor slot, one authoritative session/workspace model, recoverable server-held drafts/operations, and a versioned operator CLI managing environment/run/attempt state outside browser storage. The same browser/profile can repeat fresh runs with no cookie/cache clearing.

Source baseline: `caf3ddea7c8b4057d84f56632be1c0031e8ddecb`, with existing uncommitted IMP-03 work preserved. The source/input hashes in the work packet describe what was inspected; HEAD alone does not bind that work.

The primary is sole document writer. Scoped imp_controls and imp_platform agents returned read-only source findings; imp_review completed the integrated read-only review; its three clarifications are incorporated into the design/plan. Product/browser/runtime tests were not run. Documentation schema, reference and formatting checks are recorded in the plan's validation note.

Historical qualification remains [session003](../003-live-qualification/README.md), with its [current assessment](../003-live-qualification/qualification-status.md) and frozen archive. Its deployment-profile acceptance remains scoped; G-03 is still incomplete. The proposal changes neither canonical HLD/IMP planning nor the deleted LLD. No new human approval is inferred.
