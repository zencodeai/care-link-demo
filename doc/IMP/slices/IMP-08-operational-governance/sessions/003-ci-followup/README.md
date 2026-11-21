# IMP-08 CI follow-up

User steering: “CI failed”, following the explicit IMP-08 PR publication request. Scope is the Foundation test timing correction on PR15 and current evidence continuity; no merge/deployment or new slice.

Failed push run44927973473, fast job136918148750, head9fa9b25a1dd263c123735a9fd95c3c22e4be5913: ManualService.test.tsx expected EventSource array length1 immediately after async open, observed0. The concurrent PR run44927980573 passed on the same head. Both container jobs passed.

Preserve original G-08 source/fixture/check records. Any fixture-only correction is bound separately in this follow-up; unchanged backend/browser qualification is retained by exact source continuity.

[Handoff](handoff.md) · [current candidate](candidate-manifest.json) · [results](results.json) · [source continuity](source-continuity.json).
