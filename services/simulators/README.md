# Isolated receiving-service simulator

ReceiverService owns a distinct verified-TLS PostgreSQL database, immutable encrypted packages, atomic person-purpose copy registration, durable dispatch/digest deduplication and receiver decisions. A fixed current actor-to-fictional-service assignment governs the inbox, package projection and decisions. Sender database credentials cannot read receiver storage.

The HTTP app requires explicit workload verification and current signed receiver identity verification. Core human operations and Data send/lookup have separate fixed routes. No browser, model or directory record can choose a URL or create a real connector. Scenarios are closed synthetic composition fixtures: normal, drop_after_store, timeout_before_store, unavailable. Human accept/partial/reject/clarify decisions are explicit and version checked.

Receipt storage, service acceptance and human connection remain separate. The receiver claims no human connection. Copies retain a pending later-parent-and-terminal-delivery anchor with seven-day duration; IMP-08 supplies later rights/cleanup coordination. Unknown delivery never becomes automatically eligible for deletion.

See [process configuration](../../tools/imp05_runtime/README.md) and [IMP-05 evidence](../../doc/IMP/slices/IMP-05-reviewed-simulated-referral/sessions/001-implementation/handoff.md).
