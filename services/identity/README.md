# Private identity source candidate

This package implements the IMP-02 identity authority with explicit provider,
store, encryption and signing dependencies. `create_app()` is deliberately
unconfigured and denies private operations. No accounts, database, listener,
Keycloak realm, certificate, model or workload issuer is created on import.

Use the root locked setup/check commands. The package exports `IdentityService`,
`OIDCProvider`/`OIDCConfig`, `PostgresStore`, `Custody`, `ReceiptSigner`,
`SignalReceiver` and `create_app`. The composition root must supply a separately
credentialled identity PostgreSQL DSN with `sslmode=verify-full` and a pinned
`sslrootcert`, a verified-TLS HTTP client, fixed HTTPS provider endpoints, encrypted
custody key and Ed25519 signing key from protected mounted files. No business DB
credential belongs here. `migrations/001_identity.sql` creates initial custody;
`002_option_b_and_workload.sql` adds typed lifecycle/restriction checks and indexes.
The coordinator-owned lab runner applies exact digest-bound migrations. These
files do not themselves provision real roles or prove live database behavior.

OIDC code exchange uses PKCE S256, one-use browser-bound intents, pinned issuer
endpoints, asymmetric RS256 JWKS keys, signature/issuer/audience/azp/nonce/time
checks and a separately validated access token with a distinct resource audience.
The exact public JOSE type is pinned by `access_token_type` (default `at+jwt`;
explicit `JWT` supports the admitted Keycloak profile). Opaque tokens, unconfigured
types and ID-token/resource audience reuse deny. The profile still needs actual
provider qualification; configuring a type does not relax signatures or MFA. JWKS expire
at 300 seconds, unknown keys refresh under a single-flight lock, and failed key
fetches cannot validate an unknown key. Callback query/header/credential logging
must be disabled by the actual host proxy/server configuration.

Provider groups never provision roles. `IdentityService.provision()` is an
explicit offline composition/tool hook, absent from HTTP routes; it requires
separate operator authorization before use. Workforce sessions require a local
entitlement plus verified MFA. Every private session/help operation checks fresh
provider status and local account/session revisions at its final boundary.
Provider introspection and local commits remain distinct systems; upstream
revocation is not claimed atomic or instantaneous. Sign-out fences the local
session independently of provider availability and records pending upstream
revocation separately. The small lab PostgreSQL adapter serializes short state
transactions with an advisory lock; it holds no lock over provider I/O.

`/v1/auth/*` follows the LLD DTOs. Browser sessions use Secure/HttpOnly/SameSite=Lax
host-only cookies. Mutations require exact configured Origin, JSON, and CSRF.
The provider's GET callback uses state/browser binding instead of CSRF headers.
JSON callers receive `BrowserSession`; browser `Accept: text/html` callers may
receive a 303 to the single fixed same-origin `ui_return_url` after validation.
Caller redirect URLs are never accepted. Main/help factory instances must use
separate origins, OIDC clients/callbacks and cookies; the main default is
`__Host-care-link-session`, the help convention is `__Host-care_link_help`.

Small BFF metadata extensions support the browser without persistent token
storage: GET `/v1/auth/csrf` returns `BrowserCsrf`; GET `/v1/auth/session` may expose
a same-session `X-Ceremony-Id`; GET `/v1/auth/step-up/proof?ceremony_id=<uuid>`
returns `StepUpProof` only to that current session. CSRF retrieval is local-only
metadata so protective sign-out remains possible during provider outage; it
never grants current service authority. High-assurance ceremonies bind exact
purpose/resource/revision. Export/delete/identity-link require first MFA, five
minutes of cooling, and a distinct second MFA authenticated after cooling.
Confirmation produces an action-bound verified ceremony, never ambient AL3.
Successful login and step-up callbacks rotate the server session and CSRF secret,
locally fencing the exact previous browser session in the same transaction.
Step-up rebinds only its matching ceremony/proof; other stale references deny.
Failed callbacks and unrelated browser bindings do not revoke another session.
Successful replacement callbacks renew the validated binding cookie alongside
the session. Local CSRF bootstrap can restore missing/mismatched binding metadata
for the same stored origin/session, without granting fresh service authority.

Host help adapters use `browser_context(raw_cookie) -> {account_id, role,
csrf_token}` and `issue_help_proof(raw_cookie, exact_help_origin) -> UUID`;
`help_authorize(HelpAuthorityRequest)` consumes the proof once and emits a
one-second request-specific signed `FreshHelpAuthority`. The signature is
Ed25519 over UTF-8 JSON with sorted keys, compact separators, `ensure_ascii=False`,
excluding `signature`; its wire signature is unpadded base64url. Issuer is
`care-link-identity`, audience `care-link-help`, and `one_use_nonce` echoes the
request nonce. Worker/supervisor entitlement plus MFA is required for acceptance.
Reconciliation is explicitly unadmitted until the core import authority exists.

Internal `/internal/v1/identity/{help-authorize,signals,help-browser-context,
help-browser-proof}` routes require an injected per-request authenticated peer
and current fence verifier; the default denies every call. The context/proof
adapter routes read X-Help-Session/X-Help-Origin only after that verifier accepts
the help workload. These headers never establish workload identity. Applications
must run behind a permission-restricted proxy socket with attested mTLS identities;
constructing a FastAPI factory is not that transport proof. No permissive fallback
verifier or public-header identity parser is provided.

Signed local signals verify exact issuer/audience/digest/signature/age and
monotone per-subject sequence. Account notifications remove rights. Configured
`WorkloadSignals` handles workload-compromise events through release-configured,
immutable UUID→SPIFFE bindings and the typed `RestrictiveFence` port. Unknown
mappings deny without account mutation. Identity stores pending intent before the
host call; only a matching fsync-confirmed receipt permits sequence ACK. Lost
host or DB acknowledgements reconcile by the same command ID. Stale/gapped events
fence without advancing the head; signed jti conflicts quarantine/fence the mapped
source. No endpoint releases a fence. Missing workload configuration denies. This
custom protocol makes no SSF/CAEP conformance or IMP-03 global-journal claim.

Option B ownership/custody/operator labels are main, per the actual user decision.
They do not manufacture runtime operator rights or independent humans.
`SessionRetentionAuthority` requires the configured actual main account, current
operator-role MFA session and recent provider proof. It issues one-second
`RetentionGrant` values; every protected lifecycle mutation rechecks exact local
session/account/role revisions and expiry in its own DB transaction. No public
retention-admin bypass route is introduced.

`RetentionService` immediately disables a deprovisioned account, increments rights
revisions, clears its server credentials and fences linked ceremonies/proofs.
Provider cleanup is a separate idempotent pending operation; absent/outage
Keycloak authority never becomes completed cleanup. Reusable accounts require
30-day access reviews; missing/overdue review denies access. Identifying profile
fields are removed at the 30-day deprovision anchor, with provider/copy exceptions
reported under owner/reason/review dates. Security and minimal audit payloads use
their distinct 30/90-day event anchors. Reviewer evidence remains while dependencies
exist and for90days after the final dependency ends. Holds do not silently expire;
overdue review is visible and authority is rechecked before release. Removed
payloads retain only minimal copy-accounting restriction metadata pending evidence.
Protocol credential disposal and expired metadata maintenance are explicit
restriction-only methods for the qualified operator/job composition.
Credential disposal uses current local account/issuer restrictions, role/revision
changes and privileged900second inactivity, including session-bound positive
proofs/intents/ceremonies. It never treats a provider outage alone as revocation.
Owner-review recovery proofs likewise lose their encrypted bearer on local
restrictions, while an overdue review alone remains eligible for that narrow
recovery. Non-authorizing CSRF metadata supports a fresh bound login afterward.
Absent disposed bearers cannot create a false confirmed provider-revocation claim.

`KeycloakCleanup` calls only the fixed admitted realm's exact user disable/logout/
delete endpoints with separately scoped fresh service credentials. The bootstrap
client permits only named-lab user-management scope. `EncryptedIdentityBackups`
creates actual Fernet-encrypted logical metadata captures, excluding bearer and
ceremony state, under0700/0600 custody. Capture inventory precedes file+directory
fsync; stable capture IDs reconcile lost replies without refreshing capture dates.
Expiry is immutable capture+7days, serialized with writers, and reports unlink
rather than physical erasure. Custody IDs prevent one directory from expiring
another's captures. Profile cleanup remains backup-pending until all declared
profile-bearing copies are accounted for. New captures of negative-only metadata
do not restart the deleted profile's window. This adapter owns its explicit local
custody scope; unknown/foreign copies deny complete clearance. It is not a physical
PostgreSQL/WAL backup or IMP-09 recovery-serving proof.

`expire()` also invokes `minimize_terminal_inventory()` under the same declared
custody. After actual file unlink plus90days, terminal inventory drops plaintext
account/profile-account lists only when current holds, dependencies, outstanding
copies and provider/copy reconciliation are accounted for. Legacy unknown unlink
anchors stay pending. A minimal capture/filename/ciphertext-digest restriction
marker remains with main ownership, reason and30day review date; stable capture
IDs cannot renew it. A returned terminal filename globally denies copy clearance,
even after account links are gone. This does not claim physical database/WAL or
external-copy erasure.

Restore always produces quarantined metadata: no sessions, intents, proofs,
ceremonies, pending commands or cleanup secrets revive; current purge/hold/fence
markers take precedence and positive account grants remain suspended. Capture
expiry is checked without renewal. There is no automatic serving promotion.

Coordinator-run `tools/imp02_application/provider_bootstrap.py` prepares only the
named disposable Keycloak realm and external private credentials. It configures
actual password+TOTP execution references and the built-in AMR mapper, never a
hardcoded MFA claim. All test profiles are explicitly the owner role-playing
separate scoped accounts. `identity_qualification.py` applies exact source
migrations and can exercise real PostgreSQL/provider cleanup and encrypted files
with clearly labelled temporal fixtures. These tools are not executed on import.

Tests use a clearly isolated in-memory store/provider fixture and real RSA/
Ed25519 cryptography through mock HTTP transport. They cover callback races,
wrong claims/keys/flows, MFA/entitlement denial, timeout uncertainty, fresh-current
checks and expiry races, help replay/outage, restrictive signals and cooling.
Unit fixtures do not prove actual Keycloak MFA/recovery, PostgreSQL durability/
roles/TLS, SPIRE attestation/rotation or Envoy/CNI/host isolation. Coordinator-run
live evidence is recorded separately; no test count invents independent content
review or browser language/accessibility acceptance. The selected account policy
is implemented without applying synthetic TTLs to real metadata. Participant
admission remains false in liveness metadata.
