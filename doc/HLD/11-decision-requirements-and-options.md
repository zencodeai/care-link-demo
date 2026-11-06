# Decisions required before finalizing the LLD

Prepared 2026-11-06 · Status: **all five recommended options accepted by the user for local design on 2026-11-06**.

See the [acceptance record](decisions/2026-11-06-local-design-baseline.md) for the approval evidence, exact pre-annotation brief digest, selected options and retained qualifications. Recommendation/alternative text below preserves the basis of the decision; it is not a claim of implementation or upstream approval.

This brief covers the five open choices identified in [HLD 10](10-decisions-and-implementation-boundaries.md). They did not prevent starting a new LLD. Their accepted local choices now provide the design direction; remaining product, protocol, measurement and upstream-disposition work is stated explicitly. Preparing this document does not create or restore the deleted LLD, approve a source change, install products or change runtime parameters.

Recommendations target a private, synthetic, Ottawa-hosted demonstrator using Docker/Kubernetes and host LM Studio/Gemma. They retain useful actor support, no police integration, absent autonomous emergency contact, deterministic runtime controls and explicit clinical/production limits. Named responsibility groups below are proposed decision owners, not appointed professionals or evidence of independent approval.

## Decision summary

| ID | Decision requirement | Accepted recommended option | Detailed-design responsibility |
|---|---|---|---|
| DEC-01 | Select workload authentication, identity lifecycle and connection enforcement approach | B — standardized service proxies with automated attested workload identity; no mandatory full mesh initially | Service connectivity, credential lifecycle and compromise-response design |
| DEC-02 | Define what private minimal help may do when primary identity/control is unavailable | A — fresh-authority-required private operations, with unconditional static fallback; no stale-trust exception initially | Help credential, acknowledgement and outage contracts |
| DEC-03 | Define retention clock anchors, purpose-copy dependencies, holds and actual access-metadata treatment | B — event-anchored per-purpose lifecycle using existing demo durations, explicit exceptions and current recovery restrictions | Physical relationships, expiry/deletion/backup jobs and rights status |
| DEC-04 | Select current recovery authority and serving-promotion ownership | B — separate host recovery-control journal/checkpoints, isolated quarantine and independently approved promotion | Restore/cutover, recovery permissions and disaster limitations |
| DEC-05 | Disposition upstream inference, youth and safe-mode authority conflicts | A — explicit local delta decisions plus targeted upstream source-owner disposition | Source-conformance assertions and affected authority contracts |

The user approved all five recommendations together; each option and its qualifications are recorded separately. Product/version choice, evidence and upstream disposition remain separate from this local architecture-family/lifecycle acceptance.

## DEC-01 — Workload authentication and mesh boundary

### Decision requirement

Choose how protected services prove their own identity, authenticate peers, rotate credentials, deny unauthorized connections and contain a compromised workload. Cover Kubernetes workloads and the host inference bridge, not just browser authentication. Existing open connections, streams and pending work must be fenced after compromise; certificate expiry alone is insufficient. Service identity does not replace initiating actor/task/purpose, consent or business authorization.

HLD references: [trust plane](04-safety-security-and-governance.md), [deployment](07-deployment-and-delivery.md). Requirement drivers: TR-SEC-01/09/10/11/14/15; TR-GOV-06…12; TR-OPS-03.

| Option | Benefits | Costs and risks | Suitability |
|---|---|---|---|
| A — Full service mesh with automated identity and connection policy | Common lifecycle and policy-distribution model across services; reduced per-application TLS integration | Additional platform/control-plane operations, host/VM boundary integration and bypass configuration; local footprint unmeasured | Valid if deployment proof shows lower total complexity than B |
| B — Standardized explicit service proxies with automated attested issuer | Centralizes identity/TLS enforcement while keeping domain code independent; can cover a small known connection graph without a full mesh control plane | Still needs an issuer/attestation service, policy distribution, automated rotation, connection fencing and proof that backend listeners cannot bypass proxies; not inherently simpler | **Recommended initial family**, conditional on the same security tests as A |
| C — Application-managed mTLS with automated issuer | Fewer proxy processes and direct library control | Every application must implement correct peer identity, rotation, authorization and failure handling; inconsistent integration and open-connection revocation risk | Reserve for a very small verified stack; static manually issued shared certificates are not an acceptable substitute |

### Recommendation and decision boundary

Select **B** for the first detailed-design candidate. Compare its actual integration/operational cost against A before treating it as final; if B requires bespoke certificate/policy plumbing, prefer the demonstrably simpler supported full-mesh approach instead. Do not claim proxy-managed mTLS is automatically lightweight or secure.

A candidate combination for evaluation is SPIFFE/SPIRE attested identities plus a supported proxy such as Envoy. This is not a product/version approval: SPIRE supplies identity/attestation, a proxy supplies connection enforcement, and CNI/firewall prevents alternate routes. Neither SPIRE nor a certificate alone supplies application authorization. Keep the existing Kubernetes choice open until host/routing/network-policy capability is known.

The LLD must specify issuer trust/bootstrap, per-workload identity bindings, automatic rotation, destination verification, policy distribution, direct-listener bypass prevention, current revocation and host-bridge treatment. It must show credential/issuer outage states and how already-open traffic/work is fenced. The independent help/static path must not gain a dependency on the main mesh just to reuse a certificate service.

**Evidence before implementation acceptance:** unauthorized/missing/wrong-identity peer denied; certificate/issuer change handled safely; compromised connection/stream/queued action fenced; runtime cannot reach stores/policy/host inference directly; host bridge accepts only the designated gateway. Resource fit and timings are measured, not assumed.

**Proposed accountable roles:** architecture and security recommend; operations verifies operability; an independent appropriate human reviews the selected design.

**Primary references:** [SPIRE identity and attestation concepts](https://spiffe.io/docs/latest/spire-about/spire-concepts/), [Envoy credential delivery/rotation through SDS](https://www.envoyproxy.io/docs/envoy/latest/configuration/security/secret), [Istio security architecture](https://istio.io/latest/docs/concepts/security/). These support possible mechanisms, not a claim that any is installed or that the combination has been tested here. The references are evolving; pin supported releases before implementation.

## DEC-02 — Independent minimal-help trust during outages

### Decision requirement

Decide the authority required to accept a private help request, show its status or permit a worker to accept it when the primary application/identity/control plane fails. Distinguish **recorded request**, **accepted but unconnected**, and **confirmed human connection**. Define exactly which failures preserve private help and which leave static information only. A healthy host listener and unexpired token do not prove current rights.

HLD references: [safe mode](04-safety-security-and-governance.md), [capability hierarchy](08-reliability-and-operations.md). Drivers: TR-WF-04/06; TR-GOV-10; TR-SEC-10; TR-OPS-08/09; TR-AI-09.

| Option | Benefits | Costs and risks | Suitability |
|---|---|---|---|
| A — Current authoritative validation required for each private operation | Preserves current revocation semantics, clear fail-closed behaviour and no invented stale-permission allowance | Private help may be unavailable during identity/control outage even though host UI/spool survives; static information is then the retained capability | **Recommended initial rule** |
| B — Bounded offline validation against cached credentials and restrictions | May extend request acceptance during selected control outages | Introduces an explicit stale-revocation interval and recovery/synchronization obligations; conflicts with any claim of immediate current-authority enforcement unless that exception is scoped and approved | Only after a documented risk/requirements disposition, not an implicit token-cache setting |
| C — Independently operated host help identity/revocation authority | Can maintain fresh authority during main-cluster loss | Additional independently bootstrapped trust, enrollment/offboarding and cross-authority revocation design; must avoid a partially revoked user remaining active in help | Future extension if private-help continuity through complete cluster/identity loss is required |

### Recommendation and service consequence

Select **A now**: direct independently served host UI, durable narrow spool and no private business history; a private operation succeeds only when its current authority can be established. Static information remains unconditional. Do not implement a grace-period/fail-open flag or claim a private request was accepted when trust could not be checked.

This deliberately means **host entry independence is not full authentication independence**. An edge/model/core failure may leave the current identity path usable; loss of the sole authority does not. Update any acceptance narrative that promises authenticated help through every complete cluster outage. If such continuity is required, select/design **C** rather than pretending B provides fresh revocation. A later choice of C needs a reviewable amendment to HLD and identity ownership.

No new freshness duration is recommended here. Required runtime revocation targets remain those in the existing requirements. Cryptographic key/trust-bundle caching is distinct from caching a positive authorization. Jobs, private status views and worker acceptance require current scope; no private conversation access or actual connection guarantee is created by spool acceptance.

**Evidence:** simulate main edge/core/model failure separately from authority failure; verify current authorized help requests where possible and static-only status when authority is absent; deny a revoked user despite valid-looking token; reconcile request IDs to restored core without duplicate request, stale grant or false connected status.

**Proposed accountable roles:** security and operations, with product review of the reduced outage promise.

## DEC-03 — Retention anchors, copies, holds and access metadata

### Decision requirement

Durations alone do not determine when records expire. Choose an authoritative anchor for each purpose, handling of unresolved sessions, dependent plan/assertion copies, holds, rights exceptions, backups and real authentication metadata. Define what completion actually means. Existing demo durations must not be silently changed or presented as statutory requirements.

HLD reference: [lifecycle and rights](05-data-and-audit.md). Drivers: TR-DAT-01/02/04; TR-WF-08; FR-H5/H7; AQ-10/AQ-27/AQ-37 and [demo retention parameters](../REQ/demo-parameters.json).

| Option | Benefits | Costs and risks | Suitability |
|---|---|---|---|
| A — Creation-time TTL for every class | Simple scheduling and easy volume bound | Can remove an active plan/unresolved crisis context and misses parent, consent and copy semantics | Reject as a universal rule; suitable only for explicitly capture/event-bound temporary classes |
| B — Event-anchored per-purpose lifecycle and explicit dependency/hold history | Preserves active context, makes deletion/backup effects testable and aligns retention to real lifecycle | Requires reliable closure/retirement facts, copy inventory and explicit unresolved/held states | **Recommended demo model** |
| C — Retain until manually deleted, with no scheduled lifecycle | Avoids accidental automated expiry | Accumulation, inconsistent rights outcomes, operational burden and no automatic minimization | Not appropriate as the system-wide rule; active plans may have explicit until-retirement treatment |

### Recommended anchor proposal

Preserve current duration values. Adopt these anchor meanings **only after this decision is accepted**:

| Class / existing default | Proposed anchor and exception |
|---|---|
| Session content and session-purpose person/carer records — 7 days | Explicit session/last relevant parent closure. Unresolved sessions remain anchor-pending and are reviewed, never closed solely to trigger expiry. |
| Referral payload/receipts — 7 days | Later of session closure and terminal/reconciled delivery outcome. Unknown delivery requires accountable reconciliation/review rather than silent indefinite retention. |
| Plans and justified plan-purpose snapshots — 30 days | Explicit plan retirement as the ordinary demo cleanup anchor. Active plans remain available; a verified PID deletion request triggers the existing faster deletion target instead of starting a fresh 30-day delay. |
| Consent history — 30 days | Later of relevant parent closure and effective grant expiry/revocation. Minimal revocation/guard evidence remains for dependent grants/restore safety, with reported retention exception. |
| Replay corpus — 7 days | Capture time; not an alternative permanent session record. |
| Security events — 30 days; audit metadata — 90 days; aggregate metrics — 90 days | Event time or closed reporting interval, with audit-chain closure/pruning and purpose limits. |
| Backup copies — 7 days | Immutable capture time. Retry/restore does not silently renew archive expiry. Holds and any extra recovery-copy retention are explicit exceptions. |
| Actual account/login metadata | Separate schedule: keep the minimum needed for active issued accounts, propose removing inactive session artifacts after their security/recovery window and minimizing account identifiers after deprovisioning. Exact periods remain a separate privacy/security decision; do not apply a synthetic-data TTL by accident. |
| Recovery restrictions and approval history | Retain minimal evidence for all restorable backups and still-dependent grants/receipts; review long-lived linkability. No rule silently deletes the authority needed to stop restoration of old data. |

These anchor choices qualify previously underspecified engineering defaults and may expose differences from upstream source lifecycle wording. They are not legal approval. A protected purpose-bound plan snapshot can outlive its session source only with its own documented purpose and provenance; deletion must enumerate all copies. An expired source cannot become an invented verified fact.

Hold/release history must have scoped authority, reason, parent/copy reach, duration/review and accountable release. There is no automatic legal-hold authority inferred from a project role. For the demo, use explicitly approved engineering preservation holds and disclose their effect on rights targets. Missing anchors, unknown class/purpose, cycles or contradictory history produce review-needed, not eligibility. Holds cannot justify unbounded hidden retention or erase required negative rights.

Report retained, eligible, held, active-content-purged/backup-pending, completed-with-exceptions and failed/reconcile states honestly. SQL DELETE/file unlink does not prove physical erasure from WAL, pages or filesystem snapshots. The existing active-deletion and backup-expiry targets remain targets for eligible content; any retained audit/control exception is visible.

**Evidence:** active plan survives ordinary session expiry; session/plan copies follow their own approved rule; revoked grants cannot reappear; a held child/copy is handled consistently; deletion covers exports/replay/backups; unknown rule blocks purge and is assigned for review; real account metadata never gets silently classified synthetic.

**Proposed accountable roles:** product and privacy/security responsibility, independently reviewed for this demo. Clinical/legal schedules remain outside this engineering decision.

## DEC-04 — Current recovery authority and serving promotion

### Decision requirement

Select where current consent/revocation/deletion/hold history survives a business restore, how recency is established, who may restore versus approve serving, and what happens when current truth cannot be established. A restored database must not certify that its own restrictions are latest. A signed old checkpoint proves origin, not recency.

HLD references: [recovery authority](05-data-and-audit.md), [quarantine and serving stages](08-reliability-and-operations.md). Drivers: TR-DAT-02/03/04; TR-OPS-10; TR-GOV-03/09; TR-SEC-10/15.

| Option | Benefits | Costs and risks | Suitability |
|---|---|---|---|
| A — Restore snapshot plus the control history it contains | Simple and self-contained | Reinstates superseded grants/deleted content after point-in-time rollback; no independent evidence of latest restrictions | Reject as serving authority; backup history remains useful evidence only |
| B — Separate host recovery-control journal/checkpoints with restricted credentials | Survives ordinary app/cluster/database restore, fits local deployment and supports conservative replay/quarantine | Still vulnerable to whole-host loss/root rollback; durable publication and journal/DB uncertainty must be explicitly reconciled | **Recommended local-demo baseline** |
| C — Independently administered second failure domain / trusted witness | Stronger disaster/anti-rollback evidence and separation of compromise domains | More infrastructure, key/custody/residency and operational obligations; not current single-host guarantee | Required extension for broader disaster or independent-host claims |

### Recommendation and recovery semantics

Select **B**, explicitly limited to local application/cluster/data recovery. Keep the journal outside the restored business store and cluster-managed volume lifecycle, with separate credentials, signed/integrity-checked ordered history and checkpoint provenance. Include all state needed to prevent unauthorized resurrection, not only deletion: current identity/consent/sharing restrictions, holds and relevant activation/recovery decisions. Ordinary app/restore-worker credentials cannot edit or truncate it.

The LLD must define which changes require durable recovery intent before acknowledgement, how journal/DB partial success reconciles, and what trusted monotonic head continuity is available. No atomic filesystem+database+router claim. When required current history is absent, corrupt or cannot be shown sufficiently current, stay quarantined; a timestamp, signature or sequence number from an old restored copy is insufficient. If all copies share a compromised/lost host, B cannot establish disaster recency—do not assert it can. Adopt C before making that claim.

Restoration and serving are different authorities. Recovery worker builds an isolated target and validation evidence; operator proposes serving; a distinct authorized human approves the exact target/current-authority evidence; controlled promotion fences obsolete generations and only enables healthy capability after reconciliation. A changed target/head invalidates stale approval. Restored tokens, leases and review receipts never automatically regain authority.

**Evidence:** old backup retains no access revoked since capture; missing journal blocks serving; control change after approval invalidates promotion; partial journal/DB outcome has deterministic reconcile status; crash during cutover produces one fenced serving generation and no duplicate dispatch. Actual RPO/RTO includes current-rights validation, not merely database startup.

**Proposed accountable roles:** architecture, recovery operations and security; independent authorized human for serving promotion. Approval independence is human accountability, not a claim of independent hardware.

## DEC-05 — Upstream authority conflicts and local design baseline

### Decision requirement

Decide the disposition of the existing REQ D-02 source conflicts: broker-mediated inference under broker-only runtime egress, youth mediation without an invalid authority edge, and safe-mode human help without a general security bypass. Distinguish local design adoption from upstream source conformance and live activation. This decision does not reopen the chosen LM Studio/Gemma requirement or permit direct runtime egress.

| Option | Benefits | Costs and risks | Suitability |
|---|---|---|---|
| A — Explicit local delta decisions and targeted upstream source-owner disposition | Keeps work moving on a coherent local candidate while preserving traceability and source authority | Requires separate clear status for local recommendation, local acceptance, upstream disposition and implementation evidence | **Recommended** |
| B — Halt all affected design until upstream artifacts are revised and approved | Strong source synchronization | Blocks useful proposal work and may stall unrelated LLD sections unnecessarily | Needed only before a required source-conformance/approval claim, not before drafting |
| C — Silently treat implementation bindings or historical approvals as resolving source conflicts | Fast apparent closure | Hides changed authority and imports unsupported permission | Reject |

### Recommended local proposals

1. **Inference:** runtime requests model work through broker; only approved gateway invokes host LM Studio. Prompt/context handling, returned taint, model/version provenance and protected inference audit remain explicit. No new runtime destination.
2. **Youth:** broker/domain mediation enforces youth privacy, current disclosure basis and human escalation; do not invent a forbidden enforcer-to-enforcer authority edge. Real legal/capacity/youth rules stay disabled/stubbed.
3. **Safe-mode help:** normal human routing remains current-policy/audit mediated when healthy; independent minimal help uses DEC-02's narrow trust contract with no protected history or arbitrary tools, and static content is unconditional. No blanket policy bypass.

Record each proposal's requirement/HLD references, changed boundary, source conflict, human decision, required upstream disposition and validation. A single local accept statement must not imply that named source owners approved all three. Where upstream updates are not authorized, keep a documented divergence and avoid upstream-conformance or activation-approved claims. If a later disposition changes authority, revise the affected HLD and LLD rather than quietly changing implementation.

**Evidence:** trace every runtime/inference/young-person/help operation to a permitted authority path; demonstrate no direct egress, unauthorized guardian disclosure or safe-mode escape route; keep local and upstream acceptance/evidence states distinct.

**Proposed accountable roles:** local architecture/product for the local baseline; actual source owner and applicable safety/security/privacy authority for upstream disposition. These actors are not assumed to be appointed or independent merely because the document names a responsibility.

## Recommended order and decision record

All five local choices are accepted. Define the detailed DEC-01/02 protocols first because connectivity and outage trust affect many interfaces. Develop DEC-03/04 together so rights history survives every retained copy. Track DEC-05 upstream dispositions in parallel; the local baseline is accepted, while upstream conformance remains unestablished.

For each decision record: chosen option or qualified alternative; rationale; scope; actual accountable decision maker; date; independent reviewer where required; affected HLD/requirements; parameter implications; evidence needed before implementation acceptance; outstanding conditions. No new approval database or phase-gating framework is required—an attributable versioned decision record/PR review is sufficient for design acceptance within the existing governance process.

**Acceptance follow-through:** HLD 04/05/07/08/10, the inventory and relevant parameter meanings now reflect the accepted local choices. Source history and scope exclusions are preserved. Runtime settings are not activated. Host probes, exact product/version/model pins, actual-account metadata schedule, verified fallback content, independent reviews and eventual clinical/partner permissions remain separate readiness obligations. No LLD is created or restored.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
