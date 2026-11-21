# Implementation notes and contract reconciliation

The canonical stage remains IMP-07/G-07, tasks A–D, with the 29 allocated public, data-gateway and workload operations. The implementation adds source capability modules; it does not activate a deployment, publish source, advance to IMP-08 or accept a production release.

## Follow-up and outcomes

Post-crisis events require explicit attributed actor input and a source event from the same session. Pending follow-ups contain no inferred clock anchor. Scheduling and binding check the separate current contact grant and the explicit 24–72 hour anchor window. Inbox delivery uses one stable effect key inside the same guarded PostgreSQL transaction as authorization and canonical audit. A lost database acknowledgement is reconciled from durable state. Reauthorization requires locked durable absence and an incremented fence; an arbitrary timeout cannot prove absence. Internal inbox content has its own expiry and never reopens a closed conversation.

Copy cleanup rotates a durable per-class subject cursor over due or deletion candidates. Historical purged copies and released/expired holds do not consume the active inventory bound. Missing anchors, cycles, unknown source locators, active holds and unresolved dependencies retain content explicitly. Review drafts/intents are inventoried purpose copies, including migration backfill when those optional tables exist, and actual assistance replay caches are minimized with their source. Eligible encrypted referral and assistance bodies and stored response copies are minimized through source-bound SQL guards; unknown delivery and running/unknown compute remain retained.

Outcomes retain reporter, source, time and carer-support attribution. A committed outcome receipt does not imply connection or benefit. Cancellation after authorization remains visibly potentially too late.

## Rights and recovery authority

Identity ceremonies retain first MFA time, five-minute cooling, distinct second MFA proof, factor information and exact purpose/subject binding. Export/delete creation requires that proof and a matching own persona. The data request uniquely binds the ceremony; download rechecks its still-fresh second proof and current identity. Export content is encrypted, inventoried, bounded and one-use, with a 15-minute maximum materialization lifetime. The stricter five-minute proof freshness can require creating a newly authorized export. Download intersects the originally materialized identifiers with currently permitted content and excludes other authors' private reports.

Deletion journals a restrictive tombstone outside business restore before restricting disclosure and cancelling unsent follow-ups. Exact committed same-key recovery returns minimized request progress even after restriction. Active-copy minimization is distinct from physical erasure; backup completion remains pending IMP-09 evidence. SQL updates, encrypted-content replacement and unlinking do not prove removal from WAL, storage media or snapshots.

Governance hold release reasserts the original external restriction and commits the active-store release with canonical audit. It does not encode an expired hold as an uncommitted restrictive intent. Future recovery must conservatively retain the external hold until IMP-09 reconciles actual committed release evidence. Failed database work cannot weaken the journal restriction.

## Module and transport boundaries

`services/data/.../lifecycle` owns guards, copy graphs, business persistence, holds and current projections. `LifecycleJobs` uses signed workload duties rather than human actors. The registry verifies the admitted artifact, exact jobs SPIFFE identity, global rights scope, canonical `expired_copy` and `due_followup` resource classes, original request digest, nonce/fence and signed batch limit. Browser source uses the optional BFF lifecycle port and contains no permission authority.

The shared contract snapshot adds existing canonical lifecycle shapes to its bounded public inventory. Authenticated SessionView optionally exposes its current subject revision so actors can request rights without supplying hidden database metadata. Exact metadata-target alternatives and follow-up consent authority facts are additive transport bindings, following the existing planning/referral pattern. The canonical REQ/HLD/LLD documents remain unchanged. The new policy artifact is source configuration, with no live activation.

## Evidence interpretation

PostgreSQL uses a dedicated disposable TLS 1.3 fixture on loopback35437. The populated signed boundary test uses real ceremony logic, signatures, OPA and PostgreSQL, with an explicit synthetic OIDC provider, in-memory identity fixture and in-process HTTP/mesh adapters. Separate tests use real fsynced signed restriction journals and concurrency barriers. These tests do not establish deployed SPIFFE/network enforcement or real-provider readiness.

Chromium evidence covers six EN/FR route-fixture cases, keyboard, axe, responsive overflow, cancellation uncertainty and private inbox clearing. Component tests cover additional complete form sequences. This browser evidence does not itself qualify backend behavior. Human usability, screen-reader, visual and language review is `deferred_until_after_IMP10` and belongs to later GitHub issue follow-ups.
