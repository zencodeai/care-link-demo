# IMP-10 cold-start qualification

The authorized Qwen unload and reload passed the bounded cold and warm checks on the unchanged [session 002 candidate](../002-qualification/candidate-manifest.json). The same authenticated LM Studio listener continued running. The CLI, SDK and REST catalog all showed the selected model absent before recovery. A new instance of the exact Qwen artifact then appeared with the original effective MLX settings, including 8,192 context tokens, four prediction slots, the same 4-bit variant and no idle unload timer.

The installed CLI first rejected an engine-configuration option restricted to vLLM. The successful reload took 9.19 seconds after omitting it. That time excludes the failed attempts. The restored configuration kept the original raw fields and added an explicit parallel count of four plus two disabled auto-fit flags for other engines. SDK settings, authenticated REST settings, the other CLI settings and artifact, tokenizer and template digests matched. The final catalog check verified the replacement instance was still ready.

| Observation | Provider duration |
| --- | ---: |
| First observed synthetic English request after reload | 6.93 s |
| Identical warm English request | 1.68 s |
| Warm French request | 4.35 s |

All three requests passed exact grounding and token accounting. The paired English requests had the same 723 prompt tokens and 11 output tokens. Artifact and identity verification after reload took 7.36 seconds, measured separately from provider generation. The OS file cache remained in place. The first observed synthetic request followed the validation checks on the replacement instance. These are single-run cold and warm observations.

[Current results](results.json) · [Raw timings and restoration evidence](evidence/cold-start.json) · [Initial attempt](evidence/initial-unload-and-reload-attempt.json) · [G-10 ledger](../../../../executions/2026-11-23-IMP-10/ledger.json)

G-10 remains open for the single-topology outage run with all current roles and the declared load. Carry forward the [live provider, workload trust and independent Help results](../002-qualification/results.json). Human observation remains deferred through IMP-10.
