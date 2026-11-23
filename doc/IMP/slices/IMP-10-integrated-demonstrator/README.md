# IMP-10 — Integrated demonstrator

**G-10 is closed as `automated_qualified`.** The final protected candidate passed two deployed warm rounds and two controlled error rounds at ten active sessions, two occupied slots and eight queued tasks. The user waived true cold-start measurements for this private synthetic qualification.

[Closure and publication](sessions/010-closure-and-pr/handoff.md) · [Final qualification and closure](sessions/009-cold-exception-closure/handoff.md) · [Deployed qualification](sessions/008-deployed-qualification/handoff.md) · [Protected deployment bindings](sessions/007-protected-deployment/handoff.md) · [Kubernetes retry](sessions/006-kubernetes-retry/handoff.md) · [Deployment qualification follow-up](sessions/005-g10-closure/handoff.md) · [Combined outage follow-up](sessions/004-combined-outages/handoff.md) · [Cold-start follow-up](sessions/003-cold-start/handoff.md) · [Qualification follow-up](sessions/002-qualification/handoff.md) · [Implementation handoff](sessions/001-implementation/handoff.md) · [Evidence matrix](sessions/001-implementation/trace-disposition.json) · [G-10 ledger](../../executions/2026-11-23-IMP-10/ledger.json) · [Runbook](../../../runbooks/imp10-integrated-demo.md)

- IMP-10-A reconciled the local, upstream, control, verification and operation inventories. G-06 through G-09 retain their exact predecessor candidate scopes.
- IMP-10-B adds three trainer scenario routes and four signed replay routes in Core and Data. Two fixed-deny routes cover identity linking under LD-13. Training and quality code is in services/simulators, services/core, services/data and the shared contracts and domain packages.
- IMP-10-C adds the English and French training workspace, scoped sign-in profiles and automated browser coverage. The browser fixture exercises HTTP request and visible-state behavior.
- IMP-10-D recorded the loaded and cold model observations, application and outage timings, five-role SPIRE and Envoy probes, and 55 passing Chromium tests. The developer Core image passed its isolated smoke check.

Human usability, language, visual and screen-reader review remains `deferred_until_after_IMP10` for GitHub issue follow-up. The candidate manifest binds the qualified source and image. Earlier protected deployment and outage evidence remains linked above.
