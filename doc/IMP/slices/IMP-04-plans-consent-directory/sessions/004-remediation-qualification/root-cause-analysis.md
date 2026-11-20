# Measured remediation findings

OPA integrity checking allocated a complete60,179,132-byte executable for every evaluation. Per-evaluation streaming hashing retains the same pinned digest/signature checks and reduced workstation traced allocation from60,180,459 to396,041bytes. Actual new PDP underthree qualification trials peaked135,118,848bytes within268,435,456, with zero OOM counters. This is a measured resource correction, not proof that all availability failures were fixed.

The browser's missing init reaper caused orphan zombie accumulation across runs. The presented `--init` correction preserved image/home/capability/limits. The post-trial observation records zero zombies and zero PID ceiling hits, without manual batch restarts.

UI directory refresh launched seven separately authorized requests concurrently. The correction performs allseven sequentially and publishes only the complete successful batch, preserving per-entry authorization,5second UI abort and error clearing. Unit tests prove one outstanding read and clearing after a denied member. Real native bilingual rerun remains required.

Safe Core error propagation now preserves four exact downstream key/status pairs. No statuses, permissions or deadlines changed. Completed Core hop tracing is bounded, private, default off, and contains no credentials/body/narrative. Missing completion rows do not establish no attempt; transport failures may have no response-hook row.

Sequential genuine-role diagnostics passed session/read/create and EN/FR directory operations in364–423ms. An authenticated HTTPS field probe passed in427ms. The native trials nevertheless showed intermittent503/commit_unknown and business refresh loss during visible MFA. Business PostgreSQL sampling found no blockers in its sampled interval.

The identity database contains398sessions,387alreadyexpired/restricted,806intents and14ceremonies. Existing credential cleanup runs every5seconds under the identity-wide advisory transaction lock. Its old implementation repeatedly performs three full dependent-table scans for every restricted session even if no material remains. A source-only100already-cleared-session fixture performs303kind scans without changing any record. Current record counts imply at least1,161 dependent scans per sweep, before other account/intent checks.

SELECT-only observation of the existing background routine measured identity transactions lasting up to964ms. This occupies almost the complete immutable1second business-request budget and explains why queued identity resolution can fail despite fast isolated requests. The proposed fix must retain the advisory guard and every restriction predicate while replacing repeated scans with transaction-local snapshots and a single dependent-material pass. No positive permission cache may survive a sweep.

Automatic approval review rejected manually invoking the live maintenance routine for profiling because it could revoke sessions/delete proofs/expire ceremonies. That invocation was not executed. All subsequent live diagnosis is SELECT-only; source tests use synthetic stores. The normal application's pre-existing automatic maintenance remains active.


## Identity scheduled cleanup contention

SELECT-only observations found identity transactions up to964ms under the unchanged global advisory guard, against a one-second business request budget. Retained state contained398sessions,387restricted/expired and806intents. The former loop rescanned each dependent kind for every restricted session. A synthetic100already-disposed-session comparison required303source scans with no state changes.

The reviewed replacement keeps the same transaction/guard and restriction/disposal predicates, but uses a single per-kind read-through/write-through view within that sweep. Resulting state/counters match the original algorithm;14differential tests and the full228identity tests passed. This bounds SQL scans, not overall CPU linearity. The identity-only replacement was proposed before application and serving source hashes match the reviewed build. No manual live cleanup was invoked.

A20-second passive post-deployment sample observed a maximum transaction age13ms, compared with964ms before. Native workflow qualification remains separately measured; this observation alone is not a passing qualification.
