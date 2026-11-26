# Stage 03 — Vietnamese-guided Han segmentation

## Official production handoff (both Caps)

Use `run_release.py prepare` without `--run-id` for the official [production directory](artifacts/production/). Run from the project root. The first command starts a new directory, the second continues an interrupted run, and the third republishes and verifies completed checkpoints offline:

```powershell
python -B 03_text_sach/scripts/run_release.py prepare --live
python -B 03_text_sach/scripts/run_release.py prepare --live --resume
python -B 03_text_sach/scripts/run_release.py prepare --resume
```

S4 + T1 is fixed. Windows are consecutive pairs of Han pages within each Cap (one final singleton for Cap_01). Check `production_manifest.json:release_status == "complete"` before consuming outputs. On interruption, per-window checksummed checkpoints are authoritative; resume checks source/config/code identity, reuses completed windows, and retries failed windows. Start only one writer at a time. A matching cache or the `SINONOM_TOKEN` environment variable is needed for uncached work. No Alignment requests are made. Processing status (`successful`, `failed`, `pending`) is independent of VI mapping (`supported`, `partial`, `unmatched`).

**Stage 04 input contract**

- `stage04/Cap_01/S4/` and `stage04/Cap_02/S4/` are separate `--han-dir` inputs. Files named `NNNN-segments.csv` are UTF-8-SIG, keyed by segment **start** page, with columns `id_zh,text_zh,han_page_start,han_page_end,global_raw_start,global_raw_end`. A segment may end on the following page. The existing `04_dong_hang/temp/batch_sentence_alignment.py:load_han(folder, start, end)` accepts inclusive page ranges; it returns whole overlapping segments. IDs are unique across both Caps.
- `han_segments.jsonl` provides `text_original`, normalized `text_zh`, `id_zh`, `window`, `method`, inclusive `page_start/page_end`, `global_raw_span`, per-normalized-character `normalized_source_spans` and `source[]` containing page, source file and `file_span`. All character intervals are zero-based, end-exclusive Unicode code points. File slices address decoded UTF-8-SIG text before newline translation. Global offsets index the joined, edge-trimmed original page bodies, Cap_01 then Cap_02, with no inserted separator. Normalize for API use; use original slices for reconstruction.
- `window_context.jsonl` contains one record per manifest window: source pages, mapping evidence, page-specific `page_mapping_status`, window `mapping_status`, `processing_status` and ordered `viet[]`. Each VI record retains its workbook ID, source row, page range, original text, T1 string and normalized-to-original spans. Each T1 string is one VI input line. Overlap between neighboring VI contexts is intentional; use VI IDs, not array positions. Cap_02 051 has partial VI support; 052–092 remain source-linked Han without supported processed VI mapping. Never infer a semantic label from this flag. Use the per-page context status in preference to the coarse segmentation hint carried on individual segment rows.
- `coarse_alignment_audit.xlsx`, `production_audit.json`, `requests.jsonl`, `checkpoints/` and the [completion report](artifacts/production/stage03_completion_report.md) document inventory, exact reconstruction, requests and reader verification. `han_segmented.xlsx` is the human inspection copy.

## Earlier release sample and experiments

**Final release: S4 + T1 controlled over-segmentation.** The DP pipeline below remains the earlier experiment. Use `run_release.py prepare` for production preprocessing; it uses Separate or an exact cached response and never calls Alignment. See the [release decision and Stage 04 input contract](artifacts/release/final_v1/stage03_final_report.md).

```powershell
python -B 03_text_sach/scripts/run_release.py prepare --cap Cap_01 --pages 1 2 --run-id prepared_example
python -B 03_text_sach/scripts/run_release.py evaluate --run-id new_release_eval --live
```

Without `--live`, uncached Separate input is explicitly recorded as unavailable in `window_context.jsonl` and `prepare` exits nonzero. Add `--live` to permit Separate requests. Process both Caps with separate run IDs; `--pages FIRST LAST` is inclusive. Use `coarse_alignment_audit.xlsx` to identify partial and unsupported pages even in a two-page window that has Vietnamese context. Retain these pages for Stage 04 review. A new run ID prevents accidental overwrite; `--resume` checks the manifest and reuses saved cases/cache for a matching run.

Run from the repository root with the existing Python environment. Inputs are read from Stage 02. Live runs use `SINONOM_TOKEN`; raw responses in the run directory are redacted. No model downloads are needed: when enabled, semantic scoring loads the project-local OmniAlign model. If it cannot load, M3 records `NOT_RUN` and M5 reports a fallback. M6 is `NOT_RUN` because no offset-only LLM service is configured.

```powershell
python -B -m unittest discover -s 03_text_sach/tests
python -B 03_text_sach/scripts/run_pipeline.py benchmark --run-id new_run --live
python -B 03_text_sach/scripts/run_pipeline.py ablation --run-id new_run --live
python -B 03_text_sach/scripts/run_pipeline.py heldout --run-id new_run --live
python -B 03_text_sach/scripts/run_pipeline.py full --run-id preview --dry-run
```

`--resume` continues a named run with matching sources and configuration. Successful requests are reused within the run. Requests pause on authorization failures, exhausted quotas, or service throttling; resume only after addressing the logged reason and any `Retry-After`. `--live` is required for network calls, and `--no-model` disables local embedding. Full execution requires `--release <file>` and `--method <method>`; the release JSON must include matching `approved_method`, `config_sha256` from the manifest, and `heldout_review` evidence. Use a fresh `--run-id` for revised settings.

Outputs are under `artifacts/<mode>/<run-id>/` (`full` writes under `final`). `han_segments.jsonl` keeps original Han text, global code-point spans, physical file slices, and normalized offsets. `stage04/<cap>/<method>/` provides CSVs loadable by the existing Stage 04 batch reader. Pass the appropriate method folder as `--han-dir`; spans can cross page boundaries. `*.inputs.json` records the original Vietnamese context used for each window and boundary candidates. `semantic_review.xlsx` includes the actual alignment pairs and review fields. `heldout_reference_packet.xlsx` contains source text and a blank reviewer form without model boundaries, for an independent held-out review.

`Label_Target` starts `UNKNOWN`. Verify meaning, completeness, and OCR independently before marking a pair positive or negative. Boundary proxy scores, coverage, and API scores are diagnostics. See the [consolidated experimental report](artifacts/final/pipeline_report.md).
