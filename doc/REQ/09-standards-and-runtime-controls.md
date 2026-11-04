# Standards baseline for security and realtime governance

Research date: 2026-11-04. Status: proposed tailored baseline, not certification, legal advice or evidence of implementation. Sources below are official publisher/project resources. Public ISO descriptions were consulted; the licensed ISO text was not reviewed, so no clause-level ISO conformity is asserted.

## Recommended foundation

Use **OWASP ASVS for verifiable application security**, **OWASP AI risk lists and MITRE ATLAS for AI threat scenarios**, **NIST AI RMF for AI risk governance**, and **NIST Zero Trust plus OpenID SSF/CAEP for continuous authorization patterns**. ISO/IEC 42001 informs organizational accountability. OSCAL is optional evidence interchange, not a required new compliance platform. These resources are complementary; no single one specifies a complete realtime AI governance engine or the project's millisecond targets.

| Reference and primary source | Kind / baseline | Application and limitation |
|---|---|---|
| [OWASP ASVS](https://asvs.owasp.org/) | Application verification standard; select 5.0.0 as initial pinned baseline | Tailor applicable Level 2 controls for authentication, sessions, access, validation, APIs, cryptography and logging. Identify additional high-assurance controls based on threat impact. This is a verification target, not an ASVS Level 2 pass claim. |
| [OWASP LLM Top 10, 2025](https://genai.owasp.org/llm-top-10/) | AI application risk taxonomy; deliberate 2025 reference baseline | Covers injection, disclosure, supply chain, poisoning, output handling, agency, prompt leakage, embedding risks, misinformation and consumption. A Top 10 list is not a complete test standard. |
| [OWASP official GenAI LLM repository](https://github.com/GenAI-Security-Project/GenAI-LLM-Top10) and [Agentic Applications publication](https://genai.owasp.org/download/52117/) | Versioned evolving AI guidance, including agent-specific risks | Review agent tool misuse, identity/privilege abuse, memory poisoning, unsafe execution, trust exploitation and cascading failure. The official repository also points to a 2026 LLM edition while the public risks page shows 2025: record and review edition changes before choosing a successor, never mix identifiers across editions. Pin the agentic document title/edition/digest before formal category mapping. |
| [MITRE ATLAS](https://atlas.mitre.org/) and [official ATLAS data](https://github.com/mitre-atlas/atlas-data) | Living adversary tactics/techniques and case-study knowledge base | Build adversarial chains and expected denied effects. Pin data revision and resolve exact technique IDs from that revision. ATLAS is not a certification or a policy engine; do not claim every technique applies. |
| [NIST AI RMF 1.0 core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) | Voluntary AI risk-management framework: GOVERN/MAP/MEASURE/MANAGE | Risk ownership, operating context, evaluation, monitoring and incident response. It does not provide clinical authorization, executable rules or a mandatory realtime SLA. |
| [ISO/IEC 42001:2023](https://www.iso.org/standard/42001) | AI management-system standard | Organizational responsibilities, lifecycle management and improvement. Public overview supports selection only; licensed clause review and organizational assessment would be required for conformity/certification claims. |
| [NIST SP 800-207](https://nvlpubs.nist.gov/nistpubs/specialpublications/NIST.SP.800-207.pdf) | Zero Trust architectural guidance | Policy engine, policy administrator and PEP separation, current-context access decisions and continuous evaluation. Apply to humans and workloads; it is not an AI ethics ruleset. |
| [OpenID SSF 1.0](https://openid.net/specs/openid-sharedsignals-framework-1_0-final.html) and [CAEP 1.0](https://openid.net/specs/openid-caep-1_0-final.html) | Final interoperability specifications | Authenticated event exchange for session/credential/assurance changes. CAEP attenuates access through receiving enforcement; events alone do not enforce consent, governance or ethical rules. Local policy activation/consent events need explicitly separate schemas. |
| [NIST OSCAL](https://pages.nist.gov/OSCAL/) | Machine-readable control and assessment information | Optional future export of control/evidence mappings. OSCAL does not execute authorization policy. Keep the initial local mapping small and consumed by tests/release checks; do not build a separate conformance framework without a consumer. |

These sources support the reference descriptions. Selection, mappings, runtime limits and architecture below are CARE-Link design proposals, not requirements quoted from those publications. No external certification is required merely to demonstrate a synthetic workflow; all applicable project security acceptance remains required.

## Runtime control loop

1. Validate identity and structured request at the boundary.
2. Retrieve current authoritative policy epoch, roles/assurance, resource ownership, consent and relevant artifact/source state.
3. Evaluate deterministic policy; deny unknown/stale inputs and require all obligations.
4. Bind authorization to exact action/payload/revisions and commit audit before effect.
5. Revalidate at irreversible execution boundary and fence stale queued/streamed work.
6. Consume authenticated change/security signals, revoke or restrict scope, and reconcile missed events against authoritative state.
7. Measure drift/latency/outcomes, alert responsible humans and recover only through approved changes.

The governance rules decide what is allowed and whose authority is required. Security mechanisms enforce identities, isolation, integrity and containment. Shared PEP/PDP infrastructure SHALL enforce both, with separately identifiable policy/reason codes. No LLM evaluates final permission. Human-help and static fallback retain their narrowly specified independent paths.

## Initial mapping to enforceable requirements

The following is a risk-family mapping. It is not yet an individual-control/technique crosswalk. Exact ASVS and ATLAS identifiers must be pinned and verified under TR-SEC-16 before affected implementation acceptance.

| Threat / governance concern | Reference basis | Inline control / requirement | Acceptance |
|---|---|---|---|
| Session theft, broken object/field authorization, identity privilege abuse | ASVS; ATLAS applicable access techniques; SSF/CAEP | Current identity/assurance, ownership filters, revocation and reauthorization; TR-SEC-09/10; TR-GOV-06…11 | AT-02/14/15 |
| Direct/indirect prompt injection and tool hijacking | OWASP LLM01:2025 and LLM06:2025; ATLAS applicable injection techniques; OWASP agentic guidance | Broker-only tools, taint/source checks, no caller-controlled recipients; TR-SEC-11/12 | AT-08/15 |
| Sensitive disclosure, prompt leakage and exfiltration | OWASP LLM02:2025 and LLM07:2025; ASVS; ATLAS | Prompt minimization, no secrets in context, denied egress, field filtering and stream revocation; TR-SEC-09…12 | AT-02/08/15 |
| Compromised dependencies/model, poisoned feeds/context | OWASP LLM03:2025 and LLM04:2025; ATLAS | Artifact verification, provenance/quarantine, drift fencing; TR-SEC-12/14 | AT-08/10/15 |
| Unsafe output and invented authoritative facts | OWASP LLM05:2025 and LLM09:2025; ASVS | Safe rendering, no executable model output, controlled sourced assembly; TR-SEC-09/12 | AT-03/08/15 |
| Cross-session retrieval and poisoned embeddings | OWASP LLM08:2025; ATLAS | Shared retrieval absent; future enablement requires reviewed isolation and negative tests; TR-SEC-12/16 | AT-08/15 |
| Unbounded consumption, cascading failure and abuse | OWASP LLM10:2025; OWASP agentic guidance | Resource budgets, bounded queues, protected human-help capacity; TR-SEC-13/15 | AT-11/15 |
| Stale approval, unsafe policy activation or governance drift | NIST AI RMF; ISO management-system intent; NIST Zero Trust | Signed approved bundles, epoch/revision fencing, atomic activation, no self-approval; TR-GOV-01…12 | AT-12/14/16 |
| Lost/replayed identity events and delayed revocation | SSF/CAEP; Zero Trust | Signature/issuer/audience/freshness validation, deduplication, recovery and current-state checks; TR-SEC-10 | AT-14/15 |
| Unowned risks, expired exceptions and unsupported assurance claims | AI RMF; ISO 42001 overview; optional OSCAL representation | Named responsible role, review dates, scope/digest-bound exceptions and residual-risk evidence; TR-GOV-13/14 | AT-16 |

## Standards adoption requirements

**TR-GOV-13 — Tailored control register.** SHALL maintain a versioned register containing local control ID, reference/edition/exact verified identifier where applicable, applicability/rationale, protected operation, enforcement owner and component, policy digest, test/evidence reference, residual risk, responsible human role and review date. Initial status is proposed/not implemented. Framework references SHALL not create an implied approval or legal obligation. Resolve outdated references and edition deltas through human review; do not silently update live policies when a framework website changes.

**TR-GOV-14 — Governance rules as operational policy.** Each automatable governance obligation SHALL identify its authoritative inputs, deterministic condition, required approval, effect/obligation, activation scope, fail-closed behavior and verification case. Non-automatable clinical/legal/community judgements SHALL remain explicitly human-owned, blocking the affected capability where approval is absent. Security/governance exceptions SHALL have exact scope, approving authority, expiry and compensating control; expiry SHALL automatically stop affected permission. No exception may authorize police integration, autonomous emergency contact, self-approval, real-data demo use or production promotion. Standards alignment SHALL never override these project constraints.

## Proposed runtime budgets and limitations

`runtime_security` and `runtime_governance` in [demo-parameters.json](demo-parameters.json) define local acceptance budgets, not values prescribed by a standard. A decision is inline before effect; detection/response, revocation propagation, configuration-drift discovery and alert presentation have distinct clocks. Test distributions and maximums under the declared workload. Classifier detection may miss novel attacks; network restrictions, ownership and policy checks remain mandatory independent barriers. All capacity and timing claims remain unmeasured.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
