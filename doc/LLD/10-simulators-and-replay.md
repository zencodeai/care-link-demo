# Isolated receiving services, channels, training and replay

## Simulator service contract

Simulator identities are distinct from business/runtime/receiver-human identities. Receiving service IDs map through a signed internal allowlist to exact simulator identities and typed methods. Receivers use their own account and own service assignment; no source-session ACL is granted. A package read revalidates receiving scope and current disclosure policy; stored payload is not a permission. Incoming simulator text/receipts remain untrusted and cannot become authority instructions.

| Scenario | Exact behavior / observed state |
|---|---|
| accept | Persist unique recipient+dispatch ID+digest, return received; separate human decision sets accepted |
| reject | Record explicit refusal/reason; retain source support and alternatives |
| partial | Record accepted field subset and receipt; never mark whole package accepted |
| delay | Persist/pause at named barrier until controlled release; caller timeout remains unknown |
| drop_after_store | Persist package/dedup then close response; status query returns existing receipt without second package |
| receipt_unavailable | Receiver declares no receipt lookup capability; caller remains unsupported/unknown, not accepted |
| schema rejection | Reject invalid/unknown/oversized payload before store; distinguish validation rejection from downstream refusal |
| warm handoff | Separate queue, refusal/drop, worker acceptance and two-party channel confirmation; no implied carrier connection |
| poisoned feed | Unsigned/invalid/instruction-bearing/conflicting source quarantines; admitted source not silently replaced |
| denied emergency | Test-only unreachable target; machine request guard always DENY and network probe denied; no business registry entry or emergency credentials |

Scenario controls require trainer identity, exact scenario artifact/version, synthetic resources and isolated business clock. They cannot mutate another trainer's run or ordinary service controls. Scenario ID namespaces dedup keys and datasets; no mixing scenario outcomes into operational quality views. Scenario clock advances only due scheduling/fixture time; real authentication, policy, consent and token deadlines remain real authority time. Pause/stop cancels scenario tasks and fences outputs without erasing evidence.

## Internal channel exercise

Web is the first real application transport. SMS/voice/mobile/relay/interpretation are internal event simulators with explicit simulated labels. Normalize message IDs, language, delivery observations and channel errors into the same session command; cross-channel continuation requires explicit same-principal proof and target-channel token family. Simulated telephone number/URL text can never route externally. Voice transcription/interpretation text is untrusted reported input, not a verified fact; no unchecked machine translation of clinical guidance. Language/relay/manual help stays visible where supported. Real carriers, app-store delivery, accessibility equivalence and interpretation staffing remain deferred, not satisfied by these tests.

## Training and deterministic replay

Replay input manifest binds scenario, schema, deterministic code/rules/policies/templates, directory versions, task/turn/source revisions, fixture clocks and recorded model outputs. Replay invokes no real model by default, no network connectors, no live grant/identity controls and no serving outputs. Compare deterministic committed states, reasons, effects suppressed, payload digests and audit decisions, allowing new replay-specific timestamps/IDs only through explicit normalization. Temperature0 is not a deterministic-generation guarantee. Missing recorded observation means replay incomplete, never regenerate and call it exact replay.

Training consent/safeguarding supports adult collaborators role-playing fictional cases, stop and instructor review. Model debrief remains labelled proposed; no certification of clinical competence. Evaluation compares actor-only/assisted variants of matched scenarios, isolates participant/order effects and records missingness and raw counts. Shadow tasks cannot change current tier, queue, consent, messages or artifacts; feedback does not train/fine-tune or self-modify the system.

Directory scenario configuration must exercise all seven FR-C2b operating states as explicit versioned facts in addition to poisoning/freshness/suspension. Neither an HTTP200 feed nor a directory row marked verified proves current service availability.
