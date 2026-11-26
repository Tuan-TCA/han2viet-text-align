# Stage 03B — Coarse Page Mapping V2 (Book VI Integration)

## 1. Executive Summary

- **Coverage expansion**: Supported/mapped Han pages increased from **103** (53 Cap_01 + 50 Cap_02 full + 1 Cap_02 partial = 104 with partial, 103 full) to **140/145** full-supported pages (`Cap_01` 001–053 + `Cap_02` 001–087), with **0** partial pages and **5** unresolved pages (`Cap_02` 088–092).
- **Refined page status counts (V1 → V2)**: `{'VERIFIED': 9, 'LOW_CONFIDENCE_ESTIMATED': 84, 'AMBIGUOUS': 7, 'HIGH_CONFIDENCE_ESTIMATED': 3, 'PARTIAL': 1, 'UNMATCHED': 41}` → `{'VERIFIED': 14, 'LOW_CONFIDENCE_ESTIMATED': 115, 'AMBIGUOUS': 7, 'HIGH_CONFIDENCE_ESTIMATED': 4, 'UNMATCHED': 5}`.
- **Vietnamese corpus inventory**: Extended from **1,676** eligible segments (`685` Cap_01 + `991` Cap_02 Book V) to **2,054** eligible segments (+`378` Cap_02 Book VI segments from `VIET_0405-0439.xlsx`, namespace `Cap_02_VI-VI-*`), all exported in `viet_segments_extended.jsonl` with reversible T1 character spans and zero ID collisions.
- **Page 051 cross-book transition**: Upgraded from `PARTIAL` (`[105, 105]`) to `VERIFIED` (`[105, 405]`, printed pp. 408–409, physical width = 2 pages), preserving all 19 Book V p.105 segments and all 8 Book VI p.405 segments (27 segments in reading order) and documenting the exact intra-S4 transition at global offset `40812` (after heading `撫邊雜錄卷之六` at `[40805, 40812)` inside `Cap_02-051-052-S4-0006`).
- **API usage**: **123** live Alignment API calls this execution (logged total in V2 `requests.jsonl`: **123**), **15** exact-payload cache hits, **2** retries, **0** HTTP 429 events, **4** permanent failures, halt=`None`.
- **Semantic caveat**: Coarse mapping provides candidate page/segment windows only. **Zero Gold semantic labels (`Label_Target`) are assigned or inferred.**

## 2. Structural Comparison (Continuous Physical Page Coordinates)

| Scope | Method | Ranges | Mean width (pages) | Median width | Backward transitions | Gap pages | Excess overlap |
|---|---|---:|---:|---:|---:|---:|---:|
| Cap_01 (001-053) | B0 | 53 | 31.53 | 31.0 | 0 | 0 | 1553 |
| Cap_01 (001-053) | B1 | 53 | 2.21 | 3.0 | 0 | 2 | 19 |
| Cap_01 (001-053) | B2 | 53 | 2.26 | 2.0 | 0 | 0 | 19 |
| Cap_01 (001-053) | local | 53 | 2.23 | 2.0 | 2 | 2 | 21 |
| Cap_02_Book_V (001-050) | B0 | 50 | 51.12 | 52.0 | 0 | 0 | 2402 |
| Cap_02_Book_V (001-050) | B1 | 50 | 2.10 | 2.0 | 0 | 16 | 3 |
| Cap_02_Book_V (001-050) | B2 | 50 | 2.32 | 2.0 | 0 | 6 | 3 |
| Cap_02_Book_V (001-050) | local | 50 | 2.18 | 2.0 | 0 | 15 | 4 |
| Cap_02_Book_VI (051-087) | B0 | 37 | 10.35 | 10.0 | 0 | 0 | 310 |
| Cap_02_Book_VI (051-087) | B1 | 37 | 1.70 | 1.0 | 0 | 0 | 7 |
| Cap_02_Book_VI (051-087) | B2 | 37 | 1.89 | 2.0 | 0 | 0 | 6 |
| Cap_02_Book_VI (051-087) | local | 37 | 1.92 | 2.0 | 0 | 0 | 8 |
| Cap_02_Combined (001-087) | B0 | 87 | 33.78 | 50.0 | 0 | 0 | 2713 |
| Cap_02_Combined (001-087) | B1 | 87 | 1.93 | 2.0 | 0 | 16 | 10 |
| Cap_02_Combined (001-087) | B2 | 87 | 2.14 | 2.0 | 0 | 6 | 9 |
| Cap_02_Combined (001-087) | local | 87 | 2.07 | 2.0 | 0 | 15 | 12 |

Note: For `Cap_02`, Book V PDF pages `1–105` correspond to printed pages `304–408` and Book VI PDF pages `405–439` correspond to printed pages `409–443` (140 consecutive printed pages). Widths, gaps, and monotonicity across the Book V → Book VI seam at Han page 051 are evaluated in continuous physical page coordinates (`1..140`) so the PDF numbering jump (`105 → 405`) does not create a synthetic 299-page gap.

## 3. Vietnamese ID Coverage & Non-Exclusion Audit

| Subset | Total Eligible VI IDs | In `Selected_VI_IDs` | Touching `B2_Range` | In `±1` Page Padded Context | In `viet_segments_extended.jsonl` |
|---|---:|---:|---:|---:|---:|
| Cap_01 (VIET_0186-0251) | 685 | 439 (64.1%) | 685 (100.0%) | 685 (100.0%) | 685 (100.0%) |
| Cap_02 Book V (VIET_0001-0105) | 991 | 580 (58.5%) | 928 (93.6%) | 991 (100.0%) | 991 (100.0%) |
| Cap_02 Book VI (VIET_0405-0439) | 378 | 324 (85.7%) | 378 (100.0%) | 378 (100.0%) | 378 (100.0%) |
| All Corpus Combined | 2054 | 1343 (65.4%) | 1991 (96.9%) | 2054 (100.0%) | 2054 (100.0%) |

As in Stage 03B V1, `Selected_VI_IDs` on unanchored B2 pages lists only the specific segments matched by the winning 10-segment probe, so downstream Stage 04 alignment **must not** treat `Selected_VI_IDs` as a hard exclusion filter. Using `padded_context_vi_ids` (`B2_Range ∪ B1_Range ± 1` page) on `Cap_02` 051–087 retains **378/378 (100.0%)** of eligible Book VI segments, and `viet_segments_extended.jsonl` retains **2,054/2,054 (100.0%)** across both Caps.

## 4. Hidden-Anchor Leave-One-Out Validation

**All 15 folds (Cap_01 + Book V + Book VI)**:
- `B0`: 22/22 anchor overlaps recovered; mean distance 0.00 VI pages over 15/15 folds.
- `B1`: 17/22 anchor overlaps recovered; mean distance 0.22 VI pages over 15/15 folds.
- `B2`: 17/22 anchor overlaps recovered; mean distance 0.20 VI pages over 14/15 folds.

**Book VI 5 folds (51, 61, 71, 81, 87)**:
- `B0`: 6/6 anchor overlaps recovered; mean distance 0.00 VI pages over 5/5 folds.
- `B1`: 5/6 anchor overlaps recovered; mean distance 0.10 VI pages over 5/5 folds.
- `B2`: 6/6 anchor overlaps recovered; mean distance 0.00 VI pages over 5/5 folds.

## 5. Downstream Context Comparison (Paired B0 vs B1 vs B2)

- `B0` (10 matched pages across Cap_01, Book V, Book VI): mean Han/VI coverage `0.963` / `0.913`; unresolved groups: `8`.
- `B1` (10 matched pages across Cap_01, Book V, Book VI): mean Han/VI coverage `0.982` / `0.981`; unresolved groups: `2`.
- `B2` (10 matched pages across Cap_01, Book V, Book VI): mean Han/VI coverage `0.972` / `0.981`; unresolved groups: `2`.

## 6. Remaining Unmatched & Ambiguous Pages

- **Unmatched Han pages (5)**: `['Cap_02:088', 'Cap_02:089', 'Cap_02:090', 'Cap_02:091', 'Cap_02:092']`
  - `Cap_02:088–089`: Ngô Thì Sĩ's postface (*Phủ biên tạp lục bạt*, 1777); Vietnamese text begins at PDF p. 440, outside `VIET_0405-0439.xlsx`. Cross-page S4 unit `Cap_02-087-088-S4-0005` bridges Book VI's last two chars `[52417,52419)` into page 088.
  - `Cap_02:090`: Duplicate scan of `Cap_02:001` (Book V opening `撫邊雜錄卷之五...人才何代無之`); intentionally kept unmatched to prevent false alignment to Book VI.
  - `Cap_02:091–092`: Archival shelfmark OCR fragments (`R16061`, `01`); no literary text.
- **Ambiguous Han pages (7)**: `['Cap_01:006', 'Cap_01:026', 'Cap_02:003', 'Cap_02:004', 'Cap_02:007', 'Cap_02:008', 'Cap_02:022']` (competing candidates within `<0.5` adjusted score and `>=2` pages apart; inspect `uncertain_pages.xlsx` and retain union/padded candidate context in Stage 04).

## 7. Integrity & Frozen Artifact Verification

- Frozen S4 segments verified: **2808** segments, **53328** Han characters, `exact_reconstruction = True`.
- Unaffected mappings verified identical to V1: `Cap_01` `001–053` (**53/53** exact), `Cap_02` `001–050` (**50/50** exact), `Cap_02` `088–092` (**5/5** exact).
- Shared Stage02/Stage03/Stage03B/Stage04_V4_Handoff files modified: **0**.
- See `STAGE04_INTEGRATION_GUIDE.md` for exact Stage 04 V4 consumption instructions.
