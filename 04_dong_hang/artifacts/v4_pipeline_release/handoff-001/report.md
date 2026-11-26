# Stage04 release: handoff-001

**Decision: retain S4+T1; V4 experimental.** Independent Gold: 0. Semantic accuracy: NOT MEASURED.

## Fresh primary comparison (full context)

|Metric|S4+T1|V4|
|---|---:|---:|
|groups|127|127|
|fully_mapped|70|70|
|partial|35|35|
|unresolved|22|22|
|han_covered|4181|4181|
|han_total|4747|4747|
|vi_covered|12351|12351|
|vi_total|14968|14968|
|han_duplicate|0|0|
|vi_duplicate|0|0|
|full_ids|96|96|
|total_ids|122|122|
|conflict_pairs|0|0|

API: 27 new requests, 0 cache hits, 0 failures. 140 CSV units verified in 6 windows. 382 blind records. No fresh reference spans; fresh exact accuracy, IoU, correction precision and false-correction rate unavailable.

Full context is primary. Sensitivity rows share Han input and differ in recorded VI context. V4 uses corroboration across contexts. Partial coverage is not a complete translation. See comparison.xlsx for per-context scores, alignment types, and rejected alternatives.

All package hashes and S4 source slices checked. The fee case crosses a Han page and a Vietnamese ID boundary. The four-copy register case has a plausible earlier start. Candidate agreement is descriptive, not Gold.

## Commands (repository root)
```powershell
python -B 04_dong_hang/v4_release/cli.py all handoff-001
python -B 04_dong_hang/v4_release/cli.py consume handoff-001 Cap_01 27 28
```
Same run ID resumes. See manifest.json for file inventory and freeze.json for decoder identity.
