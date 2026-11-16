# IMP-03 session003 qualification status

**Automation continuation is in progress:** see [current continuation status](automation-continuation-status.md) for new completed browser-trust, EN/FR UI, contention/buffered-output, ACL, database-ack and quarantine evidence. Earlier Option B tables below describe the preserved original target; a separate continuation candidate/packet is being finalized.

2026-11-13. **Option B is deployed and the scripted normal journey plus all five adverse phases passed. G-03 remains pending.** The user selected shared running infrastructure and separately approved scoped TLS renewal. The source guide supplies procedure; these user decisions supply authority. No human acceptance, participant admission or IMP-04 activation is inferred.

**Current target state:** the final one-way core fence is retained at generation1. Protected core operations are intentionally denied. All reversible process/grant faults were restored. The privileged seed and provisioning supervisors were removed; ordinary serving containers, new identities/state/volumes and private operator inputs remain. Do not rerun initial provisioning, reset the fence, or replay completed TLS maintenance.

See [Option B results](option-b-results.json), [current candidate](option-b-candidate-manifest.json), [deployed artifacts](option-b-deployed-artifacts.json), [current draft DemoPacket](option-b-demo-packet.json), [handoff](handoff.md), and [operator profile](../../../../../../tools/imp03_shared/README.md). The earlier `checks.json`, `candidate-manifest.json`, `environment.json`, `demo-packet.json` and `agent-result.json` remain historical records of the initial local-only run, not the present target.

| Guide steps | Actual result | Limits or evidence |
|---|---|---|
| 1–2 — Scope/candidate | Bound to Option B authorization, separate TLS approval and actual artifacts/config hashes | Current uncommitted source has changed since the initial 319-file local candidate. Separate current manifest records it. G-02 remains inherited acceptance only. |
| 3 — Source/full checks | Final source **536 Python passed/56 declared skips; 59 TS passed**. Full PostgreSQL/OPA lane **590 passed/two skips; 59 TS passed**. Separate provisioning **one passed**. | Two full-lane skips are Linux-only UID (covered earlier in its exact unchanged workload-source scope) and provisioning (passed separately). Existing deprecations and Vite chunk warning remain. |
| 4 — Infrastructure | Shared SPIRE server/Keycloak/PostgreSQL reused with fresh IMP-03 resources | Docker apps outside kind; not new-app Kubernetes/Calico qualification. Shared failure/administration domain is explicit. |
| 5–7 — Actors/config/provision | Fresh realm/client, distinct audience and three real password+OTP actors; separate DBs/logins; five role configs and journal initialized | Actual private binding/browser hashes and role config custody recorded. Runtime protocol lease remains `imp03-002`; work belongs to session003. No old state adopted/reset. |
| 8 — Trust/isolation | Each dedicated agent issued only its expected role SVID to proxy UID22002; all five naturally renewed beyond earlier leaf expiry. Actual five app UIDs, network=none, absent sibling/SVID mounts, direct TCP denial observed | Parent+Unix UID attestation, not exact image selectors. No independent live expired-credential rejection or comprehensive route/negative source-IP policy coverage. |
| 9–10 — Serving/browser | Five protected roles served; real browser ran from private pinned headless cache | Backend CA/hostname verification preserved. Browser uses a recorded temporary CA exception; browser CA trust remains unqualified. |
| 11 — Normal journey | **Passed, attempt011**: three real MFA actors; UI creation; real two-party SSE handshake; attributed message delivery; disconnect; takeover/old-owner denial; dropped committed rotation reply; original-key reconciliation; fresh provider recovery | Later shutdown/fence preconditions re-established logins and creation after restart. Selected UI + API/SSE coverage, not full actor UI acceptance. |
| 12 — Dependency loss | **PDP, identity and journal phases passed** | Exact receipt/pidfd pauses/resumes. Actual GET and POST denied; 23 business table hashes/counts and committed-operation counts unchanged while faults active. This excludes durable event/duty/job/recovery rows, audit-chain integrity and buffered output. |
| 13 — Audit loss | **Passed, attempt003**; exact new audit grant restored | Actual GET/POST denied and same durable comparison. Earlier attempt001 creation403 and attempt002 pre-readiness timeout remain unexplained observations; neither applied an audit fault. |
| 14 — One-way fence last | **Passed**: core restriction durable at generation1, GET403/POST403, measured business state unchanged | Restriction retained; no unfence/reset. Scoped UID22001 custodian removed. |
| 15 — Additional scenarios | Local fixture coverage plus deployed normal/denial coverage above | Remaining live obligations listed below; this is not comprehensive G-03 scenario completion. |
| 16 — Operations/human | One five-role resource sample, ten health round trips, owned core stop/start; help/static200 while stopped | Median health round trip ~3ms, not protected-operation/capacity acceptance. Stop exit241 records SIGTERM propagation, not zero-exit graceful certification. Human EN/FR, keyboard and screen-reader reviews absent. |
| 17–18 — Packet/decision | Current candidate and draft packet assembled | Not ready for G-03 acceptance; no decision/ledger acceptance recorded. |

## Fixes and failed attempts retained

Q-01 is resolved: CSRF is acquired before readiness; the actual intended post-fault POST is observed and its token-free method/path/status is recorded. Three harness regressions passed and live durable-state checks add separate evidence. Browser execution also exposed missing locale, a CSP-incompatible parking page and assertions that confused transport liveness with human connection; these harness defects were corrected without weakening CSP or server controls.

The live participant message read exposed a runtime adapter defect: `PageQuery` permits an omitted cursor but rejects null. Core now omits an absent cursor and data consumes optional fields with defaults. Four signed-envelope pagination regressions, a real signed composition extension and the full lane passed. Only new core/data containers were replaced, preserving credentials and durable volumes. Startup attempt009 saw503; later complete normal/phase runs passed. Failed browser attempts remain in `evidence/option-b-live-*.json`; raw outputs remain private.

## Remaining G-03 obligations

The scripted journey and five named barriers passed within their recorded scope. The following items extend that evidence to the rest of the guide. Some need additional automated observations; others need a deployment change or an actual human decision. An unobserved scenario is an evidence gap, not by itself a demonstrated control failure. The unexplained pre-readiness failures remain concrete observations requiring diagnosis.

The reference is [guide steps8–18](../002-runtime-completion/G-03-validation-guide.md), especially step15's additional scenarios and step16's human/operational review. The current [review](option-b-review.md) confirms these evidence limits. No new live work is executed by this expanded breakdown.

### 1. Browser certificate trust — automatable with an isolated trust setup

**Already observed:** verified backend CA/hostname checks and TLS1.3 for the named transports. Real browser actors completed login and service actions, but Playwright used `ignoreHTTPSErrors: true`.

**Missing evidence:** the browser itself accepts the intended certificate chains and hostnames for main, provider, help and static while normal certificate verification is enabled.

**Closure:** prepare a scoped browser trust configuration, run with `ignoreHTTPSErrors: false`, and retain successful navigation/login plus a negative wrong-hostname or untrusted-certificate observation. Record the trust material and browser profile without publishing private keys or credentials. No global workstation trust change is implied by this obligation.

### 2. Deployment and workload identity profile — implementation plus review

**Already observed:** five capless network-none Docker apps, distinct application UIDs/custody, protected relays, dedicated SPIRE agent parents, role-specific SVIDs, natural renewal and the final one-way fence. Option B explicitly permits sharing the existing SPIRE/Keycloak/PostgreSQL processes.

**Remaining profile differences:**

- Applications run outside kind. There is no new-application Kubernetes/Calico enforcement evidence.
- The source-workspace images contain multiple role packages and co-located service tests. Per-role installed dependencies/distributions are not established.
- Workload registrations establish dedicated parent identity plus Unix UID22002. They do not demonstrate exact deployed image selectors rejecting an incorrect image.

**Closure:** either implement and demonstrate the intended role packaging/placement/selectors, or present a concrete deployment delta with exact retained controls and limitations for review within the proposed bounded G-03 scope. The Option B authorization alone does not establish these separate architectural claims. Sharing the existing infrastructure does not require creating a second full infrastructure stack merely to address them.

### 3. Additional live actor/control scenarios — principally automatable

Local fixture tests provide useful mechanism evidence. Each scenario below still needs sufficient current deployed evidence, including actual outcomes and relevant durable state.

| Scenario | Required observation for closure |
|---|---|
| Disclosure and fictional intake UI | Use the actual participant UI to acknowledge the exact disclosure and submit fictional intake/turns. Demonstrate the required gate and truthful attribution in the resulting views. Existing UI creation plus API/SSE manual messaging is narrower. |
| Competing workers | Issue two distinct eligible worker accounts and race reservation/acceptance of the same conversation. Establish one resulting owner/active assignment and a truthful conflict for the other, using current projections and durable rows. Existing worker-versus-supervisor takeover is a different scenario. |
| Buffered output across takeover | Hold an old worker's response/output across the control-epoch change, then release it. Observe that the stale output does not become newly visible or produce an unauthorized later effect. Rejection of a new old-owner POST after takeover does not establish this case. |
| Lost database acknowledgement | Inject acknowledgement loss at the serving database transaction boundary after the commit can have occurred. Reconcile/retry the original operation and prove exactly one logical durable effect. The passed rotation test drops an HTTP reply after server success; that is a different failure boundary. |
| Current identity or ACL revocation | Establish access, apply a scoped current restriction/revocation, then attempt subsequent reads/disclosure and relevant writes on existing and new channels. Confirm current authority wins over previously successful access or cached proof. Workload core fencing is a separate control. |
| Capture and restore to quarantine | Capture the actual target under assigned custody, import into a separate quarantined target and verify consistency, restricted roles and absence of serving authority. Preserve the original target. Trusted serving recovery/promotion remains IMP-09. |

A second issued worker, fault hooks and a quarantine destination are prerequisites to the corresponding cases; they are not supplied by the existing three-actor script.

### 4. Audit integrity and complete forbidden-effect coverage — automatable

**Already observed:** while each named barrier was active, actual GET/POST calls denied and snapshots of 23 tables in `core`, `workforce`, `access`, `lifecycle` and `control`, plus committed-operation counts, stayed unchanged. Audit append privilege was restored after the audit-loss phase.

**Missing evidence:** the snapshot excludes `durable.event`, `durable.due_job`, `durable.duty_*`, `recovery.command`, audit-chain integrity and already buffered/output effects. HTTP denial and the existing comparison therefore cover only the measured state.

**Closure:** define the protected effect set for each attempted operation, extend observation to its relevant durable/outbox/job/recovery state, and verify persisted audit continuity/hashes against the actual target. Distinguish legitimate denial audit records from prohibited business effects. For in-flight output cases, observe bytes/events at the client as well as database state. Do not infer whole-database integrity or absence of delivery from unchanged sampled rows.

### 5. Negative trust, route and network cases — automatable on an isolated target

**Already observed:** allowed real service paths, app direct TCP denial, absent sibling/SVID mounts, correct role SVID issuance/renewal and current core fence denial.

**Missing adverse cases:**

- Wrong or absent workload identity on protected routes; spoofed browser identity/certificate headers must not confer workload authority.
- A role attempting another role's egress socket or protected credential access under the actual deployment's custody and kernel peer checks.
- An unauthorized connector/source attempting the protected PostgreSQL path, with evidence of effective enforcement rather than the policy manifest alone.
- An expired SVID attempting a new request and, where applicable, continued disclosure over an already open connection. Natural renewal proves fresh issuance; it does not demonstrate rejection of the expired leaf.

**Closure:** retain a route/source/custody test matrix with expected allow/deny, actual result and absence of protected bytes/effects for denied cases. Use scoped IMP-03 fault/probe resources; a shared issuer outage would also affect IMP-02 and is not a prerequisite to these observations.

### 6. Intermittent pre-readiness failures — automated diagnosis and regression

Audit attempt001 returned403 during UI conversation creation; attempt002 timed out before barrier readiness. Neither applied the audit fault. Attempt003 passed. Normal attempt009 also saw503 immediately after replacement; subsequent complete normal/phase runs passed.

**Closure:** reproduce with safe progress/timing metadata, identify the failing boundary and canonical error, and determine whether the cause is application behavior, readiness, authentication timing or the harness. Correct a confirmed defect and add a relevant regression, or document supported readiness conditions with evidence. A later pass alone does not explain the earlier failures; no root cause is currently established.

### 7. Operational measurements and shutdown/recovery — automatable with reviewed criteria

**Already observed:** one five-role resource sample, ten verified health round trips (~3ms median), and a scoped core stop/start preserving its container/volumes while help/static returned200. The stop returned241, consistent with the recorded SIGTERM propagation; clean zero-exit shutdown was not certified.

**Closure:** define the workload, concurrency, duration and review criteria before assessing results; measure representative protected actor operations/streams and resource behavior, including dependency loss. Observe shutdown with active channels/in-flight commands, truthful client disconnect/unknown state, operation reconciliation, durable-state preservation and restart behavior without rewinding rights or restrictions. Keep health timing separate from protected-operation latency. Fuller trusted serving recovery remains IMP-09.

Numerical acceptance limits require a stated basis; the existing samples do not supply them.

### 8. Human usability/accessibility review — human work supported by automation

Review participant, worker and supervisor journeys in English and French. Cover wording/disclosures, keyboard-only operation, focus and error recovery, screen-reader announcements, unsent text through reauthentication, and truthful queued/unconnected/disconnected/pending/unknown states.

**Closure:** record the actual reviewer, interface/candidate, scenarios, observations, defects and resolutions or explicit bounded limitations. Automated checks can support keyboard/focus/semantic regressions; they do not supply a human screen-reader, language-comprehension or usability decision.

### 9. Final packet and G-03 decision — automated assembly, human acceptance

The current packet is a draft with exact source/artifact/configuration bindings and passed scripted observations. It has no G-03 human decision.

**Closure:** refresh the packet for the final candidate, include additional evidence and unresolved limitations, validate digests and present the actual demonstration and bounded acceptance scope. Follow the [human-decision procedure](../../../../06-demonstrations-and-human-decisions.md): the actual response may be `accept_stage`, `request_changes`, `defer` or `reject`, with attribution, timestamp, reviewed packet/candidate and constraints recorded. Update the execution ledger only after actual acceptance. Neither test success nor Option B deployment approval supplies that decision. Participant admission and IMP-04 remain separate authority.

### Practical order for continuation

1. Preserve the current generation1 restricted target and its evidence. Prepare a separately scoped fresh IMP-03 serving target or reviewed continuation design; the current core cannot supply the required positive preconditions. This can still share the Option B infrastructure. Do not reset its fence or replay initial-only provisioning. The privileged seed/provisioning supervisors have been removed.
2. Resolve the deployment-profile direction and browser trust, then diagnose the intermittent startup/readiness failures.
3. Extend live actor/race/revocation/DB-ack/capture cases and audit/output/negative-control observations. Group them before the final one-way fence so the next target remains usable for positive tests.
4. Complete operational and human reviews, bind the final evidence and present the actual G-03 decision.

Synthetic demo only. No police integration, autonomous contact, production/clinical qualification, commit or push occurred. Existing IMP-02 changes were confined to the specifically approved certificate renewal/reload/restarts and additive Option B resources; final certificate/process/Secret verification passed.
