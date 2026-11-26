# Stage 04 V4 pilot package

## Build (offline)
Run from the directory containing the source files:

```bash
python Stage04_V4/stage04_v4.py   --han-segments han_segments.jsonl   --vi-workbook VIET_0186-0251.xlsx   --baseline-json baseline_reconstruction.json   --review-workbook Semantic_Gold_Review_verified_v2.xlsx   --out-dir Stage04_V4
```

## Validate
```bash
python Stage04_V4/test_stage04_v4.py
```

Requires Python 3.10+ and `openpyxl`. No API token, network request, model download, or dependency installation is needed.

## Outputs
- `v4_alignment.json`: structured candidate and source hashes.
- `v4_alignment.xlsx`: alignment, unresolved ledger, changes, metrics and rules.
- `v4_comparison.xlsx`: V0/V3/V4 comparison.
- `v4_report.md`: findings and production gate.
- `stage04_v4.py`: reproducible builder.
- `test_stage04_v4.py`: eight regression tests.

## Scope and safety
This is a Cap_01 two-page pilot. It is not a full-corpus alignment and must not be promoted to production without independent review and held-out testing on both Caps. All `Label_Target` values remain `UNKNOWN`.
