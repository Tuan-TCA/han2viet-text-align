# Stage 03 — ablation

Requests logged: 16; run completed.
Length model: 1.525 Han content characters/VI token; 6 non-evaluation anchors.
Semantic encoder: local_omnia_align. Independently labelled held-out references: UNAVAILABLE.

| Window | Method | Alignment | Segments | Exact CG / DS / agreed | Mapped groups awaiting semantic review |
|---|---|---|---:|---:|---:|
| Cap_01-001-002 | M5 | ok | 15 | 3/12 / 5/12 / 3/8 | 11 |
| Cap_01-001-002 | no_length | ok | 12 | 4/12 / 6/12 / 4/8 | 12 |
| Cap_01-001-002 | no_semantic | ok | 15 | 3/12 / 5/12 / 3/8 | 11 |
| Cap_01-001-002 | no_numbers | ok | 11 | 3/12 / 3/12 / 3/8 | 11 |
| Cap_01-001-002 | no_entities | ok | 11 | 2/12 / 3/12 / 2/8 | 10 |
| Cap_01-001-002 | no_direct_separate | ok | 15 | 3/12 / 5/12 / 3/8 | 11 |
| Cap_01-001-002 | no_separate | ok | 11 | 0/12 / 0/12 / 0/8 | 10 |
| Cap_01-001-002 | no_s4 | ok | 11 | 3/12 / 3/12 / 3/8 | 11 |
| Cap_01-001-002 | no_repair | ok | 11 | 3/12 / 3/12 / 3/8 | 10 |

Exact compares one mapped alignment group per VI ID, with whitespace-equivalent edges. Mean IoU scores missing matches as zero. Boundary metrics compare segment endpoints, not final API groups. Verified positives and negatives are both zero until independent review; no verified-positive rate is estimable. Compare coverage and unresolved groups as diagnostics, not semantic quality.
