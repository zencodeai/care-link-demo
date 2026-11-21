# IMP-08 publication handoff

G-08 is closed as automated_qualified for its isolated synthetic governance source/build. All 900 source hashes, 58 reference hashes, 3 build hashes and 47 automated check bindings matched. The merged IMP-07 main tree equals the qualified baseline.

Implementation commit `673306eb2963b2f9178251d2e565cf39230d2f58` is pushed on `feat/imp-08-operational-governance`. [PR #15](https://github.com/zencodeai/care-link-demo/pull/15) is open against `main`. [Publication receipt](publication.json), [source continuity](source-continuity.json), [publication scan](publication-scan.json) and [implementation handoff](../001-implementation/handoff.md). A subsequent documentation-only commit records this receipt; it does not change qualified product source.

Validation retained: 1,684 Python tests passed with 3 explicit legacy skips, 223 frontend tests, 102 focused slice tests and 13 Chromium route-fixture cases passed. All 38 source commands and final metadata/evidence checks passed. Closure verified continuity, schema, links and scoped publication; unchanged behavioral tests were not rerun. Raw log whitespace remains unchanged to preserve evidence digests.

Human review remains deferred_until_after_IMP10. Live activation here is Rego-policy-only and audit access is metadata-only; all other qualified source limits remain in the implementation packet. Backup/recovery and physical-erasure proof remain IMP-09. GitHub Foundation checks were running at the initial publication read; the final PR snapshot records the latest observation. Local qualification does not imply a remote CI pass.

Pre-existing research resources remain excluded and untouched. No merge, deployment, host trust/model change or IMP-09 activation was performed. Next chat: verify PR head/CI and source/evidence bindings, then act only on the newly assigned scope. Merge and deployment require their actual authorization.
