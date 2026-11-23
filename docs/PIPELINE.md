# CV16 — Hán–Việt corpus pipeline and Kaggle OCR

CV16 builds a sentence-aligned corpus from the Hán text of *Phủ Biên tạp lục* (撫邊雜錄) and an existing Vietnamese translation. See [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) for the repository inventory, existing scripts, historical experiments, and workbook schemas.

## Stage layout

Use `Cap_XX` for the volume and `HAN` or `VIET` for the source. A page ID such as `0001` is the **one-based PDF position**, not the printed page number. Matching IDs across languages do not establish passage correspondence. The paths below describe the layout for new work; the legacy consumers still use their existing paths.

| Stage | Path and file contract |
| --- | --- |
| 01 · Sources | `01_nguon/Cap_XX/{HAN,VIET}.pdf`; inventory in `01_nguon/Kiem_ke_nguon.xlsx`. Keep the originals as the source of truth. |
| 02 · Raw Hán OCR | Within a run, `02_ocr_tho/Cap_XX/HAN/images/NNNN/` contains the page image and numbered strips. `raw/NNNN/<engine>/` contains per-strip JSON and reconstructed `NNNN.txt`; `raw/NNNN/ensemble/` contains the vote and decision details. |
| 02 · Raw Vietnamese extraction | For new extractions, pass `--out <run>/02_ocr_tho/Cap_XX/VIET/raw/pdfplumber` to the existing [`viet-ocr.py`](../02_ocr_tho/Cap_01/VIET/viet-ocr.py). Keep its `NNNN/` outputs and `all_sentences.csv` together. The checked-in sample is under `Cap_01/VIET/VIET_pdfplumber/` and covers PDF pages 170–190. |
| 03 · Review and clean | `03_text_sach/Cap_XX/HAN/NNNN-corrected.{xlsx,csv}` → `NNNN-cleaned.csv` (`id_zh,text_zh`). Vietnamese review uses a range-named CSV (e.g. `170-190.csv`) → `03_text_sach/Cap_XX/VIET/vi_cleaned.csv` (`id_vi,page_start,page_end,text_vi`). The current cleaner scripts use fixed sample inputs; expanding their processing is separate from expanding OCR. |
| 04 · Align and annotate | Read the cleaned files and choose a Vietnamese passage window verified against the Hán source. For new review workbooks use a run-specific output directory, e.g. `04_dong_hang/runs/<run_id>/KetQua_CapXX_TrangN.xlsx`, which retains the existing aligner filename. Keep the source page/window in the review metadata. |
| Reviewed delivery | Proposed layout: `deliveries/<release_id>/parallel.tsv`, `parallel.xlsx`, clean language text, and `qa.md`. The TSV has one pair per physical line and one tab delimiter; the Excel `DONG_HANG` sheet has columns `Hán` and `Việt` and matches the TSV. Count reviewed valid pairs and document source and QA results. |

The Hán PDFs have **53** (`Cap_01`) and **92** (`Cap_02`) pages; the Vietnamese PDFs have **251** and **105** respectively. Stage 02 produces OCR candidates, not the segmented and corrected tables expected by Stage 03. A vertical strip ID is a reading-order index, not a sentence ID. In the existing `Cap_01` sample there are 18 OCR strips and 16 corrected rows on each of the first two pages.

## Vietnamese OCR batch to Excel

From the repository root, with Poppler's `pdftotext` on `PATH` and Python `openpyxl` available:

```powershell
python -B 02_ocr_tho/viet_ocr_batch.py --cap all
```

The same command reads both PDFs' embedded OCR, segments the selected text, checks configured passage anchors, and regenerates the raw `VIET/raw/pdftotext/NNNN_page_text.txt` and workbook outputs for each pair. Use `--cap Cap_01` or `--cap Cap_02` for one pair.

| Workbook (under `02_ocr_tho/`) | Vietnamese PDF pages | Hán scope |
| --- | --- | --- |
| `Cap_01/VIET/VIET_0186-0251.xlsx` | 186–251 | 1–53; the overlap starts within Vietnamese PDF p. 186. |
| `Cap_02/VIET/VIET_0001-0105.xlsx` | 1–105 | 1–50 and right half of 51 (Quyển V). |

Filter `CAU_VIET` on `dung_de_ghep = TRUE` for prose and verse translations. Each cross-page sentence has one ID and two page endpoints. Labels and sentence boundaries are extraction heuristics; review OCR against the PDF before using it as a reference. `TRANG_VIET` separates confirmed passage anchors from candidates and from broader search windows bounded by the neighboring anchors. A verified anchor establishes an overlap, not a full page or sentence alignment. The script checks each cue in `02_ocr_tho/viet_han_anchors.json` against the source. If page-numbered Hán cleaned CSVs are available in Stage 03, uniquely shared number pairs can additionally suggest a candidate. The search window for Cap_02 never includes the left half of Hán p. 51.

## Kaggle: upload, attach data, run

1. Import [han_ocr_voting_kaggle.ipynb](../02_ocr_tho/han_ocr_voting_kaggle.ipynb) as a Kaggle notebook. In **Session options**, turn **Internet** on. A GPU is optional: EasyOCR uses one if available; PaddleOCR and Tesseract run on CPU.
2. Attach a Kaggle dataset containing the following **directories/files**, not only an unopened ZIP. Datasets can be separate. Under the dataset mount, the notebook discovers unique matching source directories automatically. The default pilot requires both Hán PDFs.

   ```text
   01_nguon/
     Cap_01/HAN.pdf
     Cap_02/HAN.pdf
   02_ocr_tho/                      # optional: reuse pre-cut strips
     Cap_01/HAN/images/0001/0001-01.png
     Cap_01/HAN/images/0001/0001-02.png
     ...
   ```

   Preserve the original strip numbers. The notebook reads numbered PNGs in numeric order: rightmost strip first, upright characters top to bottom. A whole-page `0001.png` does not count as a strip. If a page has no matching numbered PNGs, the notebook renders it and runs the original notebook's crop algorithm (144 DPI, top 92%, grayscale/denoising/CLAHE, vertical projection and right-to-left ordering). It doesn't fill in gaps in a partially supplied strip set; review the warning against the original page. If your Kaggle data uses different directory names, set `PDF_ROOT` to the folder holding `Cap_XX/HAN.pdf` and `CROP_ROOT` to the folder holding `Cap_XX/HAN/images/` using absolute `/kaggle/input/...` paths.
3. Select **Run All**. The setup cell installs PaddleOCR, EasyOCR, and Tesseract's vertical Traditional Chinese language pack as needed. PaddleOCR and EasyOCR fetch public model weights on first use. Read the engine status lines and check that all three engines are `ready` before treating the result as a three-engine comparison.
4. The default pilot selects `Cap_01` pages **1, 27, 53** and `Cap_02` pages **1, 46, 92**. Set `PAGES = {'Cap_01': '1-2'}` to smoke-test the existing sample, or `PAGES = {'Cap_01': '1-12,27', 'Cap_02': [1, 46]}` for a custom set. Ranges are inclusive and out-of-bounds pages are rejected. Use `'all'` for a volume after inspecting the pilot.
5. Download `cv16_han_ocr_<run_id>.zip` from Kaggle **Output** after the final cell finishes. To retain the results after the session, download the archive or save a version with its outputs.

## Read the results

```text
cv16_han_ocr_<run_id>/
  manifest.json               # source paths, selected pages, settings, engine setup and versions
  pages.csv                   # per-page strip counts, nonempty outputs, failures and timings
  review.csv                  # disputed or missing text, strip warnings, page errors
  cer.csv                     # empty of data rows until verified references are supplied
  02_ocr_tho/Cap_XX/HAN/
    images/NNNN/NNNN.png
    images/NNNN/NNNN-CC.png
    raw/NNNN/
      paddle/NNNN-CC.json
      easyocr/NNNN-CC.json
      tesseract/NNNN-CC.json
      ensemble/review.json    # per-strip vote, anchors, alternative readings and decisions
      <variant>/NNNN.txt      # one reconstructed page per engine and for ensemble
```

PaddleOCR uses `chinese_cht` with PP-OCRv5, EasyOCR uses `ch_tra` with English support, and Tesseract uses `chi_tra_vert` in single vertical-block mode. Empty or failed strips abstain. Voting starts from the reading with the smallest total edit distance to the others, aligns each alternative to it, and uses strict majorities at its character positions. Gaps can vote for deletions; insertions are compared as blocks. When there is no majority, keep the anchor reading and flag the decision. Confidence scores from different engines are not compared. In `pages.csv`, nonempty strip counts measure output coverage, not correctness; the `ensemble` timing is vote computation only, so include all engine timings when estimating the cost of running the ensemble.

Inspect `review.csv` alongside the strips. Agreement can still be wrong, especially for historical variants, omitted regions, or incorrect crop order. There are currently no verified references for the new pilot. When you have them, set `REFERENCE_ROOT` to a directory containing UTF-8 `Cap_XX/HAN/NNNN.txt` files transcribed from the **same regions**, in the same order. CER is edit distance divided by reference length. The notebook removes whitespace and uses NFC normalization for both sides while preserving punctuation and character variants. It compares aggregate CER on the same labelled pages that every variant could score. A lower CER on a small pilot is evidence for that sample; check coverage and review effort before scaling up.
