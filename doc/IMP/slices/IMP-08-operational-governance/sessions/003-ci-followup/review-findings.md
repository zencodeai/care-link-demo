# Scoped CI fix review

Independent imp_review confirmed the test still asserts exactly one stream, live ACK behavior, immediate private hide on authority loss and eventual stream cleanup. No global retries, timeouts or runtime controls were weakened.

The review found the new selectable-session verifier needed path association as well as digest checks. selected_binding now binds results to the selected manifest and default ledger references to the selected manifest/results paths. Positive current-session verification and both historical-substitution negatives passed. The reviewer rechecked and reported no remaining concrete blocker. No new DB/browser result is claimed.
