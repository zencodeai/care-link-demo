# IMP-04 session003 final state

The exact session002 proposal was accepted and applied only to the independent IMP-04 target. Live qualification is partial with major findings; G-04 remains pending. See qualification-results.md, results.json, demo-packet.json and handoff.md.

All66 session001 source/reference bindings remain unchanged. The new serving image is b5282ae84b127c301f8dbc5cfec7a14c5e8e278b7c9317c0a8eb11811dc88edd; later host operator/harness files are separately bound. All9 source/tooling checks pass, including35 deployment unit tests.44 private attempts have safe summaries retained in evidence/live with exact outcomes. Passed observations in failed phases remain scoped to those observations.

Actual passed cases include distinct genuine actor sign-ins, attributed plans/sharing/revocation, own reports/reload, signed stale directory/quarantine/suspension, real delegation expiry, lifecycle anchors, native manual two-party handoff/messages/idempotency, actual dependency freezer faults/recovery, pendingUI503→same-key/body200 with one durable operation+field, runtime DB privilege denials and forced RLS.

Unresolved: strict A03/A04 tests return503; absent-operation durable row absent; bilingual UI French search503; final normal run's first session-create503; policy256MiB OOM cause; browser zombie accumulation; issuer recovery exceeded75s test window though actual later recovery succeeded; manual screen reader/200percent zoom and other explicitly unrun cases. No silent status/deadline/clock/authority relaxation was used.

Normal data composition is restored with qualification_enabled:false and volumes retained. All29 normal new services are running; seed/operator-seed stopped intentionally. Issuer-only restart recovered all5 current URI-bound certificates and protected200 after the original failed75s window. Final signed journal generation1/tip9/restrictionbarrier9/servinggeneration1; current fencegeneration0. All64 accepted containers match identity/image/status/StartedAt/fullmounts/networks exactly. No accepted restart or reconfiguration, commit/push, participant admission, G-04 acceptance or next-slice activation.
