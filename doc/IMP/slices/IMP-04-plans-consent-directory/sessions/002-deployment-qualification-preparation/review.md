# Preparation review and reconciliation

The coordinator is the sole writer. `imp_platform` and `imp_controls` performed bounded read-only source reviews; `imp_review` independently reviewed the integrated deployment/DemoPacket and then the corrected qualification procedure. No specialist changed application files, deployed resources or delegated further. No more than three specialist threads ran concurrently. Their findings are engineering review, not human approval.

Resolved in the prepared scope:

- Existing profile/preparation/provision/image/toolkit assumptions select IMP-03, omit migrations002/003, reject added actors/admission fields and load the wrong policy. The proposal requires a separate new operator/recipe and clearly labels it unimplemented; old helpers are not presented as runnable IMP-04 deployment commands.
- Reusing the existing SPIRE root with the same role names would mix administrative trust. The proposal uses a dedicated authority/root and dedicated Keycloak/DB; no accepted registrations, realms or services are mutated. Logical role names remain compatible with the exact signed policy.
- Initial review found mesh peer communication disabled while direct proxy TCP was required. Corrected to internal bridge with isolated gateway mode and peer connectivity; mTLS, route and per-request identity/fence enforce authority. No unlisted egress bridge is assumed.
- Initial DemoPacket A07 implied use of an accepted-target SVID. Corrected to a new diagnostic foreign CA with the same logical identity plus public root/bundle comparison; no accepted private key, SVID extraction or proxy reconfiguration.
- Initial Q09 overstated ordinary App recovery. Corrected to same-mounted-page unsent/pending-key recovery and re-reading committed records by manually reselected IDs after full reload. The four-slot ReviewApp's durable draft/intent restoration is not claimed qualified for IMP-04.
- Final qualification review distinguished visible DirectoryView source/state/expiry fields from owner/method/field-class evidence held in the signed admission manifest. No unsupported UI visibility is claimed. A requirement for those fields on screen would need a separately reviewed product delta.
- Directory matrix was reconciled to the exact seven signed fixture labels. Fixed observation/expiry and no retained signing key prohibit inventing fresh positive availability by changing timestamps. New source evidence/pins require their own candidate review.
- Existing consent race tests remain source/adapter evidence. Deterministic deployed pending-output evidence needs a separately reviewed target-only final-release barrier; it cannot be fabricated with a clock injection or a lock-blocked revocation.

Retained limitations: no new operator/image/configuration/actor/certificate/journal IDs have been issued, no live checks or native accessibility checks ran, and no deployment-change or G-04 decision exists. These are explicit subsequent execution tasks, not failures of this preparation packet. The new environment shares the workstation/daemon, so preflight capacity and preservation comparisons are required.
