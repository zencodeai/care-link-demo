# Demonstrability and human-in-the-loop decisions

## A reviewable candidate before asking

Every gate G-00…G-10 corresponds to a self-contained stage. Coordinator prepares the actual candidate, setup, exact scripts, evidence and rollback before requesting acceptance. The human sees useful behavior and critical failure outcomes, not a plan to show them later. A reviewer need not infer internal security from a screenshot: connect actor-visible results to direct API/race/DB/network evidence. A recording supports review but does not prove the current candidate or replace an interactive demonstration where needed.

DemoPacket binds stage/gate, source commit and dirty-diff digest (or clean commit), artifact/config/contract/fixture/environment digests, steps/expected observations, preconditions, actual automated results, evidence paths/digests, residuals, proposed acceptance scope and rollback. Preserve useful client/worker workflows while injecting the exact failures the stage claims to handle. Use separate role browser profiles and real authenticated channels for connection claims. All stories/person data are synthetic; actual account metadata and keys remain protected.

Human decision binds the exact DemoPacket digest and candidate/environment. Allowed decisions: accept_stage, request_changes, defer, reject. The decision records actual human attribution and authority/scope, evidence reviewed, constraints and timestamp. No timeout, preselected UI choice, agent output or second account for the same human can create acceptance. A stage decision is not necessarily independent release/clinical review; where independence is required, the corresponding real identities/roles must exist. Do not infer them from the role catalogue.

## Procedure

1. Confirm dependencies and prior accepted gate bindings still match; validate candidate and relevant tests. Do not replay stale private results or use a staging flag to bypass current authority.
2. Run the normal actor/operator scenario. Explain simulated versus actual observations, incomplete features, unknown wait/connection and non-clinical status.
3. Run the named adverse cases and show both expected denial/absence and durable actual state. A denial log alone is insufficient if prohibited bytes/effects were still delivered.
4. Show reproducibility, rollback and current limitations. Summarize failures/missing evidence without hiding them behind coverage counts.
5. Present the concrete decision: accept the stated stage scope, request specified rework, defer or reject. Explain any actual authorization needed for installation/deployment separately from design/stage acceptance.
6. Record the user's actual response and its scope. If absent, leave awaiting_human. If material candidate/contracts/policy/environment changes, mark previous acceptance stale for affected behavior and re-demonstrate relevant cases; do not silently extend approval.

All stages currently have empty evidence and no acceptance. [Examples](examples/) are explicitly unexecuted. A machine-readable receipt is a record of a real human action, not proof that someone acted merely because JSON validates. No cryptographic signing system is introduced for development stage notes; existing runtime artifact/promotion signatures and independent authorities remain separate.

## What each gate protects

G-00 accepts observed planning decisions and scoped setup proposal. G-01 accepts the developer foundation. G-02 protects identity/network/fallback boundaries. G-03 protects manual service, audit and exclusive human control. G-04 protects field privacy/consent and source truth. G-05 protects dispatch/uncertainty. G-06 protects actual AI usefulness/admission and fallback. G-07 protects lifecycle/rights truth. G-08 protects live authority changes and evidence access. G-09 protects recovery serving. G-10 accepts a specifically bounded synthetic demonstrator.

Stage acceptance may permit authorized dependent coding but does not automatically mutate the live workstation or promote a restored target. Each actual restore serving promotion retains the LLD's distinct exact human approval. Human review of implementation/config PRs remains required; agents cannot merge their own changes as human approval.

## Concise decision template

```text
Stage / gate:
Candidate source + diff/artifact/environment binding:
Demo packet digest:
Observed normal behavior and adverse cases:
Tests/evidence reviewed; failures or missing observations:
Accepted scope / limitations / remaining obligations:
Rollback and last-known-good status:
Actual human response, attribution and time: [pending until received]
Action authorized by this response: [explicit scope only]
```

Prefer one meaningful decision per integrated stage, not approval requests after every reversible edit. If independent work is already authorized, continue it while a different gate awaits a human; never cross an unaccepted dependent authority boundary to keep a schedule.

Development-stage candidate/environment digests bind review-relevant source, artifact versions/configuration, fixtures and declared capabilities, not every transient session timestamp. Recheck only materially affected behavior on change. Actual serving promotion remains stricter: its approval binds the LLD current live target/head/generation, and changes invalidate that particular promotion receipt. A stage review cannot replace it.
