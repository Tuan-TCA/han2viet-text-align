# Stage 03 — benchmark

Requests logged: 6; run completed.
Length model: 1.525 Han content characters/VI token; 6 non-evaluation anchors.
Semantic encoder: local_omnia_align. Independently labelled held-out references: UNAVAILABLE.

| Window | Method | Alignment | Segments | Exact CG / DS / agreed | Mapped groups awaiting semantic review |
|---|---|---|---:|---:|---:|
| Cap_01-001-002 | M1 | ok | 40 | 5/12 / 7/12 / 5/8 | 12 |
| Cap_01-001-002 | M2 | ok | 10 | 0/12 / 0/12 / 0/8 | 4 |
| Cap_01-001-002 | M3 | ok | 12 | 0/12 / 0/12 / 0/8 | 10 |
| Cap_01-001-002 | M4 | ok | 12 | 2/12 / 1/12 / 1/8 | 10 |
| Cap_01-001-002 | M5 | ok | 15 | 3/12 / 5/12 / 3/8 | 11 |
| Cap_01-001-002 | M6 | no_configured_offset_only_llm | — | — / — / — | — |

Exact compares one mapped alignment group per VI ID, with whitespace-equivalent edges. Mean IoU scores missing matches as zero. Boundary metrics compare segment endpoints, not final API groups. Verified positives and negatives are both zero until independent review; no verified-positive rate is estimable. Compare coverage and unresolved groups as diagnostics, not semantic quality.
