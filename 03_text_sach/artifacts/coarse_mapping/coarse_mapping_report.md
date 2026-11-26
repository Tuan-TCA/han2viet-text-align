# Stage 03B — Coarse page mapping

**Decision: use B2 as candidate context for Stage 04 evaluation, with B1 retained as a fallback.** B2 narrowed the Stage 02 ranges by 92.8% in Cap_01 and 95.4% in Cap_02. Global reconciliation removed two backward transitions from local selection and reduced adjacent gaps from 18 to 6 relative to B1. It did not outperform B1 on hidden anchors or mean Han coverage in the paired downstream sample. The Silver endpoint proxy improved, but all eligible pairs come from the opening anchored pages of Cap_01. This does not establish a corpus-wide accuracy improvement. Inspect 7 ambiguous and 84 low-confidence pages before treating their estimates as fixed context.

Page statuses: `{'VERIFIED': 9, 'LOW_CONFIDENCE_ESTIMATED': 84, 'AMBIGUOUS': 7, 'HIGH_CONFIDENCE_ESTIMATED': 3, 'PARTIAL': 1, 'UNMATCHED': 41}`. Alignment attempts logged: **291**. This execution: 12.41 seconds, 0 exact-cache hits.

| Cap | Method | Ranges | Mean width | Backward transitions | Gap pages | Excess overlap |
|---|---|---:|---:|---:|---:|---:|
| Cap_01 | B0 | 53 | 31.53 | 0 | 0 | 1553 |
| Cap_01 | B1 | 53 | 2.21 | 0 | 2 | 19 |
| Cap_01 | B2 | 53 | 2.26 | 0 | 0 | 19 |
| Cap_01 | local | 53 | 2.23 | 2 | 2 | 21 |
| Cap_02 | B0 | 51 | 50.16 | 0 | 0 | 2403 |
| Cap_02 | B1 | 51 | 2.08 | 0 | 16 | 3 |
| Cap_02 | B2 | 51 | 2.29 | 0 | 6 | 3 |
| Cap_02 | local | 51 | 2.16 | 0 | 15 | 4 |

Global choices differed from independent local choices on **15** pages. Gap/overlap are geometric proxies over reported intervals, not independently adjudicated omissions.

## Hidden anchors

- B0: 16/16 anchor overlaps recovered, mean distance 0.00 VI pages over 10/10 folds.
- B1: 12/16 anchor overlaps recovered, mean distance 0.28 VI pages over 10/10 folds.
- B2: 11/16 anchor overlaps recovered, mean distance 0.31 VI pages over 9/10 folds.
B0 is descriptive because workbook windows were constructed with source anchors. B1 and B2 do not consume workbook priors in held-out folds; B2 probes the hidden page, with nonhidden anchors and interpolation-only neighbors. Any quality claim on this small sample is provisional.

## Downstream context comparison

- B0: 7 matched successful pages; mean Han/VI coverage 0.947/0.938; unresolved rows 8.
- B1: 7 matched successful pages; mean Han/VI coverage 0.974/0.979; unresolved rows 2.
- B2: 7 matched successful pages; mean Han/VI coverage 0.959/0.979; unresolved rows 2.

B0 downstream probes use at most 30 original VI segments centered in the original candidate range; B1/B2 use all eligible segments touching the proposed range. The comparison measures operational mapping, not semantic truth. Same-payload responses may be reused.
- Silver endpoint proxy B0: 11 single-page pairs; exact CG 2/11, DS 2/11; mean IoU 0.233/0.233.
- Silver endpoint proxy B1: 11 single-page pairs; exact CG 3/11, DS 3/11; mean IoU 0.559/0.569.
- Silver endpoint proxy B2: 11 single-page pairs; exact CG 5/11, DS 8/11; mean IoU 0.930/0.959.

The Silver proxy excludes references spanning two Han pages and uses focal-page-clipped output. It is a small structural comparison, not independently verified translation quality.

## Handoff and limitations

Use `window_context_refined.jsonl` by page, then pass `raw`, `spans`, and `viet` to the existing Stage 04 adapter. `han` and `viet_t1` preserve original IDs, pages, raw spans and T1 projections. Adjacent page rows can share whole cross-page S4 segments; reconcile overlap by ID. Retain candidate ranges or request human review for ambiguous pages rather than treating estimates as fixed anchors.
Cap_02 page 051 is partial. Pages 052–092 remain unmatched for processed Vietnamese context. No translation absence or semantic label is inferred. No official alignment was started.
Service halt: `None`. Probe statuses: `{'ok': 293, 'api_error': 10}`.

The 13-page pilot is retained under `pilot/`. A shell timeout interrupted the first full run; the resumed live invocation completed all 104 supported or partial pages. The final offline replay published the Silver proxy without another request. Full-run request logs include both live invocations; pilot logs are separate. The production audit workbook was locked during the run, so the script checked the machine-readable production audit and per-page context flags instead. Frozen Han, context and audit/manifest hashes were checked before and after the full run.
