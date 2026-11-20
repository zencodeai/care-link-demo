# Proposed deployment changes — DEPLOY-IMP04-002

**Proposed, not applied.** The current user instruction authorizes this packet and read-only inspection. It specifically requires presentation of exact changes before application. This document is the reviewable deployment scope; it does not authorize mutation. The application source remains the unchanged, uncommitted session001 candidate on `feat/imp-04-plans-consent-directory`, baseline `a91087350306cf847ade2479c9ad05542c9d3adb`.

## Accepted environment to preserve

G-03 is accepted and closed according to `doc/IMP/executions/2026-11-16-IMP-03/ledger.json`, which supersedes earlier session003 pending-gate statements. Its accepted application image is `sha256:e854ff2799a235ac827439637ec06b7e5680b286561b1cc4fbbebc0580689de7`; environment `imp03-review`; presented run `8135ccd8-427c-4b10-a950-9d316771e68d`. The current metadata inventory shows the five continuation application containers running that image.

Preserve all original and continuation containers, images/tags, volumes, networks, DBs, journal/fence state, conversations, accounts, credentials, browser profiles, operator custody and active review run. Do not rerun initial provisioning, reset fences, reconcile old realms, restart accepted agents, or refresh/replace accepted trust roots. Do not run the old operator with a new environment variable: it accepts only two IMP-03 profiles and contains fixed target assumptions.

The separate IMP-02 kind/SPIRE/Keycloak/help/static substrate is also protected. No Kubernetes resource, SPIRE registration or Keycloak realm on that substrate will be created, updated or removed by this proposal. No sibling repository is touched.

## Resource additions

Exact names and per-container limits are in [target-proposal.json](target-proposal.json). All new Docker resources carry `care-link.scope=imp04-002` and a fresh creation nonce recorded outside Git; subsequent operations bind inspected resource IDs as well as those labels. Existing names are an error, never adoptable state.

| Resource | Proposed addition |
|---|---|
| Environment/prefix | `imp04-plans-002` / `care-link-imp04-002` |
| Private operator inputs | `/private/tmp/care-link-imp04-002`, directory0700, files0600, no symlinks; no accepted custody read/copy |
| Mesh bridge | `care-link-imp04-002-mesh`, `172.29.44.0/24`, internal, isolated gateway mode; peer TCP permitted and protected by mTLS/route allowlists |
| Database bridge | `care-link-imp04-002-database`, `172.29.45.0/24`, internal; dedicated PostgreSQL and exact connectors/provider |
| Authority bridge | `care-link-imp04-002-infrastructure`, `172.29.46.0/24`, internal; dedicated SPIRE server, five agents, provider connector |
| Published-ingress bridge | `care-link-imp04-002-ingress`, `172.29.47.0/24`; only new ingress, provider and qualification browser |
| Application HTTPS | `https://plans.localhost:30443`, publish `127.0.0.1:30443` only |
| Provider HTTPS | `https://id.plans.localhost:31443`, publish `127.0.0.1:31443` only |
| PostgreSQL diagnostics | `127.0.0.1:25436` → new PostgreSQL5432, verify-full TLS and separately issued credentials |
| Private browser broker | `127.0.0.1:30900` → new browser29900; private capability, never in Git/evidence |
| Application roles | Five each of `identity/core/data/pdp/journal` app, Envoy proxy, authorization process and SPIRE agent |
| Other containers | Dedicated SPIRE server, PostgreSQL, Keycloak, fence, three connector relays, ingress, browser; two stopped initial-only seed containers |
| Persistent volumes | 48 explicitly enumerated new volumes: 13 infrastructure/custody volumes plus seven per role |

The read-only inventory found no Docker resources with this prefix and no overlap with the four proposed subnets. A local listener query found no listeners on the four proposed ports. These observations are time-bound, not reservations; recheck immediately before creation. Check port ownership, VPN routes and subnet collisions as well as Docker IPAM.

The five role proxy addresses are `172.29.44.11`–`.15`. Each app and authorization process has `network=none`; only its role-specific Unix sockets/public inputs are mounted. Each proxy joins its corresponding agent PID namespace so Unix UID attestation remains meaningful. Each agent has its own Workload API socket volume. App UIDs22011–22015, authorization UIDs22031–22035, proxy UID22002, fence UID22000, restriction UID22001 and reader GID22999 retain the accepted custody pattern, inside separate containers/volumes. No host PID/network mode, privileged container, Docker socket mount or accepted volume/network is permitted. Initial seed processes may use only CHOWN/DAC_OVERRIDE against the new volume set; they stop before serving.

Container-internal `/run/care-link-imp03-002` paths and protocol session `imp03-002` remain for compatibility with the existing protected runtime. They do not select host resources. DB names, volumes, provider, roots, journal and Docker identities are explicitly IMP-04. No credential path may resolve into accepted custody.

## Independent trust and provider

Create a dedicated SPIRE server from the pinned source input in [artifact bindings](artifact-bindings.json). Its private server data holds its own SQLite registry and disk signing keys; enable only join-token node attestation for this Docker target. Do not install Kubernetes PSAT/RBAC/CSI. Server8081 is private on `172.29.46.10`.

Create five new parent identities `spiffe://care-link.demo/host/imp04-002-<role>` and exact `unix:uid:22002` workload registrations beneath their respective agent/PID namespaces. Join tokens expire after600s; workload SVIDs after300s. Preserve agent identity in owned persistent custody across restarts, or explicitly re-enrol the same inspected new target under a new receipt. Do not restart an agent that lost a memory-only key using a consumed join token.

Logical workload IDs remain `spiffe://care-link.demo/demo/<role>`, as required by the unchanged signed policy and delegation verifier. Isolation depends on **independent signing roots and disjoint bundles**. Neither environment may import the other's authority. The new trust steward reads only its new SPIRE server, caps upstream TLS pools at60s and refreshes only its five new authorizers. Exact current-route and fence enforcement remains active. Negative qualification must prove a foreign certificate chain with the same logical name is rejected.

Create a dedicated Keycloak instance using the verified local optimized runtime image ID `sha256:eb16e701be9e124e7d7a35ce00a8a86bef7d15ed63a262c7f3ec770cda846918` (or a separately bound rebuild from the pinned Keycloak Dockerfile), its own `imp04_provider_002` database/login and data/config volumes. Create realm `care-link-imp04-002`, confidential browser client `care-link-imp04-002-browser`, audience `care-link-imp04-002-resource` and exact redirect `https://plans.localhost:30443/v1/auth/callback`. Provider user, application account and principal IDs are newly issued, separately recorded and matched; they are not copied from accepted actors.

Use the ordinary App, with no `review_contexts_file`. Create nine distinct accounts: PID, second PID, carer, professional participant, worker1, worker2, supervisor, operator and security. Each has its own username, account UUID, provider subject and password/TOTP. The last two use actual authenticated API journeys for source ingest/suspension; no admin UI is claimed. Each account uses a separate browser profile/context/cookie jar, avoiding provider SSO crossover. The existing four-slot review toolkit is not used or modified.

Issue a new transport CA and leaves for `plans.localhost`, `id.plans.localhost` and `postgres.imp04.internal`. Configure DB/provider clients with verify-full/pinned CA verification. No host trust-store or DNS edit is proposed. Trust the new CA only in the new browser NSS profile; verify native certificate trust with `ignoreHTTPSErrors:false` and no certificate-error switches. The browser can resolve the loopback names via its dedicated configuration. Native human-review browser setup must receive the same scoped CA/profile; ordinary Chrome outside it is not claimed ready. Record actual certificate/CA fingerprints and validity after issuance; no certificates are issued in this session.

## Migration and data changes

The fresh PostgreSQL instance creates three databases and distinct runtime credentials:

| Database | Login | Initial schema order |
|---|---|---|
| `imp04_identity_002` | `imp04_identity_runtime_002` | Identity001 then002 |
| `imp04_runtime_002` | `imp04_data_runtime_002` | Business001 then002 then003 |
| `imp04_provider_002` | `imp04_provider_runtime_002` | Keycloak initial schema under provider-owned login |

Names and every SQL file digest are in the JSON proposal/bindings. Migration003 SHA-256 is `295790c4df2c8ce600bd3362a82e43699118a8ac8889ba9074a4afdb77f3da42`. It adds `plans`, `consent`, `knowledge`; plan/field/review-work tables; current grants and immutable consent events; independently admitted delegations; immutable source versions, source guards and quarantine; exact grants, RLS and immutable-grant trigger; and plan retirement+30-day lifecycle anchors. It alters lifecycle check constraints only in the fresh IMP-04 database. It is not an IMP-03 migration.

Use initial-only migration-owner custody. Refuse existing databases, logins, NOLOGIN business group roles, journal or fence; retain partial state and receipts on failure. Apply each migration transactionally with an external digest receipt and verify postconditions before serving. Provider initialization may create its own schema only inside its separate DB. Business/identity runtime logins are NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOBYPASSRLS; business login inherits only `care_link_data_runtime`. Remove PUBLIC CONNECT/TEMP and public-schema CREATE as in the accepted pattern. Do not put migration/admin credentials in serving containers.

Qualify runtime denial of DDL, delegation writes and immutable-row UPDATE/DELETE. Metadata SELECT policies are not browser authorization; guarded current identity/subject/session/consent checks still control projection. Backups receive bounded read roles only. This packet does not assert backup/recovery/purge completion.

Create fresh journal/signing/content/cursor/custody keys, a new journal UUID and new generation0 fence. Bootstrap business guards from that journal head and the exact IMP-04 policy digest. No accepted DB, journal, restriction or conversation is imported. A future one-way restriction must remain durable; rollback cannot reset it.

For the delegation check, the new-target admin tool creates one exact record **after** the live PID subject exists: newly issued delegation UUID, that subject UUID, the carer's principal UUID, purpose `plan`, fields `[plan.strategies]`, expiry `recorded creation time + 10 minutes`, revoked_at null. Record actual IDs/time and confirm the tuple before insertion. No broad authority or runtime grant is added. A separate restriction-only action can set revoked_at for that exact record; it must acquire the same global/principal/subject guards as the product workflow and durably journal the restriction before the guarded database transition. This administrator path is not implemented; do not substitute arbitrary SQL during live qualification or widen runtime privileges. Natural expiry can be tested without it. No wall-clock adjustment is allowed.

## Policy, source and image inputs

Load `config/demo/imp04/policy/manual.rego`, exact digest `cc62534fcfaf302154ccb8e0aed6f386e7857e848354d8bb41d8d10177665604`, with its exact bootstrap signature/key. OPA Linux ARM64 executable must match `8fc1c524f93b4369eb207961aba213d990604205fc49fe3ba923dfc125c8a422`. Do not use the IMP-03 bootstrap. Policy signature establishes engineering integrity, not G-04 approval.

Render `directory_signed_admissions` from the seven exact fixture envelopes and `directory_trusted_keys` separately from `directory-source-key-pin.json`. Convert the independently pinned raw Ed25519 key to the PEM path expected by composition; never learn a pin from a feed. Exact source/pin file hashes and all feed artifact/source tuples are in [directory inventory](directory-inventory.json). Ingest through the real operator/PDP/gateway path, never INSERT serving versions directly.

The signed observations are fixed at November16 13:00 Toronto /18:00Z. Availability freshness ends13:05/18:05Z, operational freshness November17 13:00/18:00Z, structural freshness December16 13:00/18:00Z. At execution use current wall time. Old fixtures must produce stale/unknown results when appropriate while retaining their operating labels and explicit unavailable states. Fresh positive availability requires actual new synthetic observations, revisions and signed artifacts with an independently reviewed pin and a new candidate digest. Do not change timestamps or silently replace the discarded signing key.

Build a new `care-link-imp04:plans-002` application image from pinned Python/uv bases, current modular services/packages/tools and the new deployment adapter, adding `config/demo/imp04` alongside the retained manual-service disclosures. Keep tests/private inputs out of serving images using a new scoped dockerignore. This remains a qualification workspace distribution, not a claim of minimal per-role packaging.

Rebuild the UI with `VITE_OIDC_ORIGIN=https://id.plans.localhost:31443` and provenance naming `imp04-plans-002`. Help/static public origins remain the existing links; no IMP-04 identity/help integration or fallback qualification is claimed. No VITE secret is allowed. Session001's generic web build and accepted IMP-03 image are not this deployable artifact. Pin the new app/browser image IDs after build; verify files, provenance, entrypoints and excluded private/test content. The pinned SPIRE server/uv cache availability is unconfirmed; any acquisition must use the exact digests, without silently selecting newer images. The derived Keycloak reference in the source products manifest is local build provenance, not proof of a published Docker Hub repository: verify/run its immutable local image ID or rebuild the pinned recipe; do not try an assumed registry fallback.

## Required target tooling changes, before application

These are **proposed new files**, not files implemented in this session. Existing IMP-03 operators, toolkit and recipes remain unchanged.

| New owner/path | Required behavior |
|---|---|
| `tools/imp04_deployment/config.py` | Parse the exact target descriptor, reject unknown fields/collisions/accepted prefixes and credentials; validate target DB names, actor registry, independent pins, UID/socket/route custody |
| `tools/imp04_deployment/prepare.py` | Generate role-exclusive config/keys and explicit policy/admissions; separate public release manifest from private inputs; fresh-only atomic creation |
| `tools/imp04_deployment/provision.py` | Fresh-only three DBs/logins, exact identity/business migration order, account/principal mapping, journal/bootstrap; bounded delegation admission/restriction receipt |
| `tools/imp04_deployment/docker.py` and `deploy.py` | Enumerated names/IDs/nonces, per-resource mounts/networks/argv/limits, own provider/authority, fail on partial state, stop-only rollback; never broad delete/reconcile |
| `tools/imp04_deployment/trust.py` | Dedicated server/agent bootstrap, persistent agent key custody, own-bundle refresh and current readiness; no accepted authority access |
| `tools/imp04_deployment/web.py` | Explicit new provider origin, qualification provenance and digest-bound web build |
| `deploy/images/imp04/Dockerfile` and `.dockerignore` | Exact pinned bases, IMP-04 config and new tools, public web build, no private inputs/tests; new tags only |
| `tests/unit/imp04_deployment/**` | Accepted-resource refusal, all new DB/migration/role/pin cases, credential mount separation, partial failure and rollback behavior |
| `tests/e2e/imp04-live/**` | Nine ordinary isolated actor contexts, truthful raw outcome capture, accessibility and current-trust checks |
| Optional `tools/imp04_verification` final-output barrier adapter | Receipt-bound new-target instrumentation only; absent/default off in ordinary serving, exact phase/deadline/cleanup, no auth bypass; new image/source review if included |

The existing `Composition`, protected Unix serving, route rules and relay mechanisms may be reused as interfaces after target-specific preparation. Their internal session marker is retained. Do not call old `prepare`, `provision`, profile selection, provider setup or deployment helpers: they hard-code IMP-03 names, load the wrong policy, reject the additional actor roles/admission fields and omit business migrations002/003.

## Application sequence and rollback

1. Implement only the new scoped operator/build/verification assets above; review source diff and appropriate local tests. Freeze all source/policy/source-pin digests. No live target mutation yet.
2. Build the explicit web/application/browser candidates, inspect immutable IDs, produce the complete rendered per-resource creation plan with argv/mounts/UIDs/routes/network/TLS/public-config fingerprints. Private secrets remain outside that manifest. Rebind the draft DemoPacket; retain the source-only and preparation bindings as history.
3. Present the exact final patch, build IDs, rendered deployment digest, ownership and rollback for the user's deployment-change decision. Record their actual response separately. Approval of this preparation document must not be silently expanded to changed later artifacts.
4. Immediately before an authorized apply, recapture accepted container IDs/images/mount/network mappings, public fence/journal/health summaries and active run identity through read-only interfaces. Compare to the new resource allowlist. The accepted trust steward may legitimately refresh authorizers; record such observed changes without claiming deployment caused or fixed them. Abort on unexplained drift or inadequate memory/CPU/disk capacity. Do not stop/resize accepted services to create capacity.
5. Acquire only exact missing pinned inputs; create the listed networks/volumes and fresh authority/provider/DB. Issue credentials and retain private receipts. Render and migrate the new target only; stop seed processes. Start five roles with their exclusive mounts, then new ingress/browser. No accepted-service commands are needed.
6. Record actual roots/leaf validity, image/config IDs, account/subject bindings, journal and fence; perform current trust/default-deny/DB privilege checks before actor qualification. Compare the accepted environment after each phase. Execute [qualification-plan.md](qualification-plan.md), recording failures without weakening controls.
7. Present a fully bound demonstrated candidate for a separate G-04 human decision. Deployment permission never equals gate acceptance.

On any mismatch/failure, stop the inspected new ingress first, then only new-target processes that need containment. Retain new volumes, DB, journal, fence, private custody and evidence for diagnosis. IMP-03 continues at its existing links. Do not down-migrate003, restore old rights, reset fences, reuse partial databases or run Docker prune. Any later deletion requires its own exact receipt-bound resource list.

No runnable deployment command is supplied as if it already existed: the target adapter and built artifacts above are outstanding. This packet is complete for deployment-scope review; it is not yet an executable release authorization.
