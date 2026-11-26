# Offline acceptance results

| Executed suite | Passed | Failed |
|---|---:|---:|
| `04_dong_hang/production/tests` | 9 | 0 |
| `04_dong_hang/tests` | 22 | 0 |
| `pipeline/tests` | 16 | 0 |
| `04_dong_hang/v4_release/test_engine.py` | 9 | 0 |
| `Stage04_V4_Handoff/previous_v4/test_stage04_v4.py` | 9 | 0 |
| `Stage04_V4_Handoff/tests/test_handoff_pack.py` | 11 | 0 |
| `03_text_sach/tests` | 15 | 0 |
| Total | 91 | 0 |

Current profile validated; plan emitted 143 windows. Full offline workflow, resume, export and audit executed. The request-log SHA-256 did not change during resume/export/audit. The 143 primary checkpoints comprise 6 successful cached responses, 96 cache misses, and 41 withheld windows. The 107 total cache misses include 11 additional recovery jobs. Network calls: zero. See `metrics.json` for source mapping outcomes and `production_audit.json` for character-level accounting. Expanded-profile validation reported the missing `coarse_mapping_v2/page_mapping_refined.jsonl`; no fallback was used. Book V/VI compatibility was exercised with a test mapping, not treated as acceptance of Agent 2’s actual release.
