# Concrete continuation deployment delta — reviewed and accepted

The user explicitly reviewed and accepted these deployment deltas in the current conversation. The [scoped acceptance record](deployment-delta-acceptance.json) binds the reviewed document and packet snapshots to the unchanged candidate. This closes deployment-profile review for this bounded synthetic qualification scope.

This records the actual synthetic qualification target; it does not amend HLD, recreate deleted LLD or grant human G-03 acceptance. User authority is the explicit instruction to proceed with remaining automatable tasks, continuing the earlier Option B reuse decision.

| Boundary | Actual continuation | Evidence/remaining difference |
|---|---|---|
| Shared substrate | Same workstation/Docker and retained kind services | No second full infrastructure stack. Original IMP-02 logical state and original IMP-03 generation1 fence preserved. |
| Identity/trust services | Existing Keycloak and SPIRE processes; new realm, separately issued synthetic actors and dedicated new agent parents | Shared administration/failure domain remains. Four actor bindings are supported by the app; an unused fifth provider account has no app registry authority. |
| PostgreSQL | Fresh disposable process, fixed runtime DB/login/group names, verify-full TLS, scoped hba sources and loopback operator publication | Deliberate continuation delta from sharing the original PostgreSQL process. It preserves fresh-only collision guards and old data instead of adopting/resetting them. |
| Application placement | Five capless, read-only-root Docker roles, networknone, distinct UIDs, own volumes and fixed protected relays | This is not normal Kubernetes application placement or Calico enforcement. |
| Package/image distribution | Three bound source-workspace image variants across roles; co-located tests excluded | Multiple role packages remain in the common image. Per-role installed distributions are not implemented. Credentials/mounts/UIDs and network boundaries are separately exercised. |
| Workload attestation | Distinct new agent parents and Unix proxy UID22002 selectors | Exact image selectors are absent. Deliberate scoped probe programs under the same parent/UID obtain the corresponding SVID; this is explicit evidence of selector scope. Apps use different UIDs and lack WorkloadAPI mounts. |
| Service authorization | Mutual TLS with exact SPIFFE route rules, kernel-bound proxy provenance, current per-target fence, signed delegation/current actor/PDP/data/audit revalidation | Wrong-role/absent identity, forged claims, expiry on an existing connection and current-source ACL loss were exercised. This is bounded observed coverage. |
| Journal/capture custody | Separate host Docker volumes outside kind; encrypted capture and quarantine-only import | No trusted serving recovery/promotion. Full trusted recovery remains IMP-09. |
| Browser trust | Pinned Linux Playwright image; dedicated NSS trust volume and process-scoped Node CA bundle | `ignoreHTTPSErrors:false`; no global Mac trust/DNS change. Browser WS endpoint stays private. |

The bounded Docker/UID/source-workspace profile is accepted for this synthetic G-03 qualification scope. The absent normal per-role/Kubernetes/image-selector controls remain documented technical differences, not outstanding deployment-profile approval. This scoped acceptance does not supply the remaining human usability review or overall G-03 decision, and does not represent absent controls as implemented.

The prior fenced target and its accepted dependency records remain historical and intact. The continuation is a fresh synthetic state domain, with different actors/keys/databases and isolated mesh; it does not import old serving state or undo the original restriction. Logical `/demo/*` service IDs are shared within the same trust domain, with new parent registrations and separate target custody/authorization.
