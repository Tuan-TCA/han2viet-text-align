# Stage 04 V4 — Source-grounded pilot

**Status: CANDIDATE_NOT_PRODUCTION**

## What V4 changes

V4 starts from the frozen S4-T1 API replay and applies source-backed, offset-preserving corrections. It does not call Separate or Alignment API.

| # | Han span | Vietnamese ID | Operation | Assessment |
|---:|---|---|---|---|
| V4-001 | [0,35) | Cap_01-VI-0186-001 | KEEP_PARTIAL_SOURCE | FALSE |
| V4-002 | [35,55) | Cap_01-VI-0186-002 | KEEP_DIRECT_MATCH | TRUE |
| V4-003 | [55,213) | Cap_01-VI-0186-003 | RESTORE_UNCOVERED_HAN_TAIL | UNKNOWN |
| V4-004 | [213,267) | Cap_01-VI-0187-001 | KEEP_NUMERIC_REVIEW | UNKNOWN |
| V4-005 | [267,326) | Cap_01-VI-0187-002 | KEEP_NUMERIC_REVIEW | UNKNOWN |
| V4-006 | [326,337) | Cap_01-VI-0187-003 | KEEP_DIRECT_MATCH | TRUE |
| V4-007 | [337,372) | Cap_01-VI-0187-004 | KEEP_DIRECT_MATCH | TRUE |
| V4-008 | [372,545) | Cap_01-VI-0187-005 | RESTORE_GAP_AND_TRANSFER_REPEATED_CLAUSE | UNKNOWN |
| V4-009 | [545,647) | Cap_01-VI-0188-001 | SPLIT_AT_SEAL_FEE_CUE | UNKNOWN |
| V4-010 | [647,664) | Cap_01-VI-0188-002 | KEEP_DIRECT_MATCH | TRUE |
| V4-011 | [664,731) | Cap_01-VI-0188-003 | TRANSFER_MEMORIAL_DAY_CLAUSE | TRUE |
| V4-012 | [731,893) | Cap_01-VI-0188-004 | AGGREGATE_SELECTION_AND_PHU_LY | UNKNOWN |

## Important adjudications

- **Annual-gifts boundary:** the frozen API row S4-T1-011 ends at 727. It does not contain 諱日亦照. The verified review workbook has an internal contradiction: its SEM-011 prose describes [664,731), but the row-level offsets are [664,727). V4 follows the offsets and transfers [727,731) to VI 0188-003, making [664,731) the corrected candidate span; [731,758) begins the selection passage.
- **Seal-fee boundary:** V4 uses 545 because the OCR at that offset begins 有印. The alternative 547 cuts inside the next fee opening and is rejected.
- **Phù Ly:** V4 aggregates [731,893) for VI 0188-004. The detailed money OCR remains uncertain, so the group stays UNKNOWN.
- **Page-3 continuation:** [893,905) is retained as an unresolved Han prefix for VI 0189-001. VI 0189-001 through 004 are not forced into the two-page alignment.
- **Missing span:** [166,213) is restored to VI 0186-003; numerical OCR remains unverified.

## Coverage

- Candidate-aligned Han: 893/905 = 98.7%.
- Explicitly unresolved Han: [893,905), 12 characters.
- Han accounting including unresolved: 905/905 = 100%.
- Candidate VI IDs: 12 (0186-001 through 0188-004).
- Unresolved VI IDs: 4 (0189-001 through 0189-004), pending Han page 3.
- Source-based provisional labels: TRUE 5, FALSE 1, UNKNOWN 6.

These labels are not expert-adjudicated Gold. `Label_Target` remains UNKNOWN for every group.

## Known limitations

1. VI 0186-001 is a source fragment cut at the beginning; it is retained but FALSE under the strict complete-match rule.
2. VI 0187-001 and 0187-002 contain numeric discrepancies requiring visual review.
3. VI 0187-005 and 0188-001 contain similar Vietnamese closing clauses; their full semantic attribution remains UNKNOWN despite the source cue at 545.
4. VI 0188-004 contains many OCR-sensitive amounts; structural completeness does not prove exact semantic equivalence.
5. This is one Cap_01 pilot window. Do not apply its page-specific boundary cues as universal rules.

## Next production gate

Extend the same provenance-aware procedure to Han page 3 to resolve VI 0189-001..004, then test frozen V4 rules on fresh held-out windows from both Caps. Only after independent review should V4 be promoted to production.
