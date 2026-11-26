# Stage 03B — Coarse page mapping pilot

Page statuses: `{'VERIFIED': 6, 'LOW_CONFIDENCE_ESTIMATED': 4, 'AMBIGUOUS': 2, 'PARTIAL': 1}`. Alignment attempts logged: **57**. This execution: 74.25 seconds, 3 exact-cache hits.

| Cap | Method | Ranges | Mean width | Backward transitions | Gap pages | Excess overlap |
|---|---|---:|---:|---:|---:|---:|
| Cap_01 | B0 | 6 | 34.00 | 0 | 0 | 134 |
| Cap_01 | B1 | 6 | 3.00 | 0 | 25 | 3 |
| Cap_01 | B2 | 6 | 2.33 | 0 | 25 | 0 |
| Cap_01 | local | 6 | 2.50 | 0 | 26 | 2 |
| Cap_02 | B0 | 7 | 44.43 | 0 | 0 | 200 |
| Cap_02 | B1 | 7 | 2.14 | 0 | 93 | 1 |
| Cap_02 | B2 | 7 | 2.14 | 0 | 91 | 0 |
| Cap_02 | local | 7 | 2.14 | 0 | 93 | 1 |

Global choices differed from independent local choices on **3** pages. Gap/overlap are geometric proxies over reported intervals, not independently adjudicated omissions.

## Hidden anchors

No held-out anchor evaluation in this execution.

## Downstream context comparison

- B0: 5 matched successful pages; mean Han/VI coverage 0.881/0.933; unresolved rows 9.
- B1: 5 matched successful pages; mean Han/VI coverage 0.904/0.888; unresolved rows 7.
- B2: 5 matched successful pages; mean Han/VI coverage 0.895/0.903; unresolved rows 6.

B0 downstream probes use at most 30 original VI segments centered in the original candidate range; B1/B2 use all eligible segments touching the proposed range. The comparison measures operational mapping, not semantic truth. Same-payload responses may be reused.

## Handoff and limitations

Use `window_context_refined.jsonl` by page, then pass `raw`, `spans`, and `viet` to the existing Stage 04 adapter. `han` and `viet_t1` preserve original IDs, pages, raw spans and T1 projections. Adjacent page rows can share whole cross-page S4 segments; reconcile overlap by ID. Retain candidate ranges or request human review for ambiguous pages rather than treating estimates as fixed anchors.
Cap_02 page 051 is partial. Pages 052–092 remain unmatched for processed Vietnamese context. No translation absence or semantic label is inferred. No official alignment was started.
Service halt: `None`. Probe statuses: `{'ok': 37, 'api_error': 1}`.
