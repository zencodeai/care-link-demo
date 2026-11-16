# IMP-03 session003 — concise handoff

Read [current status](qualification-status.md) before detailed evidence. This session's records were reorganized on 2026-11-15; original packets and approvals are frozen in [archive](archive/README.md). No runtime or source change accompanies the reorganization.

## Starting point

G-03 is incomplete. The next proposed task is bounded stabilization of worker recovery, trust lifecycle/readiness and the complete visible actor journey. The user has requested documentation declutter first; that does not activate implementation, deployment, another slice or acceptance. Use a separate fresh chat/session folder for subsequent engineering under the canonical IMP workflow.

Read these only as needed:

- [Human progress](archive/continuation/human-review-progress.json) for exact reported passes and unfinished checkpoints.
- [Last candidate](archive/continuation/continuation-candidate-manifest.json), [artifacts](archive/continuation/continuation-deployed-artifacts.json) and [results](archive/continuation/continuation-results.json) for historical bindings.
- [Worker recovery finding](evidence/continuation/worker-open-001/review.md) for the confirmed UI state gap.
- [Stability correction](evidence/continuation/session-instability-001/review.md) for implemented fixes, trust/pool limitations and affected checks.
- [Prior operational handoff](archive/history/handoff.md) for detailed custody notes; its time-sensitive statements are historical.

## Resource boundaries

| Target           | Identity                                                                         | Preserved boundary                                          |
| ---------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Original         | `care-link-imp03-003-*` excluding `-cont1-`                                      | Last verified core fence generation1; preserve state        |
| Continuation     | `CARE_LINK_IMP03_PROFILE=continuation-001`, prefix `care-link-imp03-003-cont1-*` | Last verified fence generation0; separate fresh state       |
| Shared substrate | Existing IMP-02 kind SPIRE/Keycloak                                              | Shared failure/admin domain; no transferred reset authority |

Continuation private root: `/private/tmp/care-link-imp03-003-cont1`. Main origin: `https://qualification.localhost:29443`; PostgreSQL loopback25435; isolated browser loopback29900. Legacy runtime protocol/path is still `imp03-002` / `/run/care-link-imp03-002`. Select the explicit profile before importing operator modules; default selects the original target.

Recheck actual readiness and maintenance state before any later live review. The temporary trust watcher is no longer running. Keep raw browser results, endpoints, credentials, keys and dumps private. Do not replay initial-only provisioning, reset fences, import quarantine into serving state, broadly delete resources or restart memory-backed agents with consumed join tokens.

Synthetic demo only; no police integration or autonomous emergency contact. No commit/push, participant admission or IMP-04 activation is authorized by these records. Historical JSON references retain original path/hash pairs; use [relocations](archive/relocations.json) rather than editing an old approval or packet.
