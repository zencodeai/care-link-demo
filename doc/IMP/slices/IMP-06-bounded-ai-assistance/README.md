# IMP-06 — Bounded AI assistance

**G-06 is automated-qualified for the isolated synthetic worker-summary profile as of November 21, 2026.** [Closure evidence](sessions/007-g06-automated-closure/README.md), [execution ledger](../../executions/2026-11-20-IMP-06/ledger.json).

## Initial implementation evidence

User assignment: “Implement service slice 06.” Canonical stage IMP-06 / gate G-06 / tasks A–D remain in implementation-plan.json. Dependency G-05 is automated_qualified. Clean starting commit `d0a2e188363e7fa136c920f02033cac52edf91ba`; current local branch `feat/imp-06-bounded-ai-assistance`, uncommitted changes.

Delivered encrypted durable tasks, bounded counters/leases/fences, typed tools, current-source context, signed actor/runtime separation, optional EN/FR exact unsent draft review, fixed inference/host tokenizer bridge and durable timeout-safe compute slots. First profile is worker_summary / prepare_summary / draft_ready; all actual model admissions remain disabled. Other functions are explicitly unadmitted. See [scope/deltas](sessions/001-implementation/implementation-deltas.md).

Broad source38 checks passed (1,332 Python tests,3 explicitly gated legacy skips). Final bound affected lane11 checks passed (139 Python regressions,180 web/contract tests),9 final Chromium cases passed, both source images built/smoked, and197 packaged hashes matched. These are source/synthetic qualification results. Required live selected-model, tokenizer/template, function quality and deployed AI isolation/latency checks remain unperformed, so G-06 stays blocked. Human review is deferred_until_after_IMP10.

Code ownership is modular in apps/web, services/core/data/runtime/inference, host/inference-bridge, shared contracts/policy/workload trust and tools/imp06_runtime. This chat uses [session001](sessions/001-implementation/README.md). Future follow-ups need their own chat/session. No live deployment, host-trust change, model load, SDK install, commit, push or publication occurred; only owned temporary test resources were cleaned up. No police integration, autonomous emergency contact or real-data use was added.

## Qwen documentation follow-through · 2026-11-20

The user subsequently selected Qwen3.8-27B on this laptop through LM Studio and requested the assessment/integration plan be documented. [Current model direction and plan](../../../decisions/2026-11-20-qwen-lm-studio-integration.md) supersede the earlier model selection only. [Session002 documentation handoff](sessions/002-qwen-integration-documentation/handoff.md) records this update. Session001 source/results/candidate remain the historical Gemma-pinned baseline; no new model/framework code or qualification is claimed.

## Agentic workflow and clinical knowledge implementation · 2026-11-20

[Session003 handoff](sessions/003-agentic-workflows-rag/handoff.md), [candidate](sessions/003-agentic-workflows-rag/candidate-manifest.json) and [results](sessions/003-agentic-workflows-rag/results.json) record the explicitly authorized continuation. Current source includes bounded LangGraph dispatch/execution, exact Qwen nonthinking token binding, account/session-bound optional worker preparation, six-role knowledge lookup, professionally restricted clinical references and catalog/source/release freshness controls. Current pins/defaults/fixtures migrate to Qwen; historical session001/002 evidence remains historical.

Final source lane38 commands passed:1,441 Python tests,3 gated legacy skips,193 web/contract tests;11 Chromium cases and4 actual EN/FR clinical-reference/injection cases passed. Two local images passed smoke/packaging checks with196 source/config/web hashes matched. Source stayed identical across the final lane. This is not deployed or clinical qualification; AI admission stays disabled and G-06 remains unqualified for the [remaining obligations](sessions/003-agentic-workflows-rag/remaining-qualification.md). No live deployment, server/model settings change, model load/unload, commit or push occurred. Owned temporary test resources were removed.

## Authenticated runtime qualification

Session004 verified loopback LM Studio authentication on REST and SDK discovery, pinned the authenticated SDK and passed all four Qwen cases with exact prompt-token agreement. The isolated candidate image passed package integrity and Runtime-to-Core mTLS, Unix peer credential and same-connection revocation checks. G-06 remains blocked pending qualification of the complete role topology, authenticated provider stop and recovery, and verified release custody. Every AI function remains disabled. [Session evidence and handoff](sessions/004-authenticated-qualification/README.md).

## Deployment and release follow-up

Session005 implemented signed release custody and verified provider stop recovery. The rebuilt candidate passed the disposable five-role SPIRE and Envoy mesh, SVID rotation and live revocation. Separately, the authenticated laptop Qwen bridge passed signed-release disablement and all ten bounded load cases. The observed input limit is 2,048 worker-summary prompt tokens. The real Data and laptop provider journey still needs combined deployment and lifecycle qualification. Existing demo serving remains disabled. [Session evidence and handoff](sessions/005-deployment-release-qualification/README.md).

## Enabled isolated AI demo

Session006 ran the selected isolated worker-summary demo with signed qualification authority, the authenticated Qwen model and TLS PostgreSQL. It produced and rejected an encrypted unsent draft and preserved manual access after disablement. The packaged launcher and serving CLI preserve exact-bundle approval and five-role custody. G-06 remains open pending the combined provisioned mesh and observed real-provider lifecycle recovery. [Session evidence and handoff](sessions/006-enabled-ai-qualification/README.md).

## Automated closure

Session007 passed the matched actor-only and live assisted worker cases, durable timeout containment during active provider work, and protected live tokenizer and generation traffic. G-06 covers the first worker profile and the isolated synthetic candidate. Product serving needs its own exact release and current authority. [Automated qualification packet](sessions/007-g06-automated-closure/demo-packet.json).

IMP-06 is closed for the isolated synthetic worker-summary scope and published for review against `main`. [PR #13](https://github.com/zencodeai/care-link-demo/pull/13), [publication handoff](sessions/008-closure-and-pr/README.md).
