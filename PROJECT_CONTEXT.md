# CV16 — Hán–Việt parallel corpus: project handoff

## Read this first

- **Goal:** Build a sentence-aligned parallel corpus from *Phủ Biên tạp lục* (撫邊雜錄), attributed to Lê Quý Đôn, and its existing Vietnamese translation. This is corpus construction; the project does not generate translations.
- **Pipeline:** `01_nguon` (PDFs) → `02_ocr_tho` (Hán image OCR / Vietnamese PDF text extraction) → manual review → `03_text_sach` (corrected inputs and clean CSVs) → `04_dong_hang` (alignment and review workbooks) → reviewed corpus delivery (not complete).
- **Working sample:** `Cap_01` Hán PDF pages **1–2**, each with **16** cleaned segment rows, and Vietnamese PDF pages **170–190** with **156** extracted/cleaned records. The Vietnamese range is a candidate pool, not a verified mapping between editions. `Cap_02` has source PDFs and Hán page PNGs but no populated cleaned/aligned sample here.
- **Alignment entry points:** `04_dong_hang/align_v16_fixed.py` is the newest numbered local aligner source observed; `align_v15_Template.py` is its predecessor. `align_pure_api.py` is a separate direct-LLM prototype. Files labeled **v17** are local workbooks and statistics, with **no matching generator found** in the working tree or checked Git history. They are not v16 outputs.
- **Page numbers are 1-based PDF positions.** Raw names are zero-padded (`0001`, `0170`); `page_start` in the cleaned Vietnamese CSV is numeric when read by pandas. A printed page number is separate (e.g. Vietnamese PDF page 170 is printed page 173 in this sample). Never pair Hán page 1 with Vietnamese page 1 by name alone.
- **Snapshot:** 2026-11-19, `main` at `742ec8f`, plus local changes. The per-page cleaned Hán CSVs, v15/v16/API scripts, and v13/v16-style/v17 output artifacts are local/untracked in this snapshot. A fresh clone can be missing both usable inputs and the current scripts; use the status notes below instead of assuming it matches this checkout.

For future sessions: read this file first; use the last table to open only the code or artifact relevant to the task. Recheck affected paths after code/data changes and update this handoff when stage contracts change.

## 1. Sources and repository map

| Path | Contents / role |
| --- | --- |
| `01_nguon/Cap_01/` | `HAN.pdf` (53 pages), `VIET.pdf` (251 pages). |
| `01_nguon/Cap_02/` | `HAN.pdf` (92 pages), `VIET.pdf` (105 pages). All four source PDFs are unencrypted; verified with `pdfinfo`. |
| `01_nguon/Kiem_ke_nguon.xlsx` | Source inventory, sheet `Sheet1`: `Trường`, `HAN_Cap_01`, `VIET_Cap_01`, `HAN_Cap_02`, `VIET_Cap_02`. |
| `02_ocr_tho/Cap_01/HAN/` | OCR notebook, 53 flat page PNGs, nested page/column images and OCR results for pages 1–2, local `corrected/` material. |
| `02_ocr_tho/Cap_01/VIET/` | `viet-ocr.py` plus checked-in output under `VIET_pdfplumber/`. |
| `02_ocr_tho/Cap_02/HAN/` | 92 flat page PNGs; local `raw/` and `corrected/` are empty. |
| `03_text_sach/Cap_01/{HAN,VIET}/` | Hand-reviewed inputs, cleaners, and CSVs consumed by the aligner; details below. `03_text_sach.zip` is a local archive with the same sample file names, not a runtime input. |
| `04_dong_hang/` | Per-page aligners, review workbooks, annotation template, and `test/` experiments. |
| `OmniAlign/` | Git submodule (`MilkDargon/OmniAlign`, pinned at `bf2687e`); `OmniAlign/OmniAlign/` is the separate local model checkpoint directory. See §5. |
| `README.md`, `.gitignore`, `.gitmodules` | README is a title only; Git ignores local Python environments, new `images/`, `raw/`, `corrected/`, and model artifacts. Already tracked flat PNGs remain tracked. |
| `src/02_ocr_tho/`, `specs/02_ocr_tho/` | Historical scripts, inventory and plan are in `HEAD` but deleted in this working tree. Use `git show HEAD:<path>` for read-only reference. |

Keep source PDFs and raw extraction separate from edits. Page counts and folder names alone do not establish which passages correspond.

## 2. Raw extraction and OCR

### Hán: image preparation → column segmentation → PaddleOCR

Entry point: `02_ocr_tho/Cap_01/HAN/nlp-midterm-han-ocr (1).ipynb`. Read executable cells rather than relying on notebook headings; paths default to Kaggle (`/kaggle/input/.../01_nguon`, `/kaggle/working/CV16_nlp_midterm`), `CAP='Cap_01'`, `LANG='HAN'`, `PAGES_TO_PROCESS=[1, 2]`.

1. **Render pages.** PyMuPDF (`pymupdf`) uses `doc[page_no - 1].get_pixmap(dpi=144)` → `images/NNNN/NNNN.png`. This nested file is different from the flat `images/NNNN.png` inventory rendered by the older Poppler workflow.
2. **Preprocess.** `preprocess_page()` reads with OpenCV, keeps the top 92% of the page, converts to grayscale, applies non-local means denoising and CLAHE, and scales the longest side to 2,000 px.
3. **Split columns.** `extract_columns_final()` uses inverted Otsu thresholding, a vertical foreground projection smoothed by SciPy's median filter (size 9), a 10% gap threshold, and a forced gap around the central spine. It pads accepted columns, tries to split unusually wide columns at a projection minimum, and reverses the array for **right-to-left** reading. Saves `images/NNNN/NNNN-CC.png` (`CC` starts at 01). Check the plotted crops if OCR misses, merges, or reorders columns.
4. **Recognize.** Kaggle GPU path uses `paddlepaddle-gpu==3.2.0` (CUDA 12.6 package index), `paddleocr`, `gpu:0`, `lang='chinese_cht'`. Document orientation and unwarping are disabled, textline orientation is enabled. Detection uses a 1,600 px maximum side, box threshold 0.3 and detection threshold 0.2; the `predict` call overrides unclip ratio to 1.5 (constructor 2.0). Recognition threshold is 0.0. The notebook checks for a GPU and runs a synthetic convolution before initializing OCR. Other imports: OpenCV, NumPy, SciPy, Pillow, matplotlib, tqdm and IPython/Jupyter.
5. **Write results.** Sort column filenames, then sort detections within a column by polygon top coordinate (`min(y)`). Concatenate text within each column, then concatenate columns without inserting separators. Under `raw/NNNN/NNNN-CC/`, save `NNNN-CC_res.json`, `NNNN-CC_ocr_res_img.png`, and `result.txt`. JSON includes `dt_polys`, `rec_texts`, `rec_scores`, and recognition geometry/metadata. The page file `raw/NNNN/NNNN_reconstructed.txt` contains per-column text/mean scores plus the joined text. Page score is the mean of the scored column means, not a per-character confidence. Local raw pages have 18 column outputs each; the corrected tables have 16 rows each, so do not infer 1:1 raw-column-to-corrected-row mapping.
6. **Inspect/archive.** `print_tree()` displays the output tree. The last cell writes `raw_Cap01_HAN.zip` with `root_dir=HAN_DIR`, so despite its name it targets the full Hán stage directory, not specifically `raw/`.

Use a separate OCR kernel: the notebook has a `DELETE_RAW` confirmation cell that removes raw contents and Kaggle-specific cells that uninstall Torch and delete package directories. Skip those cells for ordinary inspection/reuse, especially in the OmniAlign environment. Rerunning render/OCR cells can overwrite same-name outputs; use separate output directories or preserve previous results before reruns.

### Vietnamese: extract the PDF text layer and reconstruct sentences

Entry point: `02_ocr_tho/Cap_01/VIET/viet-ocr.py`, with `numpy` and `pdfplumber` (needs `Page.extract_text_lines`). Example from the repo root, writing to a separate output so the sample is preserved:

```powershell
python .\02_ocr_tho\Cap_01\VIET\viet-ocr.py --pdf .\01_nguon\Cap_01\VIET.pdf --out .\outputs\viet-cap01-check --start 170 --end 190
```

CLI: `--pdf`, `--out`, `--start`, `--end`; bounds are inclusive. The default `--out` is `02_ocr_tho/Cap_01/VIET_pdfplumber` relative to the current directory (no `VIET/` component); the checked-in output is actually at `02_ocr_tho/Cap_01/VIET/VIET_pdfplumber/`. Use explicit paths.

| Functions | Behavior |
| --- | --- |
| `run`, `extract_page_lines`, `clean_text` | Validate the PDF and bounds, visit pages in file order, save raw `extract_text()`, and use line text and `(x0,x1,top,bottom)` coordinates for reconstruction. Normalize line text to NFC, collapse whitespace and remove spaces before select punctuation. If all selected pages are empty, exit with a message to use image OCR. |
| `drop_page_furniture`, `build_paragraphs`, `join_lines` | Optionally filter configured regexes; identify isolated printed page numbers at edges with a line-gap test. Infer paragraph boundaries from indentation and short preceding lines relative to page geometry. Join lines while retaining offset/score spans; do not add a space after a trailing hyphen. |
| `build_sentences`, `split_spans`, `_page_at` | Continue an unfinished paragraph onto a following page when the next first paragraph is not a new paragraph. Split on `.?!…` followed by an uppercase starter (or at end), with exceptions for abbreviations, initials and numbered markers. Store the start and end PDF pages, starting-page ID `NNNN-SSS`, and cross-page/incomplete flags. |
| `line_quality`, `_score_of` | Character-class/font sanity heuristic (0–1), averaged across contributing line spans by character overlap. `(cid:...)` yields 0 for that line; replacement characters cap it at 0.5. `needs_review` means score below 0.90. This **is not OCR confidence** or proofreading. |

Output: `NNNN/NNNN_page_text.txt`, `NNNN/NNNN_sentences.txt`, `NNNN/NNNN_sentences.csv`; root `all_sentences.csv`, `all_sentences.jsonl`, `summary.csv`. Records are grouped by start page, even when a sentence continues into the next page. CSVs are UTF-8 with BOM; TXT and JSONL are UTF-8. Sentence CSV columns: `id, confidence, page, page_end, text, n_chars, cross_page, incomplete_start, incomplete_end, needs_review`; JSONL has the same keys. Summary columns: `page, n_lines, n_sentences, mean_confidence, printed_page_no`. Checked sample: 21 page directories, 156 records, 10 cross-page, 1 incomplete start, 0 incomplete ends, 1 `needs_review`.

## 3. Manual review and cleaner contracts

There is no checked-in program that converts raw Hán OCR to the corrected table or raw Vietnamese CSV to a correction sheet. Review the original PDF/raw output and keep the corrected text in the input columns below before running cleaners. For Vietnamese, the current correction input preserves all 156 raw IDs in order and its `Corrected text` values match the raw `text` values in this snapshot; the filename/column does not prove review.

| Cleaner (under `03_text_sach/Cap_01/`) | Inputs beside script | Outputs beside script |
| --- | --- | --- |
| `HAN/clean_zh.py` → `clean_zh_text()` | Fixed prefixes `0001-corrected`, `0002-corrected`. Prefers `.xlsx`, then `.csv`. Current files are `0001-corrected.xlsx` (first sheet `New Text Document`) and `0002-corrected.csv`, each with `Cột, Text OCR, Lỗi OCR, Corrected text, Ghi chú / Giải nghĩa`; only `Cột` and `Corrected text` are read for output. | `<NNNN>-cleaned.csv`: `id_zh,text_zh`. Each current CSV has 16 rows. Tracked `zh_cleaned.csv` is a legacy file byte-identical to current `0001-cleaned.csv`, not a combined corpus or an input to v16. `KetQua_Align_HanViet.xlsx` here is an older result, not a cleaner input. |
| `VIET/clean_vi.py` → `clean_vi_text()` | Fixed file `170-190.csv`; selects `id,page,page_end,Corrected text` from the review table. | `vi_cleaned.csv`: `id_vi,page_start,page_end,text_vi`; 156 rows spanning PDF pages 170–190. Extraction flags and the quality heuristic are not propagated by the cleaner. |

Both cleaners map missing text to the empty string, remove `[ð?“”*_!]`, and collapse whitespace. In particular they remove `?` and `!`, which affects later splitting and punctuation-based QA. They preserve row order, write UTF-8 BOM CSV with no dataframe index, and **can overwrite** existing outputs. There are no cleaner CLI arguments. Run `python .\03_text_sach\Cap_01\HAN\clean_zh.py` or `python .\03_text_sach\Cap_01\VIET\clean_vi.py` only to regenerate intended files. Both run top-level logic on import and may pip-install packages (`pandas` for both, `openpyxl` for the Hán Excel input); do not import them just to inspect a helper. The separate ignored `02_ocr_tho/Cap_01/HAN/corrected/` copy is not read by `clean_zh.py`.

## 4. Alignment and Excel export

### v16 (`04_dong_hang/align_v16_fixed.py`)

Entry: `main()` → `run(cap, page, vi_start=None, vi_end=None, base_dir=None, model_dir=None, output_dir=None)` → returns workbook path. From the repo root:

```powershell
python .\04_dong_hang\align_v16_fixed.py 1 1 170 190 --output-dir .\outputs\v16-check
```

- Required positional args: `cap`, `page` (Hán PDF page); optional: `vi_start`, `vi_end` (inclusive filter on `page_start` **only**, not `page_end`). Omitted bounds leave that side open; omitting both uses all of `vi_cleaned.csv`. The example uses the entire current sample; select a verified passage window for a real alignment run.
- `--base-dir` defaults to the repository root inferred from the script location; `--model-dir` defaults to `<base-dir>/OmniAlign/OmniAlign`; `--output-dir` defaults to `04_dong_hang/`. The filename `KetQua_CapXX_TrangN.xlsx` has no version tag and can overwrite v15 or v16-style outputs in that directory.

| Order | Functions / data flow |
| --- | --- |
| 1. Read/filter | `find_han_file()` tries 1–7 digits of padding for `<page>-cleaned.csv` under `03_text_sach/Cap_XX/HAN/`. `run()` reads `VIET/vi_cleaned.csv` beside `HAN/`; requires Hán `text_zh` and Vietnamese `text_vi,page_start`. Drop null text / null Vietnamese start pages, filter by bounds, preserve input order, and reject empty sides. Hán `id_zh` isn't used for output IDs. |
| 2. Segment | `split_vi_text()` splits on whitespace after `. ; ? ! ,`, keeps all nonempty chunks, and attaches `page_start` and filtered/reset zero-based `row_id`. A row may produce multiple chunks; Hán rows are not split further. |
| 3. Lexical scores | `get_sino_tokens()` calls `from cn2vn import cn2vn` for Hán readings. `remove_accents()` lowercases, strips combining marks and maps `đ→d`; `word_tokens()` ignores punctuation/underscores. `build_anchor_matrix()` uses an inverted Vietnamese n-gram index to record the longest shared contiguous 2–10-token sequence for each Hán/chunk pair. |
| 4. Semantic scores | `OmniEncoder.encode()` embeds both sides using CPU float32 (`eval`, no grad), batches of 8, at most 1,024 tokens, attention-mask mean pooling and L2 normalization. The dot product gives the cosine matrix `S_SEM`. |
| 5. Combine / choose anchors | `build_similarity_matrix()` computes `clip((cosine+1)/2,0,1) + 1.5*clip(anchor_len/5,0,1)`. `select_monotonic_anchors()` finds a maximum-weight chain among lengths ≥3, strictly increasing on both sides. `run()` adds `0.5` to these cells as a soft bonus, not a hard lock. |
| 6. Optimize / validate | `standard_dp_align()` maximizes global monotonic score with `1-1`, `1-2`, `2-1`, `1-0`, `0-1`; merge/split score averages individual cell values, gaps cost `-1.5`. `_backtrace()` checks pointers and bounds. `validate_alignment()` requires ordered, exactly-once coverage of both index sequences and a supported move per step. `dynamic_window_dp()` is an unused helper in `run()`; it masks match positions around anchors, leaves gap transitions available and uses unmasked global DP only when no anchors are supplied. |
| 7. Project path / save | `to_index_map()` maps each Hán row to its Vietnam chunk indices. `run()` emits one row per retained Hán segment, joining the actual aligned chunks (not their full source rows), adds a note with Hán page, Vietnamese PDF pages and filtered source-row indices, and calls `write_template_xlsx()`. |

Important distinctions: the DP path preserves coverage, but the **workbook is a projection**. A `2-1` move can repeat the same Vietnamese text in two Hán rows; `0-1` moves have no dedicated exported row; `1-0` gives blank Vietnamese. With a broad candidate window, positive match scores and a substantial gap penalty can favor weak matches; score/path validity does not establish correctness. `make_pair_id()` formats `C{cap:03d}_V{sent_no:03d}` where `sent_no=(page-1)*16 + row_number` (row number starts at 1 after null removal). This fixed 16-row stride matches the sample but needs review for variable-length pages or cross-page merging.

### Output schemas and version evidence

**Annotation template columns (A–K):** `Pair_ID, Chinese, Vietnamese, OMISSION, ADDITION, MISSING, Alignment_Type, Punct_Anchor_Match, Label_Target, OCR_Conf_Min, Note`. In v15/v16 `Sheet1` uses row 1 for headers, row 2 for descriptions, and data from row 3 (freeze `A3`); only A–C and K are written. D–J are review fields: missing content, extra content, blank side, link type, punctuation/numeric cues, final training label, and minimum OCR confidence. The reference workbook `04_dong_hang/Sino_Vietnamese_Sentence_Alignment_Template.xlsx` has sheet `Alignment_Dataset` with example annotations; its description/example IDs do not supersede the actual writer's formula.

| Version/artifact | What is known |
| --- | --- |
| `align_v15_Template.py` | Same positional interface/data layout; `main()` changes cwd and may auto-install packages. Drops chunks of ≤5 characters. Scores `cosine + 5*anchor_len`. Runs global v1 DP and windowed v6 DP with every anchor ≥3 as a hard-anchor candidate and a +100 bonus. Fuses rows from the two paths (v6 for empty or >200-char v1 text except on hard-anchor rows), so path-level monotonicity isn't guaranteed after fusion. Outputs full original Vietnamese rows, which may repeat. |
| `KetQua_Cap01_Trang{1,2}.xlsx` | Existing 16-data-row workbooks with v16-style notes (including `Dòng Việt`) and blank D–J. Page 1 IDs `C001_V001`–`C001_V016`; page 2 `C001_V017`–`C001_V032`. Format verified; exact run commands/model provenance not recorded. |
| `KetQua_v13_Pro_Plus_{1,2}.xlsx` | Local legacy workbooks with 16 data rows each: `Han_Text,Viet_Chunks,Viet_Row_IDs,Viet_Text,Method`; corresponding v13 generator not identified. |
| `KetQua_Cap01_Trang{1,2}_v17.xlsx` + `_v17_statistics.json` | Local snapshots labeled `v17-semantic`, `meaning_translation`. Each used 16 Hán rows and 189 Vietnamese chunks from PDF pages 170–190 according to JSON. Page 1: 187 steps, 172 Vietnamese-only `0-1`, 12 `1-1`, 2 `1-N`, 1 `N-1`, one low-semantic step. Page 2: 185 steps, 170 `0-1`, 10 `1-1`, 4 `1-N`, 1 `N-1`, zero low-semantic steps. These are full path counts, not valid corpus-pair counts. |

**v17 contract from files only:** `Sheet1` also populates `Alignment_Type` and emits gap rows; IDs span `C001_V001`–`C001_V187` on page 1 and `C001_V017`–`C001_V201` on page 2, so IDs collide across workbooks. Before combining them, define a corpus ID scheme. `Alignment_Debug` has `Pair_ID, Alignment_Type, Han_Indices_1based, Vietnamese_Chunk_Indices_1based, Chinese, Vietnamese, Semantic_Cosine, DP_Score, Weak_Lexical_Anchor, Review_Flag, Vietnamese_Pages, Vietnamese_Source_Rows`. JSON top-level keys: `version, translation_type, inputs, alignment, parameters, definitions`; input paths are machine-local. Reported parameters: `neutral_cosine=0.3`, `gap_penalty=0.05`, `merge_penalty=0.05`, `anchor_weight=0.08`, `review_threshold=0.3`. JSON describes raw sentence/group cosine (not a probability), a centered score with merge penalty and weak lexical hint on `1-1`, and heuristic review flags rather than ground truth. Use these artifacts for comparison/debugging, not to claim exact reproducibility or annotation accuracy.

### Direct LLM prototype (`04_dong_hang/align_pure_api.py`)

`main()` → `run(args)` → `DirectAPI.align()` → `export_xlsx()`. Depends on `pandas`, `requests` and `openpyxl`. Uses the same cleaned CSV search, inclusive `page_start` filter and Vietnamese chunk split as v16, then **sends both indexed text arrays to the configured service** in one request per attempt. It uses no local embedding model, lexical anchors or DP. Choose a small verified window to control input/output size and retry cost. Only use an authorized endpoint and an approved set of texts; credentials belong in the environment, not in the handoff or Git.

- CLI shape: `python .\04_dong_hang\align_pure_api.py <cap> <page> [vi_start] [vi_end]` with `--base-dir`, `--output-dir`, `--save-raw`. `ALIGN_API_URL`, `ALIGN_API_TOKEN`, `ALIGN_API_MODEL` provide defaults for `--api-url`, `--token`, `--model`. `--auth` defaults to `bearer` and also supports `header`, `cookie`, and `none`; `--cookie-name` is used as the custom header or cookie name. `--timeout` defaults to 180 seconds; `--retries` defaults to two retries after the first attempt.
- `_request()` sends chat-completions JSON by default (temperature 0), or substitutes `{model}`, `{system_prompt}` and `{user_prompt}` into string values of `--request-template`. Accepts a direct `alignments` object, defaults to `choices.0.message.content` otherwise, and supports a custom dot-delimited `--response-path`. `parse_json_content()` handles text blocks, fenced JSON or an object.
- `validate_alignments()` expects a JSON `alignments` list of `{"zh":[...],"vi":[...]}` steps. Integers are zero-based; each group is contiguous and overall paths must cover both sides exactly once in order. No empty-on-both-sides steps. `DirectAPI.align()` retries HTTP/parse/validation errors with feedback to the provider (401/403/404 stop early). Structural validation is not evidence of semantic quality.
- Writes `KetQua_CapXX_TrangN_PURE_API.xlsx` using the same 11-column review layout, including one row per returned step and explicit Vietnamese-only insertions; `Alignment_Type` is inferred from group sizes, while annotation flags/labels/confidence stay blank. Review multi-unit gap types before using those labels: the current ternary expression can mislabel them. `--save-raw` also saves a JSON copy of input text and validated arrays beside the workbook. Insertion IDs lack a Hán page component and can collide across workbooks. No API run or matching output was observed during this handoff.

## 5. Environments, model, and troubleshooting

- **Platform:** Repo was inspected on Windows/PowerShell. `.venv/`, `.venv_paddle/`, and `env_omni/` are local ignored environments, not reproducible dependency manifests. There is no root lockfile or unified runner. For v16 the direct dependencies are `numpy`, `pandas`, `openpyxl`, `torch`, `transformers`, `cn2vn`. v15 and some experiments additionally mention `cn2an`; GA experiments use `deap` and the hybrid experiment can use `sentence-transformers`.
- **OmniAlign:** Submodule code and model weights are separate. The inner `OmniAlign/OmniAlign/` in this working tree has `model.safetensors`, `config.json`, tokenizer assets and custom `configuration.py`/`modeling.py`. Most are ignored, so a populated submodule alone does not provide a usable model. Upstream model is `WPS-Qingqiu/OmniAlign` on Hugging Face; submodule `README.md` explains placement and recommends Python 3.12. `example/requirements.txt` pins `torch==2.7.1`, `transformers==4.56.1` for upstream demos; the local model config also lists `4.56.1`. These pins were not tested for this repo. v16 sets `trust_remote_code=True`; use a trusted model directory. No model assets need to be read or loaded simply to understand the pipeline.
- **Integration boundary:** `OmniAlign/example/example.py` has `word_align()` and `sent_align()` for upstream demos; `example/corelib.py` implements overlapping sentence layers, top-k candidate search, and two-pass DP with a refined path. CV16's `OmniEncoder` calls Transformers directly and does **not** call that demo aligner or use its DP settings.
- **Missing CSV or empty window:** Check that the actual per-page CSV exists and is retained when moving checkouts; do not substitute `zh_cleaned.csv` for an arbitrary page. Check `page_start` bounds against PDF positions and ensure they load as numbers. Widen or shift only after checking passage correspondence.
- **Bad alignment:** Inspect the PDF/cleaned text pair and original Vietnamese sentence/row IDs first. Check punctuation losses and fragment boundaries, page-crossing paragraphs, candidate window, and then anchors/cosine and DP moves. Read `Note` for v16 or `Alignment_Debug` plus statistics for v17. A page's corrected table and candidate Vietnamese range require review independent of implementation quality.

## 6. Historical experiments and delivery status

- `04_dong_hang/test/` is an experiment/artifact directory, not an automated test suite. `align.py` and `align-ga-omni-free.py` are equivalent after line-ending normalization: `build_anchor_matrix()`, `build_pos_penalty()` and `OmniEncoder` feed `dp_align()`; `evaluate()` scores DEAP weights for semantic/lexical/position terms using anchor rewards and gap penalties. The experiment filters Vietnamese PDF pages 186–188 and writes `KetQua_GA_Omni.xlsx`. `align-hybird.py` (spelling as on disk) filters some note prefixes, uses `build_anchors()` with Sino-Vietnamese and numeric cues, tries OmniAlign and falls back to LaBSE, then runs anchor-bonus DP and exports `DONG_HANG` and `THONG_KE` to `KetQua_Omni.xlsx`. Old relative Windows paths depend on cwd and may not resolve from `test/`. The many other `KetQua_*.xlsx` are historical outputs, not verified references. `MA_TAC_PHAM_parallel.tsv` and `.xlsx` are sample artifacts; the workbook has `DONG_HANG` (`Han_Text,Viet_Text`) and `THONG_KE` rather than the final naming/schema below.
- Git-only OCR utilities in `HEAD:src/02_ocr_tho/`: `extract_page_images.py` uses `get_page_count()` (`pdfinfo`), `convert_page()` (`pdftoppm` at 300 DPI, skip existing) and `convert_pdf()` (both Hán PDFs, all pages); `extract_vietnamese.py` uses `extract_pdf()` with `pdftotext -layout -enc UTF-8`, writing one numbered raw TXT per page and summarizing failures; `prepare_vietnamese_samples.py` uses `extract_page()` to render VIET samples at 300 DPI (Cap_01 1/100/251, Cap_02 1/50/105). `pdf_inventory.txt` is the old `pdfinfo` record; `tempCodeRunnerFile.py` is an editor scratch fragment. `HEAD:specs/02_ocr_tho/PLAN_AND_TECH_STACK.md` records the original benchmark plan (PaddleOCR vs Transkribus, CER/time/manual effort), not evidence of completed benchmarking.
- Git-only alignment utilities in `HEAD:04_dong_hang/`: `align-ga-omni-final.py` actually uses fixed semantic/anchor scores and DP (not a GA in this version), legacy `zh_cleaned.csv`, Vietnamese pages 186–188, and writes `KetQua_Final.xlsx` (`Page,Han_Text,Viet_Text`). `convert_to_template.py` converts that to `Cap-01-P01.xlsx`, appends rows with a different ID convention, guesses types from gaps/length and writes placeholder labels/confidence. The scripts and those two workbooks are deleted locally; v15/v16 write the review template directly.
- **Final delivery per historical plan:** reviewed TSV (one pair per physical line, exactly one tab delimiter, no embedded tabs/newlines), matching Excel `DONG_HANG` sheet with exactly `Hán` and `Việt`, clean text for both languages, valid-pair counts and QA/source/tool report. Review `OMISSION`, `ADDITION` and `MISSING` before assigning labels or counting valid pairs. Historical guideline records 2,000 valid pairs/member for scanned/OCR vs 3,000 for text-extractable sources, a 30% error ceiling and 20% internal target; confirm applicability with the team. No evidence here of full coverage, validated quality metrics, final export automation, or confirmed v17 source.

## 7. Minimum files to reopen by task

| Task | Read next |
| --- | --- |
| Change Hán page/crop/OCR settings | Notebook source cells 3, 11, 15, 17, 24, 26 (zero-based), then one page's column images/reconstructed TXT. |
| Fix Vietnamese extraction or joining | `viet-ocr.py` functions in §2; compare the relevant `NNNN_page_text.txt` and `NNNN_sentences.csv`, including the adjacent page if needed. |
| Correct text or change cleaner contract | The corresponding corrected table and `clean_zh.py` or `clean_vi.py`; read the cleaned CSV header/sample, not historical workbooks. |
| Fix scoring, coverage, or layout | `align_v16_fixed.py`: `run()` for data flow, anchor/encoder/DP functions for scoring, `to_index_map()` + `write_template_xlsx()` for export. Read the template only for layout or review semantics. |
| Explain a v17 result | Open the matching `_v17_statistics.json` and `Alignment_Debug`; request the generator if reproduction or algorithm changes are needed. |
| Work on direct API alignment | `align_pure_api.py`: `DirectAPI` for transport/parsing/retries, `validate_alignments()` for the response contract, `run()` for input/export. |
| Verify repository status before edits | `git status --short --branch`, `git submodule status`; use `git show HEAD:<path>` for historical files. Preserve local work. |

**How this snapshot was checked:** static source/notebook review, Git inventory/status, `pdfinfo` on all four sources, CSV/JSON counts and schema comparisons, and read-only Excel ZIP/XML inspection. OCR, model inference, and alignment commands were not run as part of this handoff. For future code changes, do a bounded smoke run to a distinct output directory and verify the page filter, path coverage, workbook headers/data rows, and manually reviewed examples before expanding scope.
