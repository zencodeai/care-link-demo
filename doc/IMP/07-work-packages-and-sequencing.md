# Work packets, sequencing and parallel execution

The [plan](implementation-plan.json) contains eleven stages and four bounded initial work items per stage: specification, implementation slice, actor/operator surface, and integrated verification/demo. They are a first decomposition, not fixed-duration estimates. Before execution, expand an oversized item into reviewable tasks with exact operation IDs, data/authority changes and relevant adverse tests. No estimates are invented without host/team measurements.

Use WorkPacket schema and the [IMP-00 example](examples/imp-00-work-packet.json). A packet is ready only with a concrete goal, input revisions, allowed paths/actions, dependencies, reviewer, validation/demo results expected and safe stopping conditions. A role name is not a work authorization. Dependencies include accepted stage gates as well as code prerequisites; the machine DAG alone does not carry a human decision.

## Critical path and parallel candidates

IMP-00→01→02→03→04→05 establishes a usable protected manual/referral baseline. After05, optional AI06 and follow-up/rights07 may progress independently with disjoint assignments. Operational governance08 builds on 03/05 while its inline enforcement foundations already exist. Recovery09 requires07/08. Integrated acceptance10 requires06/07/08/09. Exact runtime test/shared-host resources are serialized even when coding is parallel.

Specification precedes parallel backend and UI work. UI can develop against contract fakes in a clearly labelled developer harness, but integrated gate requires real authorized services and cannot accept fake auth/audit or receipt success. The verifier designs cases early and validates the integrated candidate after both sides are ready. Coordinator resolves shared contracts, lockfiles and migration order before parallel edits.

Task paths are planned ownership candidates, not permission to write outside a work packet. Shared contract roots and locks have one owner. On conflict, stop overlapping edits and report; do not overwrite another writer or reset user changes. Use isolated worktrees only when helpful and authorized, with explicit branch/base/file/resource identity. No branch/PR creation follows automatically from an agent packet.

## End-to-end reference work packet

A referral-dispatch packet cites TR-WF-07/TR-SEC-03/TR-GOV-08, named referral/dispatch operations and LLD06. It owns only referral application/data-adapter tests and listed implementation paths. It specifies the final guard/audit authorization, stable dispatch/child operation identity, immutable payload and simulator receipt contracts. Expected negative results include revoke before boundary, changed directory/review, lost receiver reply and different payload under the same key. The UI packet separately owns exact review and unknown/partial status rendering. The verifier joins them in separate actor profiles and a deterministic crash barrier. Nobody expands the simulator into a real connector.

## Replanning and blocked work

Classify a blocker: missing user decision, unavailable resource/tool, product capability mismatch, source/design conflict or actual defect. Give evidence, affected capability, concrete options/recommendation and independent work that remains possible. Preserve accepted workstation/model choice; an incompatible resource result proposes a scoped adjustment rather than silently substituting another host/model. A design amendment records old/new semantics and required approval/testing, then updates affected packets/hashes. A false pass or removed adverse test is not a resolution.

Keep a small current queue: next ready stage, active bounded work, review findings and human decisions. Do not pre-spawn idle agents for every future package or create dozens of status documents duplicating the canonical plan. Stage cards, actual evidence manifests and exact work packets are sufficient.
