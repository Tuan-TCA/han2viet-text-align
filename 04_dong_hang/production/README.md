# Stage04 production operator guide

Run from the repository root. The official path is frozen S4 + T1, B2 page context with B1 fallback, Kim Hán Nôm Alignment, strict source projection, then global reconciliation. V4 defaults to false; enabling it emits a separate diagnostic ledger and does not change the official dataset.

## Offline and live entry points

```powershell
$cli = '04_dong_hang/production/cli.py'
$expanded = '04_dong_hang/production/config/expanded.json'
python -B $cli validate
python -B $cli plan
python -B $cli dry-run --run-id my-offline-run
python -B $cli resume --run-id my-offline-run
python -B $cli export --run-id my-offline-run
python -B $cli audit --run-id my-offline-run
```

Integrate Agent 2's completed mapping **in place, read-only**, with `python -B $cli validate --config $expanded`. Then `python -B $cli plan --config $expanded` lists its windows without API access. The expanded profile requires `page_mapping_refined.jsonl`, `window_context_refined.jsonl` and `viet_segments_extended.jsonl` under `03_text_sach/artifacts/coarse_mapping_v2/`. It checks both Cap_02 workbooks. It never substitutes the current mapping. Use an existing `SINONOM_TOKEN` only for live execution.

**After explicit live approval**, one command runs load, validation, planning, alignment, reconciliation, export and audit:

```powershell
python -B $cli run --config $expanded --run-id expanded-001 --approve-live
python -B $cli resume --config $expanded --run-id expanded-001 --approve-live
python -B $cli export --config $expanded --run-id expanded-001
python -B $cli audit --config $expanded --run-id expanded-001
```

New runs require unused IDs. Resume uses the recorded mode and refuses changed input, configuration or production code. Do not run two writers on the same ID. If a service rate limit interrupts execution, consult `progress.json`, wait for the service deadline, then resume. `export` and `audit` do not need a token. A checkpointed offline miss records **unevaluated** input; an offline run cannot be promoted into a live run by resuming it.

## Input and execution contract

Paths in JSON configurations are relative to the repository root; the mapping and context filenames are relative to `mapping_dir`. The VI segment inventory must match the configured eligible workbook rows. Workbook order and `CAU_VIET` row define order, not the spelling of the ID. The expanded profile also cross-checks the published T1 projections. Mapping `Selected_VI_IDs` and VI context must agree. Extra range and padded ID lists are included when available. `book_transition` evidence is preserved. A partial page without a verified supported sub-page partition is withheld in full, including units crossing it.

Each window uses whole S4 segments and all available VI context. Adjacent pages overlap. An unsuccessful or incompletely resolved initial request can generate recovery requests restricted to contiguous uncovered Han runs and expanded context. An exact match of endpoint and complete submitted payload is required for replay. No request-count budget is set. Bounded service retries and Retry-After handling are inherited from the client. A successful HTTP/API response may still contain partial, ambiguous, or untraceable rows.

## Output contract

`artifacts/production/<run_id>/` (under `04_dong_hang/`) contains the source identity and hashes (`production_manifest.json`), per-window IDs and status, request/response log, exact-payload cache, progress, and atomic window checkpoints. `alignment_raw.jsonl` contains projected groups, including original API rows. `requests.jsonl` preserves response bodies and failures. The global reconciler considers all primary/recovery responses across all windows; merged duplicates retain their occurrences. Strict evidence winners survive; ties abstain. `rejected_candidates.jsonl` and `normalization_review.jsonl` retain alternatives or errors for review.

`alignment_final.jsonl` holds the selected source pairs and provenance. `alignment_final.xlsx` uses the official template directly from Git HEAD, including its instruction row. Its binary semantic fields are blank; the audit sheet and internal records retain `UNKNOWN`. The CSV uses the same header and no instructional/sample rows. Remaining Han **and** VI character spans are explicitly listed with source text. `audit` verifies disjoint and complete source accounting, source hashes, final order, request references and template compatibility. `metrics.json` and `production_report.md` distinguish execution, source mapping and independent semantic evidence. Offline structural coverage includes only exact cached predictions.

Production integration tests: `python -B -m unittest discover -s 04_dong_hang/production/tests -v`. They prohibit network calls and use the saved benchmark responses and a synthetic expanded-mapping fixture against real Book V/VI source workbooks.
