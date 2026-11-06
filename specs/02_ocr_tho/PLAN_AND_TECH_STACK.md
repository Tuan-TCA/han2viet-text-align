# CV16 --- OCR Plan and Technology Stack

## 1. Project context

**Project:** CV16 --- Building a Chinese--Vietnamese Parallel Corpus on
Culture\
**Main source:** *Phủ Biên tạp lục* (撫邊雜錄), attributed to Lê Quý
Đôn.

The project constructs a historical Chinese--Vietnamese parallel corpus
through source inspection, text extraction/OCR, manual correction,
cleaning, segmentation, and alignment.

This is a corpus-construction project, not a machine-translation
project. The Vietnamese translation already exists and must be aligned
with the Chinese source.

## 2. Source inventory

  Part     Language     File                           Pages
  -------- ------------ ---------------------------- -------
  Cap_01   Chinese      `01_nguon/Cap_01/HAN.pdf`         53
  Cap_01   Vietnamese   `01_nguon/Cap_01/VIET.pdf`       251
  Cap_02   Chinese      `01_nguon/Cap_02/HAN.pdf`         92
  Cap_02   Vietnamese   `01_nguon/Cap_02/VIET.pdf`       105

All four PDFs were inspected using `pdfinfo`. None is encrypted.

**Scope constraint:** Do not assume matching part names or page numbers
imply exact Chinese--Vietnamese correspondence. The exact volume/content
scope of some source files remains to be verified.

## 3. Technology stack

  -----------------------------------------------------------------------
  Technology              Role                    Decision
  ----------------------- ----------------------- -----------------------
  Python                  Orchestration and       Use
                          reproducible scripts    

  Poppler `pdfinfo`       Read PDF metadata and   Use
                          page counts             

  Poppler `pdftotext`     Extract existing PDF    Use
                          text                    

  Poppler `pdftoppm`      Convert selected PDF    Use
                          pages to images         

  PaddleOCR               Chinese OCR benchmark   Benchmark / conditional
                          candidate; Vietnamese   
                          fallback only if        
                          extraction fails        

  Transkribus             Chinese OCR benchmark   Benchmark
                          candidate               

  VS Code                 Manual text correction  Use

  Markdown                Plan and implementation Use
                          feedback records        
  -----------------------------------------------------------------------

The working environment is Windows with PowerShell (`pwsh`). Scripts
must use Windows-compatible paths and subprocess calls. Poppler is
installed and its commands are available in `PATH`.

## 4. Data and directory conventions

Current project layout:

``` text
CV16/
├── 01_nguon/
│   ├── Cap_01/
│   │   ├── HAN.pdf
│   │   └── VIET.pdf
│   └── Cap_02/
│       ├── HAN.pdf
│       └── VIET.pdf
├── 02_ocr_tho/
│   ├── Cap_01/
│   │   ├── han/
│   │   │   ├── images/
│   │   │   ├── raw/
│   │   │   └── corrected/
│   │   └── viet/
│   │       ├── raw/
│   │       └── corrected/
│   └── Cap_02/
│       ├── han/
│       │   ├── images/
│       │   ├── raw/
│       │   └── corrected/
│       └── viet/
│           ├── raw/
│           └── corrected/
├── 03_text_sach/
├── 04_dong_hang/
├── specs/
├── src/
│   └── 02_ocr_tho/
├── pdf_inventory.txt
└── README.md
```

### File naming and traceability

-   Use original PDF page numbers, zero-padded to four digits:
    `0001.txt`, `0002.txt`, `0001.png`.
-   Keep one text file per source page.
-   Store raw extraction/OCR separately from corrected text.
-   Never overwrite raw output during correction.
-   Keep original PDFs unchanged.
-   Avoid ambiguous names such as `final`, `final2`, or `final_new`.
-   Use explicit versions such as `v01`, `v02`, or dates when versioning
    is needed.
-   Preserve page-level traceability throughout the pipeline.

## 5. OCR and extraction plan

### Phase 1 --- Source inspection

1.  Inspect the project and source-file locations.
2.  Run `pdfinfo` on all four PDFs.
3.  Record page counts and metadata.
4.  Check whether Vietnamese PDFs contain extractable text.
5.  Do not infer content correspondence from page counts.

**Status:** Completed.

### Phase 2 --- Vietnamese text extraction

Decision:

1.  Use `pdftotext -layout` first.
2.  Inspect extracted text for completeness, Vietnamese diacritics,
    encoding, reading order, and broken lines.
3.  Use PaddleOCR only if text extraction is inadequate.
4.  Save page-level UTF-8 `.txt` files in the relevant `raw/` directory.
5.  Keep corrected text separate in `corrected/`.

**Inspection result:** Both Vietnamese PDFs were reported by the user to
extract successfully with `pdftotext`.

**Implementation status:** The user reports Vietnamese extraction is
complete. Verify expected page-level outputs: - Cap_01: 251 text
files. - Cap_02: 105 text files.

Do not run Vietnamese OCR unless a specific extraction problem is
identified.

### Phase 3 --- Chinese image preparation

1.  Convert selected pages from each Chinese PDF to PNG.
2.  Use 300 DPI.
3.  Preserve the original page appearance.
4.  Do not automatically denoise, sharpen, increase contrast, deskew, or
    otherwise preprocess images.
5.  Save images under the corresponding `images/` directory.
6.  Preserve original page numbers in filenames.

Initial benchmark sample:

  Source PDF         Sample PDF pages
  ------------------ ------------------
  `Cap_01/HAN.pdf`   1, 27, 53
  `Cap_02/HAN.pdf`   1, 46, 92

These are initial representative samples, not a claim that they cover
every handwriting style or document condition.

### Phase 4 --- Chinese OCR benchmark

Run PaddleOCR and Transkribus on the same six sample images.

Requirements:

-   Keep each engine's raw output separate.
-   Do not overwrite or merge OCR outputs.
-   Record engine/model/configuration and software version where
    available.
-   Record processing time per page and total processing time.
-   Prepare manually verified reference transcriptions for CER
    calculation.
-   Record manual correction effort, preferably as time spent and/or
    number of corrections.
-   Present results for review.
-   Do not process all Chinese pages until the user explicitly approves
    the benchmark and full-processing scope.

### OCR evaluation criteria

Evaluate all three criteria:

1.  **Character Error Rate (CER):** compare OCR output against manually
    verified reference transcription.
2.  **Processing time:** record per-page and total time under comparable
    conditions.
3.  **Manual correction effort:** record time and/or correction burden
    required to produce usable text.

Do not choose an OCR engine based on CER alone.

## 6. Manual correction

-   The user performs manual correction in VS Code.
-   Raw OCR/extraction files remain immutable.
-   Corrected files are stored in the matching `corrected/` directory.
-   Keep page numbering identical between raw and corrected files.
-   Do not build a correction GUI unless the user changes this
    requirement.

## 7. Downstream corpus pipeline

These stages follow OCR and correction; they are not part of the current
OCR implementation task.

### Cleaning

-   Remove irrelevant headers, footers, and non-main-content pages.
-   Join page-break fragments where appropriate.
-   Remove duplicate OCR lines.
-   Remove unrelated footnotes and markers where appropriate.
-   Fix OCR garbage characters and spacing.
-   Normalize punctuation without changing meaning.
-   Preserve names, era names, numbers, and units.
-   Exclude tables and illustrations from the main sentence corpus.

### Segmentation

-   Do not split mechanically using punctuation alone.
-   Chinese punctuation anchors include `。！？；`, but historical
    Chinese may lack punctuation or contain editorial punctuation.
-   Vietnamese segmentation should consider `.?!;:` and semantic
    structure.
-   Watch for abbreviations, numbering, names, and translation
    structures in which one Vietnamese sentence may translate multiple
    Chinese sentences.

### Alignment

Support: - `1-1`: one Chinese segment to one Vietnamese segment. -
`1-N`: one Chinese segment to multiple Vietnamese segments. - `N-1`:
multiple Chinese segments to one Vietnamese segment. - `N-M`: multiple
segments on both sides.

Choose the smallest meaningful segment. Do not force one-to-one
alignment based only on punctuation.

The supplied alignment template is an internal annotation schema, not
the required final export schema.

## 8. Final deliverables required by the project guideline

-   TSV containing aligned Chinese--Vietnamese pairs.
-   Excel workbook with a `DONG_HANG` sheet and exactly two columns:
    `Hán`, `Việt`.
-   Clean Chinese text.
-   Clean Vietnamese text.
-   Pair counts and quality report.
-   Source and tool information.

TSV constraints: - One pair per physical line. - Exactly one tab
delimiter per row. - No embedded tabs or newlines within a segment. -
TSV and Excel contents must be identical.

The guideline specifies minimum valid aligned-pair targets of 2,000 per
member for scanned/OCR sources and 3,000 per member for text-extractable
sources. Confirm the applicable target with the project team; do not
claim completion without counting valid pairs.

Quality checks include `OMISSION`, `ADDITION`, and `MISSING`. The
guideline gives an error-rate ceiling of 30% and an internal target of
20%.

## 9. Implementation safeguards

-   Never modify source PDFs.
-   Never overwrite raw OCR or raw extracted text.
-   Do not silently skip failed pages.
-   Log failures and allow individual-page retries.
-   Make scripts idempotent where practical: existing outputs should not
    be overwritten without an explicit option.
-   Validate input files and output directories before processing.
-   Record commands, tool versions, OCR model/configuration, and
    timestamps.
-   Do not launch full Chinese OCR without explicit user approval.
-   Do not invent bibliographic facts or page correspondence.
-   Report what was actually implemented and tested; distinguish
    completed, partial, failed, and not tested.

## 10. Current status and next action

  -----------------------------------------------------------------------
  Item                                Status
  ----------------------------------- -----------------------------------
  Poppler installed and available     Complete

  PDF inventory with page counts      Complete

  Vietnamese text extraction test     Successful

  Vietnamese page-level extraction    Reported complete; verify output
                                      counts

  Chinese sample image preparation    Next

  PaddleOCR vs Transkribus benchmark  Not started

  Full Chinese OCR                    Waiting for benchmark approval

  Cleaning, segmentation, alignment   Later stages
  -----------------------------------------------------------------------

**Immediate next action:** prepare only the six specified Chinese
sample-page PNGs at 300 DPI. Then inspect the images before starting OCR
benchmarking.
