# Accepted choices, remaining evidence and implementation sequence

No unresolved item below prevents drafting the LLD. It does prevent claiming a particular integration, standard mapping, measured performance or release as ready. The accepted local DEC choices are not awaiting reapproval. The user accepted the recommended LLD directions on 2026-11-06; the [acceptance record](decisions/2026-11-06-implementation-choices-and-model.md) scopes that decision. Mechanisms remain subject to implementation verification and required independent release review; no additional approval framework or clinical credential is invented.

| ID | Remaining specifics / evidence | Accepted direction / conditions | Affected capability and completion evidence |
|---|---|---|---|
| LD-01 | Host OS/architecture/RAM/GPU/storage/VM/CNI/ports, disk fsync and firewall reachability | **This workstation selected.** Inventory it and choose the smallest tested local Kubernetes/CNI binding. Alternative distribution only with same probes | All deployed containment/resources; allowed/denied host/pod/backend/IPv6 and durability tests |
| LD-02 | Exact framework/runtime/DB/IdP/PDP/image versions and license/security pins | Retain accepted React/FastAPI/PostgreSQL/Keycloak/OPA stack direction; lock supported compatible versions after review | Reproducible build/migration/identity behavior; no installed version claimed |
| LD-03 | Proxy/issuer product/version/SVID lifetime/host attestation | Evaluate SPIRE+Envoy initial binding, compare actual full-mesh cost; material family change recorded explicitly | DEC-01 implementation, bypass/rotation/issuer-loss/active-connection fence and host bridge evidence |
| LD-04 | Gemma artifact origin/digest/quantization/license/tokenizer/template/LM Studio version and function admission | **`google/gemma-4-12b-qat` selected**, reported already downloaded in LM Studio. Verify metadata and enable only functions that pass real tests; manual/templates otherwise | Per-function AI enabled set; no automatic model substitution |
| LD-05 | Actual-account and linkage retention periods, metadata reviewers/custody | Separate minimum-needed active/deprovision/recovery schedule. No synthetic TTL default | Real-account operation/retention acceptance, including ACL/assignment/reviewer and recovery metadata |
| LD-06 | Current host journal recency/durability and generation-gate implementation proof | Test DEC-04 continuing-host assumptions and every crash boundary; stronger off-host witness is separate architecture decision | Protected live/restore serving; suspect head remains quarantined |
| LD-07 | Independent current fallback content and EN/FR review | Owner/independent reviewer verify real Canadian content before participant use; no invented contacts | Static publication and participant-use release; this package contains no contact numbers |
| LD-08 | Exact official standard editions/digests/identifiers/applicable denominator | Extract/verify tailored ASVS/ATLAS/OWASP/SSF references from pinned primary artifacts | Standards-specific implementation acceptance/interoperability, never blanket certification |
| LD-09 | Named actual reviewer identities and required class-specific authority, repository protections | Human review of exact changes with proposer separation; extra accounts do not create independence | Implementation/config activation/release; current AI review supplies no human approval |
| LD-10 | Upstream D-02 source-owner dispositions | Keep locally accepted deltas and explicit divergence; revise only authorized upstream sources | Upstream-conformance claim, not unrelated synthetic design work |
| LD-11 | Clinical/youth/legal/Indigenous/real partner/staffing context | Keep real functions disabled/stubbed; obtain proper future scoped decisions before widening intended use | Real-user/clinical/production operation remains outside this design |
| LD-12 | Load budgets/resources and usability efficacy | Measure declared10-session workload,2compute slots/8queued, all failure latencies and actor-only baseline | Timing/capacity/usefulness claims; no measured values fabricated |
| LD-13 | Explicit identity-link ceremony and authority | Keep identity-link route disabled; design a separately reviewed same-subject proof/consent/recovery flow if needed | Account-to-PID linkage only; continuation does not enable it |

## Implementation order and acceptance

1. Implement shared types, validators, separate logins/role UIs, current manual intake/human request, canonical audit and independent static/help paths. Human/manual usefulness is the first service increment.
2. Add deterministic fixture assessment, sourced directory, PID/carer assertions, plans/consent, workforce reservation/connection/takeover and transaction/race tests.
3. Add durable coordinator, narrow tools, exact local model adapter and function admission; compare optional source-linked drafts to a usable actor-only workflow.
4. Add simulator referrals/receipts/reconciliation, follow-up and outcomes, then lifecycle/export/delete/holds and current-journal recovery. Test unknown delivery and restored rights before claiming complete demo.
5. Complete artifact activation, security/drift/incident/aggregate/evaluation consoles and all adverse/operational/human evidence. Keep compatible LKG and independent fallback throughout.

Each increment is a reviewable implementation PR with behavior, evidence, limitations and compatible rollback. This authoring task creates only doc/LLD; no runtime code, installation, database/host changes, PR, push or deployment follows automatically. The earlier deleted LLD is not restored. A future actual release requires independent human acceptance and configured controls, not merely completing these documents.
