# IMP-06 agentic workflow handoff

**Architecture/design/resources/source implemented and verified; G-06 remains unqualified and admission disabled.** User authority: architecture, design, gather frameworks/resources, update documentation and implement. Work stayed within this explicit IMP-06 continuation; no next slice, live deployment, server/model settings change, model load/unload, commit or push occurred.

Baseline is `d0a2e188363e7fa136c920f02033cac52edf91ba` on `feat/imp-06-bounded-ai-assistance`, with existing dirty IMP-06 source preserved. [Candidate](candidate-manifest.json) binds779 current source files and93 intentional changes/additions since this session's baseline; no baseline file was removed and24 project configuration files remain byte-identical. Historical session001/002 receipts retain their point-in-time meaning.

## Delivered behavior

- Runtime performs the real bounded LangGraph lease→inference→proposal graph through authenticated broker ports. Core has bounded metadata dispatch; Data retains durable counters, leases, fences, source context and review authority. No model/client/store path is given to Runtime.
- The worker can request preparation or opt in within an account/session-bound workspace. Read-only polling is bounded; unknown commands preserve idempotency identity. Manual service and exact accept/edit/reject remain separate from AI and business effects.
- PID, carer, professional participant, worker, receiver and supervisor receive role/locale-filtered patient-independent knowledge lookup. Worker task retrieval uses current permitted assertions plus applicable pinned catalog entries. Other role task profiles are not implemented/admitted by this lookup.
- A closed immutable catalog filters before lexical ranking. Exact catalog/source/release identity, expiry, synthetic-region binding and pending-review freshness are enforced. Existing tasks resolve pinned references; only explicit revision repins evidence.
- Qwen returns compact evidence indices. Trusted gateway code constructs current task bindings, source references and exact text, enforces all patient assertions and validates canonical Proposal. More than12 mandatory assertions fails before tokenizer/provider work. Native effects, duplicate/out-of-scope selections and added factual prose are rejected.
- Current source/contracts/defaults/fixtures target `qwen/qwen3.8-27b`. Host binding hashes weights/metadata, checks the already-loaded instance, renders the actual nonthinking template through a pinned SDK RPC seam, tokenizes it and requires provider prompt-count equality.
- LangGraph1.2.24 and LM Studio SDK1.5.0 are locked and installed in the project environment. Official Ontario Health, HL7, OWASP and NIST snapshots/metadata were gathered. Runtime contains eight bilingual synthetic workflow entries and two professionally restricted reference-only Ontario Health paraphrases; integrity is not clinical approval.

[Architecture](../../../../../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md), [LLD18](../../../../../LLD/18-agentic-knowledge-workflows.md), [resource provenance](../../../../../../config/demo/knowledge/reference-sources.json), [results](results.json).

## Actual verification

- Final [source lane](evidence/source/attempt003/checks.json):38 commands passed with identical before/after source hashes. **1,441 Python tests passed**, three explicitly gated legacy fixture tests skipped; **193 web/contract tests passed**. Strict types, lint/format, generated-contract/OpenAPI parity, dependency boundaries, builds and plan checks passed. Third-party deprecation warnings were retained.
- [Real Chromium](evidence/browser/playwright-results.json): **11 passed**, including EN/FR, keyboard/focus, axe/reflow, account-bound opt-in, knowledge attribution, stale/unknown/cancel/auth privacy and manual continuity. API/provider responses were synthetic fixtures; this is not deployed authority proof.
- [Actual local Qwen](evidence/model/attempt009-final-clinical-reference-passed.json): **4/4 EN/FR baseline/injection cases passed** using exact catalog clinical references and fictional adult reports. Observed generation1.41–3.83seconds; zero reasoning tokens; actual rendered/SDK/provider prompt counts matched; canonical projection/grounding passed. Artifact/source/catalog hashes are current. This is narrow preadmission technical evidence, not clinical or load-scale qualification.
- [Packaging](evidence/packaging/checks.json): two images built and passed nonroot/read-only/network-none smoke. All196 selected source/configuration/web hashes matched the final qualification image. Minimal Core excludes Runtime, LM Studio SDK, Data and database-driver packages. These checks do not establish deployed mesh isolation.
- Full canonical design validator passed391 types,206 operations,799 fixtures and78 storage records. The two additive transport endpoints have separately generated/validated OpenAPI. Planning and document inventory checks passed.
- Read-only HLD/LLD reviews found/fixed catalog activation drift, missing catalog-release binding, multiline source compatibility and stale model wording. [Review record](review-findings.json). Reviews are not human or clinical approval.

Earlier failed attempts remain evidence: model unavailable after idle unload; MLX grammar rejected generic schema constructs; default thinking yielded empty final content; an irrelevant-reference fixture expected unnecessary evidence; and HTTPX2 introduced a test-relay type mismatch. The final constrained selection/rendering adapter and relay correction passed the cited checks. No failed run was relabelled passed.

## Remaining release boundary

[Remaining qualification](remaining-qualification.md) identifies current obligations: enforced LM Studio authentication/authenticated tokenizer compatibility, trusted release/model origin/license/engine and catalog/schema/prompt/build binding, actual deployed workload/network/revocation/timeout/recovery evidence, workload-scale performance, and separately admitted role workflows. SDK1.5.0's tested direct client does not supply the REST API token; the host bridge's own authentication does not prove server authentication. Local bytes/alias mapping are verified; no publisher signature or engine attestation is claimed.

All checked-in AI functions remain disabled and G-06 remains blocked/unqualified. Human usability/screen-reader/clinical/language and usefulness review are distinct; specified implementation human review remains deferred_until_after_IMP10 under the existing policy. Synthetic-only, no police integration and no autonomous emergency contact remain enforced scope.

Only this session's labelled PostgreSQL/browser fixtures and temporary DB credentials were removed. Existing demos and the user's loaded LM Studio model were preserved; built images remain local for review. [Cleanup](evidence/cleanup.json).

Next scoped work should read this handoff, reconcile the candidate hashes, and resolve the remaining deployment/authenticated-tokenizer/release qualification before admission. Do not repeat completed source/model tests unless changed inputs or new failures justify it; do not infer activation from this handoff.
