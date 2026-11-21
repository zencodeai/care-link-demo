# IMP-08 implementation notes

Current authorization: “Implement service slice 08”. Baseline 83406f94014ca3cc71f870b3b8c771841c6e83f9, existing feat/imp-07-followup-and-rights branch. Existing untracked research resources excluded. Source changes and owned disposable synthetic verification only; no publication, commit, push, deployment, model loading or host trust changes.

## Scope and integration

Tasks IMP-08-A/B/C/D and all 30 allocated operations are represented by explicit closed routes, typed adapters or workload duties. Human core routes opt into GovernanceGateway through create_manual_app. Named signed gateway routes rebuild current policy under the existing guarded audit transaction. The enforcer ACK is an independently authenticated workload-duty path; it never synthesizes a human principal. No new deployable/persistence credential boundary was collapsed. Governance state belongs to the business gateway; observation fields cannot grant a human review or substitute for inline enforcement.

Signed candidate custody stores immutable bytes, exact metadata/manifest, trusted signer and changed paths. Mechanical classification takes maximum trusted path, artifact and semantic domain floors, unknown paths/domains C3. Technical/operations/security/privacy/equity/clinical/community requirements are distinct synthetic authority classes. Separate accounts for one actual human cannot satisfy independence. These synthetic fixture roles are not real clinical authority.

Live activation through this path supports Rego policy artifacts. Other artifact kinds support signed registration/classification/review and reject activation before changing an epoch; existing inference/static/directory releases retain their separate admission boundaries. This prevents model or prompt bytes replacing a Rego digest. GovernedPolicies selects staged exact signed evaluators by current guarded digest, with no fallback or permission cache. Each instance still verifies its executable and source on evaluation. Activations stage exact required instances; current boot IDs, bounded observation freshness and full required-instance set are checked at commit and every private business/evidence operation. Restart/drift disables affected operations inline until current ACK. Restrictive epoch-only AI disable preserves manual service and cannot relax a mode or restore an old boot.

Restrictive changes journal the fence before propagation. Guarded activation appends a signed relaxation intent with exact current review/ACK evidence, retains restriction barrier and serving generation, and commits a higher epoch. An orphan relaxation intent grants nothing. Rollback needs fresh current reviews and never rewinds identity, consent, deletion, holds or serving authority.

## Custody and evidence

Migration009 adds governed artifact/reviewer/signer/instance/approval/incident/exception state. Runtime cannot provision trust, actual-human linkage or approval custody. Migration010 adds metadata-only time-window audit grants, narrow SECURITY DEFINER audit.scoped_page, reference exports, reviewed fixed aggregate releases and nonoverlap disclosure protection. Migration011 forces live custody writes to acquire control.guard in a BEFORE STATEMENT trigger, preserving the same global-first ordering through the business commit without granting runtime UPDATE on custody tables.

Audit query/download requires current exact-purpose receipt, eligible distinct approver, current creator/grantee/reviewer roles and identity, control epoch, scope and expiry. Content grants are rejected; operators have no standing audit/transcript browse. Export references retain the original scope/expiry/revision; every page is regenerated and audited under current permission. The opaque cursor cannot change a filter/grant/export. No content export link or general audit SELECT is granted to the runtime.

Metrics require an independently provisioned reviewed fixed release and exact period/definition/cohort. All safety/access/equity/police-avoidance companions are present together, including explicit missing counts. Minimum cohort 30, small complements and comparable cells suppress the entire family including exact counts. Immutable nonoverlapping periods prevent ad-hoc differencing across revisions. No individual exposure identifier/export exists. This is conservative disclosure control, not a formal differential-privacy or equity claim.

Incidents support exact recipient-principal containment or explicit global capability containment. Unsupported session/subject/field scopes reject before mutation; they are not silently widened. Closing an incident never restores a fenced principal. Recovery and exception approvals require current eligible independent authority. Only the admitted demo.review_frequency rule can be registered as an exception; it grants no business permission and cannot waive the fixed exclusions.

## Actor and contract behavior

The /governance UI provides EN/FR operator/security/governance/auditor workspaces with exact signed review context, changed paths/source revision/digests/missing authority classes; current/desired epochs and missing ACKs; incidents, grants and paginated audit/export; and coupled suppressed metrics. Unsent input stays in memory across reauthentication. Every private projection is synchronously account/authority-epoch bound, with aborted/stale responses unable to repopulate evidence. Unknown command outcomes retain exact idempotency keys for retry.

Additive source contracts: GovernanceArtifactContext and Gateway_artifact_context expose signed review metadata without payload bytes or new authority. Gateway_health_read uses existing HealthView through the signed data boundary. Workload activation_ack deliberately binds governance purpose in its admitted duty; no public actor ACK exists. Canonical LLD sources were not rewritten.

## Automated evidence scope

Final command logs, source/configuration/fixture hashes, actual versions and evidence digests are in results.json and candidate-manifest.json. Focused tests include real Ed25519 candidate/identity/duty signatures, synthetic OIDC and in-memory identity persistence, in-process signed HTTP transports, pinned real OPA, disposable TLS1.3 PostgreSQL and a real signed filesystem journal. Browser tests use synthetic route fixtures, separately from backend enforcement.

Human usability, screen-reader, visual and language review is deferred_until_after_IMP10. No deployed network, real-provider, clinical, legal, police, production or certification evidence is inferred. Sustained deployed drift/alert/load performance and release readiness are outside the isolated source result. Backup/restore and physical-erasure obligations remain IMP-09. Timing evidence is a declared sequential local synthetic authorization sample; it is not a deployed service SLO.
