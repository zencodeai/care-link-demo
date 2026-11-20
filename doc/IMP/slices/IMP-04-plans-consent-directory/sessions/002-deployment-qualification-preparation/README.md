# IMP-04 session002 — deployment and live qualification preparation

Prepared on 2026-11-16 from session001. **No deployment changes have been applied.** G-03 remains accepted; G-04 remains pending.

Read [the exact deployment proposal](deployment-delta.md), then [the qualification procedure](qualification-plan.md). [target-proposal.json](target-proposal.json) enumerates the proposed resources, network addresses, ports, credentials by custodian, database names, actor roles and image inputs. [demo-packet.json](demo-packet.json) is a schema-valid draft with no claimed live outcomes.

The proposal creates a separate `care-link-imp04-002` target, including dedicated SPIRE and Keycloak services. It does not replace the accepted `imp03-review` target or alter its shared infrastructure. Both environments still share this workstation and Docker daemon; resource capacity is a preflight requirement.

[Continuity evidence](continuity-check.json) confirms all **69** source/build/reference entries in the session001 manifest still match. [Artifact verification](artifact-verification.json) verifies the exact IMP-04 policy signature, seven signed directory envelopes and independent directory public-key pin. [Resource inventory](resource-inventory.json) records a read-only, secret-free Docker snapshot. These are preparation checks, not deployment qualification.

There is a concrete remaining implementation step: the current IMP-03 launcher cannot deploy this target safely. [The proposal](deployment-delta.md) specifies new, target-scoped orchestration and image assets; they have not been implemented by this preparation request. Deployment approval must bind their actual patch, rendered plan and built image IDs after review. Null image/configuration/actor identities are explicitly unissued, not deployment-ready placeholders. No approval is being inferred from the handoff.

Session records: [WorkPacket](work-packet.json), [artifact bindings](artifact-bindings.json), [directory inventory](directory-inventory.json), [review](review.md), [results](results.json), [human decision state](human-decisions.json), [handoff](handoff.md).
