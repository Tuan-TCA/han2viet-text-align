# Gold-label status audit

## Finding: the current files do not contain independently verified Gold labels

### `inputs/Semantic_Gold_Review_verified_v2.xlsx`
- Sheet: `API_Row_Review`
- Rows: 15
- `Proposed_Label` row-level values: 5 TRUE, 7 FALSE, 3 UNKNOWN
- `Reviewer_Label`: 0 of 15 populated
- `Corrected_Groups` contains proposed spans and explanations; it is not a completed independent adjudication.

The workbook Readme reports 5 TRUE / 8 FALSE / 2 UNKNOWN, which conflicts with the 15 row-level values. Use the row-level values (5/7/3) for the provisional count and log the Readme discrepancy. The word `verified` in the filename does not change the row-level fact that every `Reviewer_Label` cell is blank. The 5/8/2 distribution is a provisional proposal, not Gold.

### `inputs/Stage04_Gold_Review_Pack.xlsx`
- Sheet: `Blind_Review`
- Rows: 24
- `Reviewer_Label`: 0 of 24 populated
- The workbook is a review form, not a completed review.

### Previous V4 pilot
- V4 `Assessment` fields are source-based preliminary judgments.
- They must not be copied into `Label_Target`.

## Required policy

1. Keep `Label_Target = UNKNOWN` until an independent reviewer has adjudicated the full Han and Vietnamese spans.
2. Preserve prior proposed labels in separate columns such as `Prior_Proposed_Label` or `LLM_Review_A`.
3. If two independent models are available, obtain blind outputs separately; these are still model opinions, not human Gold.
4. Do not show the prior proposed label, API score, or V4 correction rationale to a blind reviewer before their first assessment.
5. Exclude UNKNOWN from TRUE/FALSE denominators. Report the number of reviewed and unreviewed cases explicitly.
6. A partial match, correct topic with wrong amount/person/place, mixed assignment, or material omission/addition is not TRUE under the strict complete-semantic-match rule.

## Consequence

The Stage04 pipeline can be implemented and benchmarked structurally, but a claim that V4 improves semantic correctness requires independent Gold review. If no human reviewer or independent adjudication source is available, finish the blind review packet and report semantic accuracy as NOT MEASURED rather than inventing labels.
