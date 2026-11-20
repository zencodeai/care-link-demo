# IMP-04 live qualification procedure

**All live steps are not run.** This procedure and the draft [DemoPacket](demo-packet.json) prepare IMP-04-D/G-04. They do not report deployed outcomes. Session001's 813 Python/100 web tests remain source/adapter evidence, including explicit provider/mesh fixtures; do not relabel them as this candidate's live IdP/SVID/browser results.

The 22 canonical public/data operations remain allocated in `doc/IMP/implementation-plan.json`; plan create/read/append/retire, consent grant/read/revoke, directory search/read/ingest/suspend are exercised through the BFF and actual data routes below. Current own-report transport is the already documented narrow session001 addition. This packet does not alter REQ/HLD/LLD or activate IMP-05.

## Binding and evidence rules

Before qualification, record an immutable application/browser image ID, source patch/file manifest and web fingerprint, configuration/route/mount plan digest, policy/signature and independent source-key pin, certificate/root fingerprints, observed SVID identity/expiry/fence generation, new journal ID, exact actor account/subject mapping, fixture IDs/revisions and wall-clock start/end. The current `environment_digest` in the draft DemoPacket hashes the proposal only. Replace it with actual deployed environment evidence when issued; likewise rebind its build/configuration hashes. Do not fill missing live hashes with accepted IMP-03 artifacts or zero digests.

Each case below records expected versus observed HTTP/UI outcome, error/state code, stable request/operation ID, source/config/image binding, nonsecret effect counts and evidence SHA-256. Keep raw HTTP headers/cookies, provider responses/tokens, OTP seeds/passwords, private keys, broker capability, database rows containing synthetic narratives and raw screenshots/traces in owner-only custody. Publish redacted observations, hashes and selected safe screenshots only after inspection. Never store hidden model reasoning. Test actors are fictional and actor-owned content uses clearly fictional text.

Name future evidence `Qnn-<locale>-<attempt>.json` or `Ann-<attempt>.json` beneath a new execution session's evidence folder; include exact command/tool version where used, fixture/mock flags and any failure/retry. Retries receive new attempt IDs and retain prior outcomes. A `not_run` or failed check remains visible. No broad success summary may replace observed effects. An instrumentation-induced timeout/lock deadlock is a failed harness case, not successful revocation evidence.

## Preconditions and safe execution order

1. Complete the reviewed isolated tooling/build plan in [deployment-delta.md](deployment-delta.md) and obtain an actual deployment-change decision bound to the final rendered artifacts. This session has no deployment permission.
2. Recheck the new resource allowlist, capacity and collisions. Read accepted IMP-03 status without opening/closing its run, issuing OTPs, changing credentials, altering fences or restarting services. Record its metadata before/after deployment and after adverse checks. An unavailable accepted readiness endpoint is a finding, not authority to repair it.
3. Confirm all new roles are current under the independent new root; verify TLS natively, exact HTTPS origins/issuer/audience, ordinary App/no review context and per-actor browser isolation. Disable all optional fault barriers by default. Stop if source, key, policy, config, journal, fence or actor bindings disagree.
4. Run positive plan/sharing/report/directory journeys first. Use distinct grants/fields and stable operation keys for adverse cases. Run only one state/fault operator at a time. Use newly created test subjects/sessions on the new target; never borrow accepted conversations.
5. Run restrictive/irreversible tests last on separately identified synthetic records. Preserve their restrictions; no reset/revocation reversal to recover a green demo. Stop exact leased dependencies only; release every temporary pause in `finally`/operator cleanup and verify current trust afterward.

## Actor and authority setup

| Slot | Role and purpose | Must remain separate |
|---|---|---|
| pid | Own plan and self-consent ceremony | Own subject/persona and account |
| pid-other | Wrong-subject adversary | Different subject/account/provider subject |
| carer | Own reports; optional explicit delegation | Relationship label grants no PID rights |
| professional | `professional_participant`, own reports | Professional label grants no workforce status |
| worker1 | Exact assignment, scoped plan sharing/read/append | Workforce sign-in and fresh assurance |
| worker2 | Unassigned/other-recipient and inherited manual tests | Separate workforce account and cookie jar |
| supervisor | Inherited manual-service observe/takeover regression | Separate explicit supervisor authority |
| operator | Signed directory ingest API | No direct source-table seeding |
| security | Authoritative source suspension API | Cannot inherit authority from a UI selector |

No account UUID, provider subject or credential is issued by this document. The actual provisioner must publish only nonsecret mappings and privately retain credentials, with one exact role per account. API calls for operator/security use their genuine session/CSRF/assurance and ordinary BFF signature path; never forge a worker token or bypass the data gateway. No new governance super-user is needed.

PID self-consent uses the implemented subject-bound fresh `plan_edit` MFA ceremony. Observe ceremony completion against the same browser session/account and subject/purpose, then use that real proof reference. A prefilled UUID is not a proof. Independently provisioned delegation is a different basis: follow the exact bounded tuple and journal/guard restriction plan in the deployment delta, retain administrator evidence and prove runtime cannot write it.

## Normal cases

| Case | Actions and observable pass condition | Required evidence |
|---|---|---|
| Q01: deployment/trust binding | Native TLS with correct SAN/root; provider issuer/audience and session role verified; each protected hop has current proper SVID/route/fence; accepted target preserved | Public image/config/cert/root/SVID/fence/journal metadata; before/after accepted metadata; no credential dumps |
| Q02: separate accounts | Sign in each slot in a distinct profile/context; verify actual account/role; carer/professional use participant routes; same hostname has isolated cookie jars | Redacted account/role/assurance map and observed session endpoints |
| Q03: attributed plan | PID opens own fictional session, creates plan, appends warning signs/strategies/medication report. After exact assignment+share, worker appends scoped safety conflict; inspect attribution, disputed state and pending review | Stable logical keys, plan/field revisions, author IDs, review count; no overwritten source row |
| Q04: exact sharing | PID completes real MFA ceremony, previews worker1 + `plan.strategies` + purpose `plan` + explicit interval. Grant and read through worker1; inspect permitted projection and consent read | Grant scope hash/revisions/interval/basis; response contains strategies only, medication field absent |
| Q05: actor-owned reports | Carer and professional each create their own attributed report in their own session, reload and read saved reports | Author/subject/account binding; own reports persist and no other author's content appears |
| Q06: seven sourced states | Operator ingests each exact signed feed through real policy/gateway, then participant searches/reads in EN/FR; inspect provenance, operating state, qualifications and explicit alternative absence | Feed/service/source/revision/artifact tuples and actual current projection/freshness; no destination/send |
| Q07: lifecycle | Close support session; active plan remains. Retire that plan; read copy metadata through bounded read-only verification | Independent retirement anchor and retirement+30-day expiry; no claim of actual future purge/backups |
| Q08: accessibility | Run EN/FR positive/error/unknown/share/revoke/directory flows by keyboard; inspect labels, focus after step-up/errors, live regions, 200% zoom; axe scan plus manual screen-reader observations | Browser/axe/screen-reader versions, locale/viewport, each observation/failure; automated scan alone is insufficient |
| Q09: recovery/regression | Within the mounted page preserve unsent input during step-up and retry uncertain mutation using its same pending key; after full reload manually reselect recorded session/plan IDs and read committed work; duplicate request produces one effect; exercise new-target manual flow | Logical key/effect counts and visible state; no claim that pending keys/unsent drafts survive full reload; ordinary App does not qualify accepted ReviewApp restoration |

## Directory matrix and freshness

All fixtures are synthetic engineering candidates with `human_review:false` and `participant_admission:false`. Signed content binds source integrity, not independent review or availability. Their jurisdiction `CA-XX` is a fixture label, not validation of actual Ontario services.

| Operating label | Required visible qualification |
|---|---|
| `normal_operations` | Fictional normal operation; availability requires current evidence |
| `temporary_closure` | Explicitly unavailable; alternative or explicit absence |
| `regional_outage` | Explicitly unavailable; alternative or explicit absence |
| `holiday_hours` | Event-specific verification requirement; unknown if not current/verified |
| `severe_weather` | Weather-specific qualification and current evidence requirement |
| `api_failure` | API failure qualification; availability unknown, no fabricated fresh response |
| `conflicting_source` | Conflicting provenance visible; no silent selection of an unsupported availability claim |

Use the exact spellings in [directory-inventory.json](directory-inventory.json) as executable expectations; this table is explanatory. Each visible projection must retain its source kind/ID/revision/digest/observed time/verification, source state/expiry, available qualifications in both languages, police involvement unknown, and alternative ID or explicit none. Verify source owner/method and per-field freshness classes separately in the signed admission manifest. The current DirectoryView/UI does not expose those manifest-only fields; this packet does not claim they are visible. If visible owner/method or field classes are required at acceptance, record that product gap and review an explicit source/UI delta before changing the candidate. Fixed near-realtime freshness ends2026-11-16 18:05Z; after then these fixtures cannot demonstrate current positive availability. Operational evidence expires2026-11-17 18:00Z; structural2026-12-16 18:00Z. Future real wall-clock observations decide freshness; never freeze/rewind time to make a live check pass.

The baseline candidate can qualify truthful stale/unknown display for all seven labels. If positive freshness is required for the G-04 demonstration, first produce genuinely reobserved synthetic source revisions and new signed manifests, independently establish/approve the new key pin if necessary, review the exact new hashes and rebind the candidate. The original fixture signing key was discarded; this packet does not authorize pin replacement or invent re-verification. Record the positive freshness case as not_run until that evidence exists.

## Adverse cases

| Case | Actions and observable pass condition | Required evidence |
|---|---|---|
| A01: ownership/role | Direct API attempts against unshared PID plan, wrong subject/author, unassigned worker and browser-role mutation | Authorization denies with no protected content; role labels alone confer no rights |
| A02: exact fields/time | Request medication outside strategies grant; expire wider grant while narrower strategies grant survives; retry after wall-clock expiry | Every returned field covered by current surviving grants; medication absent and expired-only read denied |
| A03: pending output | Independently hold real live output immediately before final authorization/release, then revoke/expire/change role/delegation; release request | Barrier entered/restriction committed/final check/output timestamps, exact operation IDs, zero newly forbidden bytes |
| A04: missing-grant race | Concurrent real requests on same absent grant scope, distinct connections and stable keys | Subject guard serialization and exact durable effect/audit counts; no unguarded absence authorization |
| A05: delegation | Carer fails without delegation, succeeds only within provisioned exact tuple, fails on outside-purpose/field/subject/expiry/revocation | Read-only runtime DB rights; separately issued delegation receipt and product current checks |
| A06: admission/suspension | Modify feed/signature/unknown key; participant attempts ingest/suspend; security suspends admitted service then operator tries later ingest | Rejected digest quarantined; permitted versions immutable; suspension remains authoritative; exact audit/source records |
| A07: workload/network | No/expired/wrong role SVID, foreign root with same logical identity, direct backend and cross-role DB/egress probes | Current default deny, root isolation, UID/socket enforcement and no credential mount escape |
| A08: dependency loss | Pause only new receipt-bound identity, PDP, journal in separate attempts; always resume; verify current state after | Fail-closed/unknown outcomes within deadlines; no positive cache/fallback permission; no accepted pauses |
| A09: DB privilege | As the actual runtime login try DDL, delegation INSERT/UPDATE/DELETE and immutable field/event/source UPDATE/DELETE; test session RLS | Permission/trigger/RLS failures and no unauthorized durable row changes; no admin credential in role mounts |

For A07, do not extract an accepted private key or reconfigure an accepted proxy to perform a negative test. Compare the public accepted/new root fingerprints, verify the new bundle contains only its root, and use a new diagnostic foreign CA/credential with the same logical role name for a live handshake. A public accepted certificate-chain verification probe can supplement this when available without credential access. Record exactly which variant ran; a synthetic foreign CA is not a live accepted-workload certificate test.

For A03/A04, existing session001 tests use controlled adapters/clock injection; the inherited live dependency barrier does not pause consent projection. There is currently **no implemented deterministic live consent-release barrier**. Before claiming the pending-output race, implement/review an expiring, one-shot, target/operation/phase-bound test adapter that does not change auth inputs, clock, policy or release decisions. It must avoid holding the subject lock while waiting for revocation, or explicitly prove the lock/release ordering being tested. Fail closed on timeout and remove the barrier capability after qualification/rebuild, then rebind the resulting serving artifact. Until then A03/A04 remain not_run live; randomized concurrency is supplementary evidence only. Already disclosed bytes cannot be recalled and must not be counted as a post-revocation failure.

For A08, an ordinary new-target dependency SIGSTOP must be scoped by container ID, process birth/UID/argv/root receipt and an expiry; never locate processes by broad names. On a permanent new-target fence restriction, preserve it and end that test candidate. No restriction is cleared to continue review.

## Evidence completion and human decision

The coordinator reconciles source/automated/native/live results, retains failures and creates an actual deployed candidate manifest and evidence manifest. A read-only reviewer checks current source/image/configuration binding, all critical adverse evidence and accepted-environment preservation. Missing fresh-source, race, native accessibility or trust evidence remains listed; do not turn a scripted UI pass into those claims.

Only then present the demonstrated candidate to the user with exact fields/recipients/purposes/time limits, the seven source states and current limitations. Record their actual G-04 response using the HumanDecision contract and DemoPacket digest. No decision file is fabricated now. G-04 remains pending; no real participant admission, production/clinical certification, next slice, commit or push follows from this packet.
