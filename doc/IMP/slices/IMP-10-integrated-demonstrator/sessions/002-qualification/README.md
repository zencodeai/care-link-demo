# IMP-10 automated qualification follow-up

This session continued the isolated G-10 checks at baseline `7c1609d`. It verified the [original candidate manifest](../001-implementation/candidate-manifest.json) before making changes. The [archived ledger](session-001-ledger.json) preserves the original disposition.

- [Work packet](qualification-work-packet.json)
- [Current results](results.json) and [handoff](handoff.md)
- [Current candidate](candidate-manifest.json) and [evidence](evidence/)

## Reproduction

Build the current checkout with `docker build --file deploy/images/imp06/Dockerfile --tag care-link-imp10:qualification-002-final .`. The network-disabled package smoke checks non-root execution and compares selected image source and web-build bytes with the checkout. Record the exact image digest and observed file hashes for the model qualification release. This image uses the existing five-role qualification recipe.

Run the owned [SPIRE and Envoy fixture](../../../../../../tools/imp06_verification/role_topology.py) with `--image`, `--output` and `--run`. Run the [protected provider fixture](../../../../../../tools/imp06_verification/g06_protected.py) separately with the same image and exact receipt, the fixed-model directory, model index and current owner-only host credential file. The two role fixtures use overlapping disposable subnets. Wait for the first to remove its own resources before running the second. Keep the credential only in the host process that authenticates to LM Studio.

The source regression and fixture-provider comparison use the [IMP-10 runbook](../../../../../runbooks/imp10-integrated-demo.md). The loaded-model comparison uses the existing `tests/evaluation/qwen_combined_journey.py` and `tests/evaluation/qwen_g06_timeout.py` in separate pytest processes. Supply the owned verified-TLS database, the pinned image receipt, the existing exact model inputs and distinct fresh result paths. Select live mode with `CARE_LINK_JOURNEY_PROVIDER=live` or `CARE_LINK_G06_TIMEOUT_PROVIDER=live`, respectively. The bounded ten-case warm workload is `python -m tests.evaluation.qwen_workload` with the same exact model inputs. Its first wave starts with an already-loaded model.

Use the revision-bound source, timed fixture outcomes and environment receipts to distinguish transport security, real model response, actor workflow and independent help evidence.
