# Integrated source review

Configured read-only imp_review and imp_controls passes ran in addition to primary integration. Specialists did not supply human acceptance. Final focused recheck found no remaining critical issue in the reviewed source.

| Finding | Resolution and evidence |
|---|---|
| Caller mutation could bind an OPA permit to unevaluated bytes | Freeze input once, evaluate/bind the same bytes; deterministic mutation regression and real OPA tests pass |
| Reconnect could reactivate an old handshake generation | Server boot namespace and monotonic per-connection fencing; disconnect/reconnect regression passes |
| Error mapping discarded stable reconciliation semantics | Preserve operation key and typed conflict/unknown/replacement codes; BFF tests pass |
| Observe committed SessionView where CommandResult was required | Return canonical CommandResult; real OPA/PG/BFF observation test passes |
| Supervisor UI had no way to acquire interrupt scope | Explicit scoped confirmation with current queue revision and expiry; observation stays read only; component regression passes |
| Lost recovery reply stranded access behind an unknown replacement family | Persist lineage and allow new exact fresh-proof ancestor recovery while fencing successors; PostgreSQL regression passes |
| Worker confirmation did not recheck both parties' current principal and ACL | Bind ACK identity/role/access revisions, check both current principals/support ACL/liveness; revoke/expiry/change regressions pass |
| Signed request could expire during current authority lookup or final SQL | Recheck after lookup and retain original request deadline through final authorization; delayed-callback/final-rollback tests pass |
| Verified denied machine duties lacked canonical audit | Separate post-rollback DENY transaction with workload context; terminal rejected keys and known dependency retries tested; commit_unknown remains unresolved |
| Historical handoff phase could imply a current connection after endpoint loss | Store exact confirmed challenge on assignment and derive current flags from current endpoints/ACL/revisions; disconnect keeps unresolved owner but reports disconnected |

Module boundaries passed: no core business DB imports, no private cross-package imports, domain independent of persistence/frameworks, gateway-only business credentials and separate host journal package. Root contains only existing workspace guidance/manifests; implementation and session artifacts follow the configured layout. All new migrations and common generated contracts were serialized through the primary. Source-only reviewers did not run host/database mutations.

Runtime qualification is distinct: in-process identity/workload fixtures and a core-only image smoke do not prove deployed private TLS/SVID/CNI/current-identity boundaries. Those facts are explicitly not-run in the draft DemoPacket. SQLAlchemy/Alembic direction differs from the explicit Psycopg/SQL implementation and is recorded as a tooling delta. No policy/content signature claims independent human review.
