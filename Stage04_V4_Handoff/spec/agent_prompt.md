# Agent Task: Complete the Stage04 V4 Pipeline in Four Steps

You are working in the user's NLP project repository. **Execute the work, write code, run tests, run the permitted experiments, and produce the artifacts. Do not respond with another plan only.**

The user wants the Stage04 pipeline completed through these four steps:
1. Close the source continuation and audit the current alignment.
2. Establish a defensible Gold/review dataset.
3. Generalize the V4 refinement algorithm.
4. Benchmark the frozen V4 pipeline on fresh data from both Caps and prepare the Stage04 handoff.

Extract `Stage04_V4_Handoff/` into the project root before starting. It contains the source files and generated handoff artifacts described below.

---

## A. Required handoff files and exactly how to use them

### 1. Full source and Stage03 inputs

- `Stage04_V4_Handoff/inputs/han_segments_full.jsonl`
  - Full Stage03 S4 segmentation for both Caps.
  - Use as the authoritative segmented Han input, including `id_zh`, `text_original`, `text_zh`, `page_start/page_end`, `global_raw_span`, `normalized_source_spans`, and `source[]`.
  - Do not substitute the small two-page pilot file for this full-corpus file.

- `Stage04_V4_Handoff/inputs/Cap_01_HAN_all_pages.txt`
- `Stage04_V4_Handoff/inputs/Cap_02_HAN_all_pages.txt`
  - Full raw OCR text for source reconstruction and exact source-slice verification.

- `Stage04_V4_Handoff/inputs/window_context_refined.jsonl`
  - Page-level Han and Vietnamese context. Use it to construct the Stage04 API inputs while preserving original VI IDs and source text.

- `Stage04_V4_Handoff/inputs/page_mapping_refined.jsonl`
  - Page-level mapping candidates and confidence/status. Treat estimated and ambiguous mappings as context only, never as verified semantic alignment.

- `Stage04_V4_Handoff/inputs/VIET_Cap01_0186-0251.xlsx`
- `Stage04_V4_Handoff/inputs/VIET_Cap02_0001-0105.xlsx`
  - Vietnamese source workbooks. Use `CAU_VIET` for source text and IDs, and `TRANG_VIET` for page anchors/evidence.

- `Stage04_V4_Handoff/inputs/production_manifest.json`
- `Stage04_V4_Handoff/inputs/production_audit.json`
  - Stage03 release identity, page/window status, reader verification, and processing audit.

- `Stage04_V4_Handoff/inputs/stage03_completion_report.md`
- `Stage04_V4_Handoff/inputs/stage03_final_report.md`
- `Stage04_V4_Handoff/inputs/coarse_mapping_report.md`
  - Read these before selecting context sizes or making claims about Stage03.

### 2. Existing V4 pilot and offline review

- `Stage04_V4_Handoff/previous_v4/stage04_v4.py`
- `Stage04_V4_Handoff/previous_v4/test_stage04_v4.py`
  - Existing V4 pilot implementation and regression tests. Run the tests first; preserve the old version.

- `Stage04_V4_Handoff/previous_v4/v4_alignment.json`
- `Stage04_V4_Handoff/previous_v4/v4_alignment.xlsx`
- `Stage04_V4_Handoff/previous_v4/v4_report.md`
- `Stage04_V4_Handoff/previous_v4/v4_comparison.xlsx`
  - Existing Cap_01 pilot results. Use as the baseline for V4 development, not as corpus-wide proof.

- `Stage04_V4_Handoff/inputs/baseline_reconstruction.json`
- `Stage04_V4_Handoff/inputs/refined_alignment.json`
- `Stage04_V4_Handoff/inputs/stage04_offline_comparison.xlsx`
  - Offline replay and refinement evidence. Reuse the exact saved API response when the endpoint and full payload hash match.

### 3. Page 3–4 source continuation candidates

- `Stage04_V4_Handoff/candidate_data/page3_4_candidate_extension.json`
  - Machine-readable candidate spans for Cap_01 Han `[893,1499)`, mapping to VI 0189-001 through VI 0190-005.
  - **Use as hypotheses to verify and compare against the API, not as Gold and not as production hardcoded rules.**

- `Stage04_V4_Handoff/candidate_data/page3_4_candidate_extension.xlsx`
- `Stage04_V4_Handoff/candidate_data/Stage04_V4_Handoff_Review_Pack.xlsx`
  - Human-readable candidate spans, S4 unit trace, Vietnamese source records, PDF text extracts, and original scan images.

- `Stage04_V4_Handoff/evidence/HAN_pdf_page_002.png`
- `Stage04_V4_Handoff/evidence/HAN_pdf_page_003.png`
- `Stage04_V4_Handoff/evidence/HAN_pdf_page_004.png`
  - Original Han scans for checking OCR characters and boundaries.

- `Stage04_V4_Handoff/evidence/VIET_pdf_page_189.png`
- `Stage04_V4_Handoff/evidence/VIET_pdf_page_190.png`
- `Stage04_V4_Handoff/evidence/VIET_pdf_pages_189_190_text.txt`
  - Vietnamese source scans and extracted text. Important: PDF page indices 189–190 show printed footer pages 192–193. Do not confuse PDF page index with printed page number.

- `Stage04_V4_Handoff/candidate_data/v4_candidate_extended.json`
- `Stage04_V4_Handoff/candidate_data/v4_candidate_extended.xlsx`
  - Combined V4 pilot plus the page 3–4 candidate extension. It covers only Cap_01 `[0,1499)`, not the full Cap_01. Use as a fixture for testing the generalized algorithm.

- `Stage04_V4_Handoff/candidate_data/source_integrity_report.json`
  - Verified offset contract and full-source reconstruction. It records 53 Cap_01 pages / 23,738 characters, 92 Cap_02 pages / 29,590 characters, 2,808 S4 segments, zero global-offset mismatches, and zero source-file-slice mismatches.

Important source-backed candidate hypotheses:
- `[893,1044)` → `Cap_01-VI-0189-001` + `Cap_01-VI-0189-002` as one continuous case split into two Vietnamese IDs.
- `[1044,1175)` → `Cap_01-VI-0189-003`.
- `[1175,1274)` → `Cap_01-VI-0189-004`.
- `[1274,1293)` → `Cap_01-VI-0190-001`.
- `[1293,1404)` → `Cap_01-VI-0190-002`.
- `[1404,1426)` → `Cap_01-VI-0190-003`.
- `[1426,1473)` → `Cap_01-VI-0190-004`.
- `[1473,1499)` → `Cap_01-VI-0190-005`.

Two special boundary cases must be explicitly checked:
- Offset `893` splits S4 unit `[881,905)`.
- Offset `1404` splits S4 unit `[1397,1411)`.
The candidate map records these splits and the original scans. Do not silently preserve or reject them without source review.

### 4. Gold/review status

- `Stage04_V4_Handoff/spec/gold_status_audit.md`
  - Read this before calculating any semantic accuracy.
  - `Semantic_Gold_Review_verified_v2.xlsx` has 15 `Proposed_Label` rows (row-level count: 5 TRUE / 7 FALSE / 3 UNKNOWN; the workbook Readme incorrectly/discrepantly reports 5/8/2), but **0/15 `Reviewer_Label` cells are filled**.
  - `Stage04_Gold_Review_Pack.xlsx` has 24 blind review rows, but **0/24 reviewer labels are filled**.
  - Therefore, the current project does not yet contain an independently adjudicated Gold set. The word `verified` in a filename is not sufficient evidence.

- `Stage04_V4_Handoff/candidate_data/Stage04_V4_Handoff_Review_Pack.xlsx`
  - Use its `Blind_Review` sheet to collect independent review for the 15 baseline groups and 8 continuation candidates.
  - The prior proposed labels are kept in a hidden sheet. Do not reveal them to blind reviewers before their first review.

### 5. Fresh benchmark inputs

- `Stage04_V4_Handoff/candidate_data/fresh_benchmark_seed.jsonl`
  - Exact page-level Han/VI context for six proposed fresh windows. Use this as the benchmark input seed.

- `Stage04_V4_Handoff/candidate_data/fresh_benchmark_candidates.csv`
- `Stage04_V4_Handoff/candidate_data/fresh_benchmark_seed.xlsx`
  - Window selection, page mapping status, VI IDs, source texts, and traceability.

- `Stage04_V4_Handoff/candidate_data/benchmark_exclusions.json`
  - Pages already used in known Stage03 development/held-out experiments. Exclude them.
  - Also inspect all actual Stage04 request logs, caches, manifests, and result files. If a proposed window has already been used for Stage04 evaluation, replace it with an unused adjacent window and document the substitution.

Proposed fresh windows:
- Cap_01: 027–028, 047–048, 051–052.
- Cap_02: 009–010, 026–027, 047–048.

These are candidates, not guaranteed unseen until you inspect the repository's actual logs.

---

## B. Four execution steps

### STEP 1 — Close the source continuation and audit mapping

1. Inspect the current repository layout and identify the exact Stage03 production artifacts and Stage04 loader/API client.
2. Run the existing V4 tests before modifying anything.
3. Recheck all source hashes and offset integrity against `source_integrity_report.json`.
4. Validate the eight page 3–4 candidate groups against:
   - full S4 segments and raw OCR;
   - original Han scans;
   - `CAU_VIET` workbook rows;
   - original VIET PDF scans and extracted text;
   - page-level context and mapping evidence.
5. Run Stage04 Alignment API experiments on the page 2–4 continuation using the existing API client, cache, and response parser. Compare API groups with the candidate source spans. Reuse a response only when endpoint and full payload are identical.
6. Check whether VI 0189-001 and 002 are best treated as one Han passage to two Vietnamese fragments. Inspect the two intra-S4 split boundaries explicitly.
7. Preserve all unresolved and alternative mappings. Do not force a semantic label from API score or coverage.

**Step 1 outputs**
- `source_continuation_audit.xlsx`
- `page3_4_api_comparison.xlsx`
- `page3_4_alignment.json`
- `source_integrity.json`
- raw request/response logs and checkpoints

### STEP 2 — Build a defensible Gold/review dataset

1. Use `gold_status_audit.md` and the supplied review workbooks to distinguish proposed labels from independently verified labels.
2. Produce a blinded review packet containing:
   - all 15 original S4+T1 baseline groups;
   - all changed V4 candidate groups;
   - the page 3–4 extension groups;
   - later, all fresh benchmark groups.
3. Hide API scores, previous proposed labels, V4 rationale, and model identities from the first blind review.
4. If two independent review models are actually configured, run them separately on the same blind source pairs and save their outputs in separate columns/sheets. Do not let one reviewer see the other's result.
5. Model reviews are opinions, not human Gold. If human adjudication is unavailable, leave `Label_Target=UNKNOWN` and report Gold coverage as unavailable.
6. Never turn all high-score or boundary-matching pairs into TRUE automatically.

**Step 2 outputs**
- `gold_review_packet.xlsx`
- `reviewer_a.jsonl` and `reviewer_b.jsonl` if configured
- `gold_status.json`
- `semantic_review.xlsx`
- unresolved adjudication list

### STEP 3 — Generalize the V4 refinement engine

Read and follow:
- `Stage04_V4_Handoff/spec/v4_generalization_spec.md`
- `Stage04_V4_Handoff/previous_v4/stage04_v4.py`
- `Stage04_V4_Handoff/previous_v4/test_stage04_v4.py`

Implement reusable modules for:
1. Vietnamese number normalization with reversible offsets.
2. Robust API response mapping and ambiguity handling.
3. Gap recovery.
4. Boundary correction and splitting.
5. Safe aggregation/merging.
6. VI_ID reassignment.
7. Duplicate and order-conflict detection.
8. Candidate ranking, abstention, and full provenance logging.

Requirements:
- No hardcoded page numbers, offsets, VI IDs, or case-specific corrections.
- Candidate generation must use source offsets, S4/Separate marks, page context, VI ordering, numeral/entity evidence, and API response structure.
- Never merge across meaningful non-whitespace gaps, overlaps, or intervening VI IDs.
- Do not discard repeated clauses; record alternatives.
- Preserve original API results immutably.
- API score is a ranking feature only, not semantic proof.
- Every unverified `Label_Target` stays UNKNOWN.

Add general unit tests for gaps, split-inside-S4, cross-page segments, repeated text, ambiguous mappings, number normalization, duplicate coverage, source round-trips, and legitimate N–M alignments.

**Step 3 outputs**
- versioned generalized V4 source code in `04_dong_hang/` (do not overwrite the old pilot)
- config file and documented input/output schema
- unit tests
- `v4_design_report.md`
- correction provenance schema

### STEP 4 — Run fresh benchmark and prepare the Stage04 handoff

1. Freeze V4 code and config before evaluating the fresh windows.
2. Inspect actual Stage04 request logs/cache to confirm that the six proposed windows are unseen. Replace any reused window.
3. Run S4+T1 baseline and generalized V4 on identical Han/VI inputs.
4. Do not impose an artificial request-count limit. Run as many distinct API requests as necessary to test the hypotheses. Reuse only exact-payload cache matches; log all requests and failures. Use checkpoint/resume.
5. Start from the Stage03 recommendation of 10 original VI segments around a valid page anchor, but preserve complete page context and test 5/10/15 where context sensitivity matters. Never silently truncate source text.
6. Use the existing Stage04 CSV reader contract. Validate output with the actual `load_han(folder, start, end)` reader in `04_dong_hang/temp/batch_sentence_alignment.py` or the current equivalent.
7. Export both Caps in the Stage04-compatible structure for the benchmark windows only. Do not run the full 143-page live alignment.
8. Compare:
   - Mapping success and unresolved rows;
   - Han/VI coverage and duplicated coverage;
   - exact spans and mean IoU where references exist;
   - exact full-VI-ID assignment;
   - alignment type;
   - correction precision and false-correction rate;
   - semantic TRUE/FALSE/UNKNOWN only on independently adjudicated cases;
   - API score distribution, latency, request count, and failure rate.
9. If Gold is unavailable, semantic accuracy is NOT MEASURED. Do not substitute mapping success or boundary metrics.
10. Make a release decision: V4 production candidate only if fresh, independently reviewed evidence supports improvement. Otherwise retain S4+T1 as baseline and keep V4 experimental.

**Step 4 outputs**
- `requests.jsonl`
- `results.json`
- `metrics.json`
- `comparison.xlsx`
- `semantic_review.xlsx`
- `stage04/Cap_01/V4/*.csv`
- `stage04/Cap_02/V4/*.csv`
- `manifest.json`
- `checkpoints/`
- `report.md`
- final CLI usage instructions

---

## C. Execution constraints

- API calls are authorized for the continuation experiment and the fresh benchmark. There is **no artificial request-count cap**.
- Use the existing `SINONOM_TOKEN` environment variable. Never print, log, or write the token to artifacts.
- Do not rerun Stage03 Separate for the full corpus. Stage03 S4+T1 is already released.
- Do not modify Stage02 or Stage03 source data.
- Do not run full-corpus live Alignment.
- Do not install dependencies unless absolutely required; if required, stop and report the blocker.
- Do not perform Git commits, pushes, or destructive cleanup.
- Write all new run outputs under a new directory, for example:
  `04_dong_hang/artifacts/v4_pipeline_release/<run_id>/`
- Preserve previous artifacts and use a new run ID. Support resume.
- If an input is missing, search the repository and supplied handoff package before asking the user.
- If independent reviewer credentials/tools are unavailable, complete the blind packet and keep Gold labels UNKNOWN. Do not fabricate reviews.

## D. Final report requirements

At completion, report:
1. Status of each of the four steps (complete / partial / blocked).
2. Exact files created and their paths.
3. Tests run and pass/fail counts.
4. API requests made, cache hits, failures, and windows evaluated.
5. Baseline vs V4 metrics with denominators.
6. Number of independently adjudicated Gold labels; if zero, state semantic accuracy is NOT MEASURED.
7. Whether V4 is ready for production or must remain experimental.
8. Exact command to run the benchmark again and exact command to consume Stage04 CSV outputs.

Proceed with execution. Do not stop after writing a plan.
