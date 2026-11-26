# V4 Generalization Specification

## Objective

Turn the current Cap_01 V4 pilot into a reusable Stage04 refinement engine. The engine must improve alignment groups without relying on page-specific offsets, fixed VI IDs, or hand-written corrections for the current benchmark.

## Inputs

- Stage03 S4 Han segments with original text, page ranges, global offsets, per-character source spans, and source provenance.
- T1 Vietnamese segments with original IDs, source rows, page ranges, normalized text, and reversible offsets.
- Raw Alignment API responses and immutable baseline groups.
- Page-level mapping context and verified anchors, with confidence/status kept explicit.
- Optional OCR/source scans for human review.

## Required modules

### 1. Input normalization and reversible mapping
- Normalize Vietnamese thousands separators such as `2.344 -> 2344` and `1.234.567 -> 1234567`.
- Do not alter decimal values, dates, identifiers, or ordinary sentence punctuation.
- Preserve original text and a reversible normalized-to-source offset map.
- Keep Han and Vietnamese source strings immutable.
- Reject any transformation that cannot round-trip to the original source.

### 2. Robust response mapping
- Resolve API indices against the exact request payload.
- Detect out-of-range, partial, ambiguous, duplicated, or non-monotonic mappings.
- Never accept a substring match when multiple source occurrences are possible without disambiguation.
- Keep `Mapping_Success`, `Boundary_Match`, and `Semantic_Correctness` as separate fields.

### 3. Gap recovery
- Detect uncovered Han and Vietnamese spans independently.
- Generate candidate recoveries only from source-contiguous regions and corroborating page/VI context.
- Whitespace-only gaps may be crossed only when the original source confirms that the gap contains no meaningful character.
- Never silently skip non-whitespace source text, OCR characters, or a different VI_ID.
- Retain rejected and ambiguous gap candidates in the correction log.

### 4. Boundary correction and split
- Generate candidate boundaries from S4 unit boundaries, Separate marks, punctuation, numeral/entity protection, and source-backed linguistic cues.
- Permit a boundary inside an S4 unit only when source offsets and independent evidence support it; log the split explicitly.
- Protect numeral, date, person, place, and monetary-expression interiors from accidental splitting.
- Keep original Separate boundaries and S4 marks as provenance, not as unquestionable truth.

### 5. Merge and aggregation
- Merge only consecutive, non-overlapping groups when the source span is contiguous and evidence supports the full combined correspondence.
- Never merge across a meaningful Han gap, Vietnamese gap, overlap, or intervening VI_ID.
- Distinguish a legitimate N–M group from a mapping failure.
- Preserve the original group list and emit a new candidate list.

### 6. VI reassignment
- Reassignment candidates must use page-level mapping, verified anchors, source order, named entities, numbers, and contextual evidence.
- Estimated page mapping is context only; it is not a semantic label.
- Do not force a VI_ID into a Han window merely because it is the nearest ID.

### 7. Duplicate and conflict detection
- Detect duplicated Han coverage, duplicated VI coverage, order violations, and repeated source clauses.
- Do not automatically delete repeated text: it may genuinely occur twice in the source.
- Store each alternative with its provenance and reason.

### 8. Candidate ranking and abstention
- API score may rank candidate hypotheses but is not proof of semantic correctness.
- Combine structural, mapping, source, numeric, entity, and contextual evidence with calibrated weights.
- When evidence conflicts or is insufficient, abstain and set `Label_Target = UNKNOWN`.
- Do not use benchmark reference spans as production rules.

## Immutable outputs

Every refinement run must preserve:
- Exact request payload and raw response.
- Original API groups.
- Refined candidate groups.
- Before/after Han and VI spans.
- VI_ID changes.
- Rule/model provenance.
- Evidence, confidence, and abstention reason.
- Source hashes and configuration/code identity.

## Required output schema

At minimum:
`group_id, han_start, han_end, han_text, vi_ids, vi_text, alignment_type, api_score, mapping_status, coverage_status, correction_type, correction_reason, evidence_sources, confidence, Label_Target, review_status`.

`Label_Target` is `UNKNOWN` unless independently adjudicated.

## Non-goals

- Do not hardcode `[893,1044)`, `[1404,1426)`, or any other pilot offsets.
- Do not use fixed Cap/page/VI_ID-specific correction rules.
- Do not modify Stage02 or Stage03.
- Do not interpret full coverage or a high API score as semantic correctness.
