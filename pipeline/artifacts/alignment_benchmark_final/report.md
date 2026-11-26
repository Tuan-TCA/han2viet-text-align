# Alignment API experiment E07–E11

**38 live requests.** Status: completed planned pilot and applicable follow-ups.

| Experiment | Jobs | Live requests | Reused | Status | Median live latency (ms) |
|---|---:|---:|---:|---|---:|
| E07 | 30 | 30 | 0 | {'success': 30} | 1367.5 |
| E08 | 6 | 3 | 3 | {'success': 6} | 1354 |
| E09 | 4 | 0 | 4 | {'success': 4} | None |
| E10 | 4 | 4 | 0 | {'success': 4} | 7748.5 |
| E11 | 7 | 1 | 6 | {'success': 7} | 7662 |

## E07 — Can score separate corresponding and non-corresponding inputs?

Primary score is available only if a unique scored output covers both full inputs. Missing scores are not zero. Scores below compare Silver candidate pairings, not semantically verified labels. AUC is descriptive, with half credit for ties.

| Mismatches | Candidate / negative medians | Candidate / negative ranges | AUC | Within same Han | Provisional positives only |
|---|---|---|---:|---|---|
| hard | 0.524 / 0.133 | 0.233–0.568 / -0.109–0.218 | 1.000 | {'win': 6} | {'win': 3} |
| distant | 0.527 / 0.173 | 0.304–0.594 / 0.133–0.368 | 0.933 | {'missing': 1, 'win': 5} | {} |
| all_negatives | 0.524 / 0.153 | 0.233–0.594 / -0.109–0.368 | 0.970 | {'win': 11, 'missing': 1} | {'win': 3} |

Raw max-score sensitivity: AUC 0.965, within-Han {'win': 12}. Primary subset with Vietnamese length ratio ≤1.5: {'win': 3}. This is a sensitivity check, not causal length control.
Additional length-matched hard probes: {'win': 3, 'loss': 1}. Reported separately from the original 24 requests; see the individual scores and length ratios in `metrics.json`.
Deliberate repeats: [{'job': 'E07-corresponding-08-repeat', 'original': 'E07-corresponding-08', 'score': 0.5473270416259766, 'original_score': 0.5473270416259766}, {'job': 'E07-length-probe-08-repeat', 'original': 'E07-length-probe-08', 'score': 0.5498241186141968, 'original_score': 0.5498241186141968}]. See `metrics.json` for all individual scores and missing values.

## E08 — Sensitivity to Vietnamese order

| Job | Matches by original VI ID | Matches by input position | Groups | Scores | Han / VI coverage |
|---|---:|---:|---|---|---:|
| E08-01-02-normal | 2 | 2 | {'1-1': 2} | [0.185068176913019, 0.31047325232644396] | 1.000 / 1.000 |
| E08-01-02-reverse | 0 | 0 | {'N-M': 1} | [0.5613836646080017] | 1.000 / 1.000 |
| E08-09-10-normal | 2 | 2 | {'1-1': 2} | [0.36993959937491416, 0.35790806675873804] | 1.000 / 1.000 |
| E08-09-10-reverse | 0 | 0 | {'N-M': 1} | [0.6076425299898687] | 1.000 / 1.000 |
| E08-07-08-normal | 0 | 0 | {'N-M': 1} | [0.5634182691574097] | 1.000 / 1.000 |
| E08-07-08-reverse | 0 | 0 | {'N-M': 1} | [0.5690886378288269] | 1.000 / 1.000 |

## E09 — Number normalization

| Job | Invalid VI indices | Text fallback rows | Unresolved rows | Number cuts detected | Groups |
|---|---:|---:|---:|---:|---|
| E09-03-04-source | 1 | 1 | 0 | 0 | {'N-M': 1} |
| E09-03-04-normalized | 0 | 0 | 0 | 0 | {'N-M': 1} |
| E09-05-06-source | 1 | 2 | 0 | 0 | {'1-1': 2} |
| E09-05-06-normalized | 0 | 0 | 0 | 0 | {'1-1': 2} |

Only source-confirmed single-dot thousands and unambiguous dot grouping are removed in the outgoing payload. Decimals and ambiguous single-dot tokens are preserved. Invalid VI indices are measured against submitted lines. Detected number cuts are a lower bound from matchable snippets; altered whitespace can prevent exact detection.

## E10 — Vietnamese segmentation, Han fixed at S4

| Strategy | Fragments | Status | Exact CG / DS | Agreed | IoU CG / DS | Han / VI coverage | Unresolved |
|---|---:|---|---:|---:|---:|---:|---:|
| E10-T1 | 12 | success | 5/12 / 7/12 | 5/8 | 0.922 / 0.923 | 0.928 / 1.000 | 0 |
| E10-T2 | 13 | success | 5/12 / 7/12 | 5/8 | 0.922 / 0.923 | 0.928 / 1.000 | 0 |
| E10-T3 | 18 | success | 4/12 / 6/12 | 4/8 | 0.729 / 0.730 | 0.980 / 0.999 | 0 |
| E10-T4 | 60 | success | 5/12 / 6/12 | 5/8 | 0.497 / 0.500 | 1.000 / 0.996 | 0 |

Fragments are projected back to source IDs before evaluation. Single-ID chains may cross whitespace-only gaps. The scorecard does not mark a mapped N–M group wrong in meaning merely because it differs from individual Silver references.

## E11 — Context and merging

| Input | Successful windows | Groups | N–M share | Exact CG / DS |
|---|---:|---|---:|---:|
| 12x12 | 1 | {'1-1': 10, 'N-M': 1} | 0.091 | 10/12 / 8/12 |
| 2x2 | 6 | {'1-1': 6, 'N-M': 3} | 0.333 | 6/11 / 3/11 |

The 2×2 context baseline uses historical payloads with identical number normalization, including the paired E09 runs.
On the 11 references available under both sizes, 12×12 has 10 CG / 8 DS exact matches. This compares one long context to six particular windows; it is not a claim about all larger inputs.

## Findings and design decisions

1. **Score discrimination:** {'win': 11, 'missing': 1} in the main paired test; descriptive AUC 0.970. Length-controlled follow-ups produced {'win': 3, 'loss': 1}. Score overlap and Silver uncertainty rule out adopting a universal threshold from this pilot.
2. **Numbers:** out-of-range VI index rows 2 → 0; text fallback rows 3 → 0 across the paired controls. The observed alignment group types stayed the same.
3. **Default Vietnamese segmentation:** E10-T1 by mean reference IoU (ties broken by fewer fragments). Additional segmentation is an option for local repair, rather than a default meant to maximize raw coverage.
4. **Order:** inspect original VI_ID, not position. Reversed windows returned joint groups rather than recovering singleton crossings in the observed successful reversals. A joint group can retain high coverage and a high score while hiding which individual passages correspond. This does not by itself establish semantic error for the whole group.
5. **DP:** do not use the raw score as the sole transition cost or compare 1–1 and N–M scores as if calibrated. If used at all initially, compare a score-free baseline to a modest score feature normalized within transition shape and length.
6. **Pipeline:** use page-anchored windows, Hán S4 as an initial baseline, source Vietnamese IDs, number protection, reversible mapping, multiple candidate boundaries, and monotone alignment with explicit skip and N–M transitions. Review counterexamples and low-confidence outputs before scaling.

## DP and pipeline decision

Preserve source text; use protected number normalization and reversible fragment offsets. Generate local candidates from page anchors and multiple Hán boundaries, then apply mapping integrity checks, monotonicity and no-overlap checks. Keep N–M and skip transitions available. Treat the API score as a candidate feature only until it shows reliable within-passage ranking against independently reviewed negatives and against simpler baselines. Never infer a semantic label from API success, score or reference boundary match. `semantic_review.xlsx` has 66 distinct review groups; labels are blank.
