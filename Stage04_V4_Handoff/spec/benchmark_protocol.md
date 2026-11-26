# Stage04 V4 fresh benchmark protocol

## Purpose
Compare frozen S4+T1 baseline and generalized V4 on fresh windows from both Caps, using identical Han and Vietnamese source inputs.

## Proposed windows

| Window | Pages | Mapping status | Unique VI IDs | Han chars | VI chars | Why selected |
|---|---|---|---:|---:|---:|---|
| Cap_01-027-028 | 27–28 | VERIFIED + LOW_CONFIDENCE_ESTIMATED | 20 | 1,061 | 3,542 | One verified anchor plus one estimated page |
| Cap_01-047-048 | 47–48 | LOW_CONFIDENCE_ESTIMATED + HIGH_CONFIDENCE_ESTIMATED | 16 | 930 | 2,577 | Different part of Cap_01 and mixed confidence |
| Cap_01-051-052 | 51–52 | LOW_CONFIDENCE_ESTIMATED + VERIFIED | 12 | 812 | 2,292 | Near Cap_01 end with one verified anchor |
| Cap_02-009-010 | 9–10 | LOW_CONFIDENCE_ESTIMATED + LOW_CONFIDENCE_ESTIMATED | 19 | 660 | 1,218 | Early Cap_02 region |
| Cap_02-026-027 | 26–27 | VERIFIED + LOW_CONFIDENCE_ESTIMATED | 23 | 686 | 2,085 | Verified anchor plus estimated neighbor |
| Cap_02-047-048 | 47–48 | LOW_CONFIDENCE_ESTIMATED + LOW_CONFIDENCE_ESTIMATED | 32 | 696 | 3,254 | Later Cap_02 region with more VI context |

These are proposed fresh candidates, not guaranteed unseen. Before execution, inspect all Stage04 request logs, caches, manifests, and previous experiment outputs. If a candidate payload/window has already been used for Stage04 evaluation, replace it with another unused adjacent pair and record why.

## Known exclusions from prior work

- Cap_01: 1–4 (Silver/V4 source development), 21–22 and 40–41 (Stage03 context-size comparison), 30–31, 38–39, 53 (Stage03 frozen held-out).
- Cap_02: 13–16, 51 (Stage03 frozen held-out), 20–21 and 35–36 (Stage03 context-size comparison).

The machine-readable exclusion list is `candidate_data/benchmark_exclusions.json`.

## Execution rules

1. Freeze V4 code and configuration before reading fresh benchmark results.
2. Run baseline and V4 on exactly the same Han and VI inputs.
3. Keep API calls unlimited by an artificial request-count cap; make as many distinct experimental requests as needed to test the hypotheses. Reuse a cached response only when endpoint and full payload hash match exactly.
4. Use the existing API client, cache, and resume mechanisms. Save every request, raw response, result, checkpoint, retry, and failure.
5. Use the same context policy for baseline and V4. Start from the Stage03 recommendation of 10 original VI segments around a page anchor, but retain full candidate context and test 5/10/15 if sensitivity is material. Do not silently truncate.
6. Do not call Separate again unless the source segmentation is missing or demonstrably invalid. Stage03 is complete.
7. Use `fresh_benchmark_seed.jsonl` as the exact page-level Han/VI context seed. Use the CSV/XLSX manifest for selection and traceability.
8. Do not run full-corpus live alignment in this task.

## Metrics

Report separately:
- Mapping success / unresolved mapping.
- Han and VI coverage.
- Duplicate and overlap coverage.
- Order violations.
- Exact span match and IoU against source/reference offsets where available.
- Exact full-VI-ID assignment and alignment type.
- Semantic TRUE/FALSE/UNKNOWN only where independently adjudicated.
- False-correction rate and correction precision.
- API score distributions, latency, request count, and failure rate.

Do not report semantic accuracy when no independent Gold labels exist. Coverage, IoU, and API score are not semantic truth.

## Release gate

Promote V4 only if it improves the fresh benchmark on independently reviewed cases without increasing incorrect corrections. Otherwise retain S4+T1 baseline and ship V4 as an experimental candidate with explicit unresolved cases.
