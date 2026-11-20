# IMP-05 referral policy source

This version extends the IMP-04 manual policy for private synthetic referrals. It is source code for isolated qualification; its presence does not activate a policy or establish independent approval. Existing IMP-04 policy and signatures remain unchanged.

Referral operations use a separate allow branch. Human workforce assurance, current resource scope, current directory admission, exact granular service consent and exact human review are checked independently. Enqueue grants no transmission permission. Final authorization and consumption rebuild facts; their policy names are `dispatch_authorize` and `dispatch_consume`. `dispatch_observe`, receipt/status reads and reconciliation preserve truthful prior evidence after send permission changes while retaining current actor scope checks. They cannot authorize a package send.

The data gateway supplies the server-derived referral payload digest separately from the command digest. Review and consent facts bind their IDs, current subject/session/recipient/fields, expiry and exact payload. The simulator service mapping remains a technical configuration responsibility; directory/user text supplies no executable target. Receiver actor authority is owned by its separate service and is not admitted by this data policy.

Verification: `CARE_LINK_OPA_BINARY=<existing pinned OPA> .venv/bin/pytest packages/policy-input/tests/test_referral_policy.py -q`. The test signer is an explicitly synthetic integrity fixture, not human policy approval. Human review is deferred until after IMP-10.
