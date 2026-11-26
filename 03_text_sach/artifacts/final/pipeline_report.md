# Stage 03 — Experimental report and release decision

**Keep S4 + T1 as the production baseline.** The Vietnamese-guided hybrid placed more Silver reference boundaries correctly, but its resulting Stage 04 alignments were less exact than S4 + T1 on the same OCR input. The held-out runs establish that the methods execute on both Caps; pending independent semantic review, they do not establish a production improvement.

## Experiment A and D: Silver and downstream alignment

Cap_01 Han 001–002, 905 raw characters; 12 existing Vietnamese segments. Production segmentation receives OCR, Vietnamese context and mapping, but no Silver spans. The historical S4 cuts and downstream results were reproduced. OmniAlign was run locally for M3/M5. M6 was not run: no configured offset-only LLM.

| Method | Han segments | Boundary F1 CG / DS | Downstream exact CG / DS / agreed | Downstream mean IoU CG / DS | Han / VI mapped coverage | Unresolved groups |
|---|---:|---:|---:|---:|---:|---:|
| M1 S4 | 40 | .320 / .400 | 5/12 / 7/12 / 5/8 | .922 / .923 | .928 / 1.000 | 0 |
| M2 length | 10 | .100 / .200 | 0/12 / 0/12 / 0/8 | .000 / .000 | .617 / .667 | 2 |
| M3 semantic | 12 | .091 / .091 | 0/12 / 0/12 / 0/8 | .489 / .475 | 1.000 / 1.000 | 0 |
| M4 anchors | 12 | .364 / .273 | 2/12 / 1/12 / 1/8 | .506 / .483 | 1.000 / 1.000 | 0 |
| M5 hybrid + repair | 15 | .480 / .560 | 3/12 / 5/12 / 3/8 | .733 / .734 | 1.000 / 1.000 | 0 |

Exact counts compare one fully mapped downstream group per Vietnamese ID. Missing comparable groups contribute zero to mean IoU. Boundary metrics compare Han segment endpoints within the Silver range; exact counts and IoU compare downstream alignment, so they need not move together. The workbook includes precision/recall, per-reference spans, raw segmentation exact, timing, requests, alignment types and unresolved mappings. All evaluated segmentations reconstructed the Han source exactly, with zero missing or duplicated source characters. This does not imply complete downstream alignment.

Counterexample: M3 mapped 100% of both sides but matched zero exact Silver pairs; two mapped groups were N–M. M5 also mapped 100%, but its 11 mapped groups for 12 IDs included a 1–N group. Inspect those groups as a whole before assigning semantic labels.

## Experiment B: Incremental evidence

| Variant | Boundary F1 CG / DS | Downstream exact CG / DS | Mean IoU CG / DS |
|---|---:|---:|---:|
| M5 | .480 / .560 | 3 / 5 | .733 / .734 |
| No length | .636 / .727 | 4 / 6 | .919 / .920 |
| No semantic | .480 / .560 | 3 / 5 | .733 / .734 |
| No numerical score | .571 / .571 | 3 / 3 | .687 / .666 |
| No entity score | .381 / .476 | 2 / 3 | .515 / .511 |
| No direct Separate marks, S4 retained | .480 / .560 | 3 / 5 | .733 / .734 |
| Neither Separate nor S4 marks | .000 / .000 | 0 / 0 | .515 / .496 |
| No S4 marks, direct Separate retained | .571 / .571 | 3 / 3 | .689 / .666 |
| No repair | .571 / .571 | 3 / 3 | .549 / .526 |

S4 is derived from Separate, so the direct-mark and combined ablations answer different questions. Number/entity scoring ablations retain hard interior protection. Candidate provenance mattered most in this pilot; numerical and entity scores helped with downstream exactness in this configuration. The local semantic feature did not change the selected result in this pilot. Removing length helped the hybrid but did not beat S4 end-to-end, and the estimate was based on only six training anchors. Accepted repair improved IoU / DS exact but reduced CG boundary F1, a reason to judge repair by downstream review instead of a single metric. The no-length variant was not selected after seeing held-out outputs; it is a development hypothesis for evaluation on a fresh split.

## Experiment C: Frozen held-out execution

- Cap_01: 030–031, 038–039, 053. Cap_02: 013–014, 015–016, 051. Selection favored adjacent numeral-dense and title-dense pages plus short passages, outside known prior reviewed Han pages. The program saved all six windows in the manifest before execution. Source-window characteristics provide diversity; independent genre and OCR quality labels were not available.
- S4 and M2 returned mapped-response diagnostics on six of six windows; M3–M5 on five of six. Cap_01 030–031 returned application error `000500` for M3–M5 even after smaller-window attempts. No internal interpretation of the API error is assumed.
- On the same five successful windows, mean raw Han / VI mapped coverage was M1 **.623 / .373**, M2 **.636 / .363**, M3 **.627 / .451**, M4 **.685 / .637**, and M5 **.753 / .525**. These are coverage diagnostics, not evidence of semantic superiority. M5 accepted one repair (Cap_02 015–016), increasing covered Han characters from 559 to 612 and VI IDs from 39 to 44, while reducing unresolved rows from 2 to 1. Other successful-window proposals were rejected.
- Independent held-out labels and reference offsets were unavailable. Held-out boundary P/R/F1, exact and IoU are therefore unmeasured. The held-out run includes a blind source/reference workbook, with no model-generated boundaries in the reviewer form, and a separate workbook with the actual predictions.

## Semantic verification and release

Verified positives: **0**. Verified negatives: **0**. Verified-positive proportion: **unavailable**. The benchmark has 47 mapped predictions across M1–M5 before deduplication; the held-out runs have 331. All are `UNKNOWN` pending independent review, including predictions matching Silver boundaries. Unresolved output rows are separately logged, and are also not automatically negative. The existing three provisional Silver positives are not independent reviews of these prediction groups.

Main remaining failure modes: uncertain coarse VI windows, trivial coverage gains from merging, ambiguous repeated text and numeral OCR, unaligned tail passages, and short windows with little correct context. Run records also flag unprotected or uncertain OCR characters without replacing them. Next useful test: obtain blinded reviews of these held-out windows, then compare S4 with a frozen anchor-focused variant on a fresh split and use repairs only where source integrity and independently verified correspondence improve.

The full-corpus dry run produced 73 windows for 145 pages, of which 20 had no supported VI context. Full live execution was withheld because the approved release criterion requires independent semantic evidence. Stage 04 CSV exports are available for the evaluated runs.

## Artifacts and execution

- [Benchmark](../benchmark/pilot_v1/benchmark_comparison.xlsx) · [metrics](../benchmark/pilot_v1/metrics.json) · [semantic review](../benchmark/pilot_v1/semantic_review.xlsx)
- [Ablation](../ablation/pilot_v1/ablation_results.xlsx) · [metrics](../ablation/pilot_v1/metrics.json)
- [Held-out](../heldout/frozen_v1/heldout_comparison.xlsx) · [metrics](../heldout/frozen_v1/metrics.json) · [blind reference packet](../heldout/frozen_v1/heldout_reference_packet.xlsx) · [semantic review](../heldout/frozen_v1/semantic_review.xlsx)
- Every executed run contains `han_segments.jsonl`, `han_segmented.xlsx`, its request log and window checkpoints. The benchmark reused the exact-payload prior Separate response. Network requests logged: benchmark 6, ablation 16, held-out 47. The initial benchmark was resumed after a malformed numeral exposed a converter exception. The ablation was resumed after a shell timeout; the successful payload cache avoided replaying prior requests.
