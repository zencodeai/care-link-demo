# Shared IMP-03 qualification profiles

The original-target paragraphs below describe the historical Option B checkpoint.
For the current target use the continuation section and session003 handoff.

Session003 explicitly selected Option B: reuse the existing IMP-02 SPIRE server,
Keycloak and PostgreSQL processes, while issuing fresh IMP-03 actor/workload
identities and initializing separate databases, credentials, custody and fence.
This is the authorized exception to the source launcher's independent-instance
prerequisite, recorded in the session003 work packet. It does not amend the
architectural normal Kubernetes placement or establish G-03 acceptance.

The applications run in five capless, network-disabled Docker containers. Only
their own protected Unix backend/egress/configuration volumes are mounted.
Fixed relays carry end-to-end verified PostgreSQL/provider TLS through scoped
connectors. Role proxies use an internal isolated bridge, separate per-role
SPIRE agents and exact Unix-UID selectors beneath distinct parent identities.
The trusted ingress publishes only `127.0.0.1:28443`. The journal/fence live in
separate Docker volumes outside kind. The shared workspace image includes all
packages: this does not establish per-role package isolation, Kubernetes/CNI
enforcement, or image-selector attestation.

Private state is under `/private/tmp/care-link-imp03-003-shared` (0700/0600).
It includes provider actors/passwords/OTP secrets, bootstrap inputs, rollback
material and browser outputs. Never copy those into source or public evidence.
Browser tests currently use a temporary CA exception; backend TLS retains full
CA/hostname validation. Installing the private Playwright cache changes neither
system browsers nor host trust. Runtime wire/config lease `imp03-002` is retained
for compatibility; this work belongs to session003.

`operator` actions are **initial-only**, not restart commands. Do not rerun
`issue`, `prepare-volumes`, `dependencies`, `provision` or `applications` against
the existing deployment. Resource collisions/partial failures require exact
inspection, never adoption/reset. The original certificate maintenance completed;
use `tls_apply.verify` for checks, never replay apply/resume.

For an already bound, serving target, one reversible phase is:

```sh
.venv/bin/python -m tools.imp03_shared.qualification --phase pdp-loss --attempt 1
```

Use a fresh attempt number; existing output is refused. Supported phases are
identity, PDP and journal process loss, and the exact new database's audit grant
loss. The browser signs in before readiness, prepares CSRF, then the operator
pauses the receipt-bound process or revokes only the new audit grant. The browser
must observe the intended GET and POST denials. Read-only, journal-bound database
snapshots compare all core/workforce/access/lifecycle/control rows and committed
operation counts before/after, while the barrier remains active. Hashes/counts
leave the custodian; contents do not. Cleanup restores the exact dependency even
on failure. A pre-readiness failure applies no fault. No shared-service outage is
part of these phases.

The `fenced` phase is the guide's separate final operation. It requires generation
zero and a separate UID22001 custodian, and permanently restricts the new core
identity. It has no unfence/reset command. Session003 has completed it and retained
generation1; do not rerun against that fence. The two privileged seed supervisors
were removed afterward, so further database snapshots/reversible phases also need
a newly scoped supervisor. See the current handoff before any live operation.


## Current continuation profile

Set `CARE_LINK_IMP03_PROFILE=continuation-001` **before importing** these modules.
Only the original and this explicit profile are allowed; arbitrary resource scopes
are refused. Prefix `care-link-imp03-003-cont1-*`, private root
`/private/tmp/care-link-imp03-003-cont1`, main29443, PostgreSQL25435, browser29900.
Existing SPIRE/Keycloak are reused; a new disposable PostgreSQL process preserves
fixed-name fresh-only invariants. Four app actors include two issued workers.
The original core fence remains1; continuation remains0 and usable for review.
Both privileged bootstrap containers have been removed. Do not replay setup.

`continuation_browser` coordinates exact readiness, scoped commit/ACL barriers,
full31-table/eight-schema comparisons and real journal-bound audit validation.
`continuation_evidence` implements consistent encrypted capture/import to a fresh
quarantine DB with disabled principals/tokens and runtime CONNECT denial.
`negative` executes actual kernel custody, wrong DB source and mTLS probes;
`expiry_setup` is initial-only and must not be rerun over retained aliases.
`operations` performs a supervised active-channel core stop/start and bounded
protected-read measurements. Current command forms, for a newly scoped run with
fresh attempt numbers and its required supervisor, are:

```sh
CARE_LINK_IMP03_PROFILE=continuation-001 .venv/bin/python -m tools.imp03_shared.continuation_browser pdp-loss --attempt 3
CARE_LINK_IMP03_PROFILE=continuation-001 .venv/bin/python -m tools.imp03_shared.operations --attempt 3
```

These commands are examples, not automatic operations in this documentation.
Capture/revocation alter durable state; inspect the handoff and exact lease first.
ACL restriction remains in force; it is an operator fault, not a journalled
product rights workflow. The real-commit/lost-driver-ack capability requires the
exact explicit data-app environment flag and owner-only expiring one-shot marker;
it is **disabled in the retained runtime**. Default deployment never enables it.
A driver error after real commit is not wire-level COMMIT-packet loss.

The remote browser uses private `browser-server.json`, scoped NSS roots and
`ignoreHTTPSErrors:false`; `continuation_browser.environment` supplies the private
endpoint and process-only CA settings without exposing them in public records.
The old `Browser CA exception` observation does not apply to continuation evidence.
No host DNS/global trust change was made. See [browser image](../../deploy/images/imp03-browser/README.md)
and [extended cases](../../tests/e2e/imp03-extended/README.md).

Final source, actual deployed image variants and runtime custody are separately
bound in session003 `continuation-*` records. Common workspace packages and
parent/UID selectors remain deployment differences; exclusions now remove tests
from all three serving image variants. These checks provide no human G-03 decision.


## Qualification web build

Before building this qualification image, run the explicit profile builder:

```sh
CARE_LINK_IMP03_PROFILE=continuation-001 .venv/bin/python -m tools.imp03_shared.web
```

It supplies the reviewed public provider/help/static origins from
`config/demo/imp03/web-origins.json` to Vite, and writes public build provenance
`qualification-origins.json`. The qualification Dockerfile refuses a generic
source-check build without this provenance. A generic `tools/check.py` build
clears that file, so run the qualification builder again before Docker build.
Never place credentials, OTP seeds or tokens in VITE variables; these values are
public browser configuration. URL validation still rejects an unexpected
provider origin. Extended live sign-in now uses the visible Main account role
selector and Sign in button rather than obtaining a navigation URL via test API.


## Continuation trust-bundle maintenance

Authorization services load the public SPIRE bundle at startup. SPIRE authority
rotation can therefore outlive the static copy even while Envoy SDS renews leaf
credentials. Before a later human-review session, refresh only the continuation
copies from the exact existing SPIRE server:

```sh
CARE_LINK_IMP03_PROFILE=continuation-001 .venv/bin/python -m tools.imp03_shared.trust_refresh
```

The helper uses the verified existing kind node’s local Kubernetes client,
backs up each changed public bundle privately, atomically replaces it as its
existing authorization UID and restarts only that authorizer. An unchanged
bundle causes no restart. No issuer-policy, actor permission, shared-service,
agent or fence change occurs. Automatic continuous bundle synchronization is
not implemented; repeat after an authority rotation before further review.
Do not restart memory-backed SPIRE agents using consumed join tokens.


## Bounded maintenance during the current human review

Repeated authority rotation exposed that one manual bundle refresh does not
sustain a long review. A host operator may use `trust_refresh --watch-seconds
14400 --interval-seconds 30` with the explicit continuation profile. It is
bounded to four hours, writes owner-only PID/JSONL receipts, refreshes only
public bundles from the verified existing authority and never relaxes
verification on a failure. No OS service is installed. Check its receipt and
last successful log entry before continuing after that interval; it is not a
permanent lifecycle controller.

`pool_refresh` applies only the rendered upstream TLS pool lifetime to the
five existing continuation proxies. It archives old public configurations
privately and validates all five candidates using the pinned Envoy before
replacing files/restarting those same proxy containers. Runtime mesh rendering
now caps upstream pool age at the smaller of60s and one third of the configured
SVID lifetime. The current300s configuration therefore uses60s. Identity route,
SDS, per-request expiry/fence checks, credential custody and issuer policy stay
in force. Old pooled connections continuing after expiry are denied; the pool
bound obtains fresh handshakes instead of changing that denial rule.
