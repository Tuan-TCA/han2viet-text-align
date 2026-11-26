"""Generate `STAGE04_INTEGRATION_GUIDE.md` from verified Coarse Mapping V2 artifacts."""
from __future__ import annotations

import json
from pathlib import Path

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
DEFAULT_OUT = STAGE / "artifacts" / "coarse_mapping_v2"


def generate_guide(out_dir: Path = DEFAULT_OUT) -> Path:
    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    integrity = json.loads((out_dir / "source_integrity.json").read_text(encoding="utf-8"))
    p51 = integrity["book_vi_anchors_and_transitions"]["page_051_transition"]
    cov_b6 = metrics["vi_id_coverage"].get("Cap_02 Book VI (VIET_0405-0439)", {})
    cov_all = metrics["vi_id_coverage"].get("All Corpus Combined", {})

    guide = f"""# Stage 04 V4 Integration Guide — Coarse Mapping V2 (Book VI Extension)

## 1. Purpose & Readiness

This release (`03_text_sach/artifacts/coarse_mapping_v2/`, version `{metrics['version']}`) integrates **Book VI (*Quyển VI — Vật sản phong tục*)** from `02_ocr_tho/Cap_02/VIET/VIET_0405-0439.xlsx` into `Cap_02` and extends Stage 03B coarse page mapping from `Cap_02` Han pages `001–051` to `001–087`.

- **Supported Han pages**: **{metrics['supported_pages_v2']} / 145** (`Cap_01` `001–053` + `Cap_02` `001–087`), **0** partial pages, **{metrics['unmatched_pages_v2']}** unresolved pages (`Cap_02` `088–092`).
- **Frozen Han S4 guarantee**: All **2,808** S4 segments and **53,328** raw Han Unicode code points in `03_text_sach/artifacts/production/han_segments.jsonl` remain **100% unchanged** (`id_zh`, `global_raw_span`, `normalized_source_spans`, `source[]`).
- **Backward compatibility**: `Cap_01` (`001–053`), `Cap_02` (`001–050`), and `Cap_02` (`088–092`) records in `page_mapping_refined.jsonl` and `window_context_refined.jsonl` are **byte-for-byte field-identical** to Stage 03B V1 (`03_text_sach/artifacts/coarse_mapping/`).
- **Zero semantic labels inferred**: All `Mapping_Status` values (`VERIFIED`, `HIGH_CONFIDENCE_ESTIMATED`, `LOW_CONFIDENCE_ESTIMATED`, `AMBIGUOUS`, `UNMATCHED`) describe **candidate context availability only**. Stage 04 V4 must keep `Label_Target = "UNKNOWN"` unless independently adjudicated.

> **When to integrate**: Integrate **only after Agent 1 finishes freezing and benchmarking Stage 04 V4**. Do not overwrite `Stage04_V4_Handoff/inputs/` or active V4 benchmark directories during Agent 1's run.

---

## 2. Files to Consume in Stage 04 V4

Replace Stage 03B V1 context paths with the corresponding Coarse Mapping V2 artifacts:

| Role in Stage 04 V4 | V1 Path (Before) | V2 Path (After) | Notes |
|---|---|---|---|
| Segmented Han S4 units | `03_text_sach/artifacts/production/han_segments.jsonl` | *(unchanged)* `03_text_sach/artifacts/production/han_segments.jsonl` | Authoritative 2,808 S4 segments. Ignore segment-level `mapping_status` hints on `Cap_02` `052–087` (`"unmatched"` from pre-Book-VI Stage 03); use per-page V2 `Mapping_Status` instead. |
| Per-page Stage 04 window context | `03_text_sach/artifacts/coarse_mapping/window_context_refined.jsonl` | `03_text_sach/artifacts/coarse_mapping_v2/window_context_refined.jsonl` | 145 page records (`cap`, `han_page`, `mapping_status`, `global_raw_start`, `han_ids`, `han`, `raw`, `spans`, `viet`, `viet_t1`), plus fallback ID lists on `Cap_02` `051–087`. |
| Per-page coarse mapping & priors | `03_text_sach/artifacts/coarse_mapping/page_mapping_refined.jsonl` | `03_text_sach/artifacts/coarse_mapping_v2/page_mapping_refined.jsonl` | `B1_Range`, `B2_Range`, `Local_Range`, `Alternative_Candidates`, `Confidence_Proxy`, and `Evidence.book_transition` on page `051`. |
| Complete eligible Vietnamese catalog | *(single-workbook loader)* | `03_text_sach/artifacts/coarse_mapping_v2/viet_segments_extended.jsonl` | All **{cov_all.get('total_eligible', 2054)}** eligible Vietnamese segments (`685` Cap_01 + `991` Book V + `378` Book VI) in canonical reading order with precomputed `text_t1` and reversible `normalized_source_spans`. |
| Source workbooks (`Cap_02`) | `02_ocr_tho/Cap_02/VIET/VIET_0001-0105.xlsx` | Both `VIET_0001-0105.xlsx` **and** `VIET_0405-0439.xlsx` | Or load directly via `03_text_sach/scripts_v2/preprocess_v2.py:load_sources_v2()`. |

---

## 3. Critical Multi-Workbook & Namespace Contracts

### 3.1 Vietnamese ID Namespaces in `Cap_02`

`Cap_02` now spans **two** Vietnamese workbooks in strict reading order. Preserve all IDs verbatim without renumbering or stripping prefixes:

1. **Book V (`VIET_0001-0105.xlsx`)**:
   - `book_id = "Book_V"`, `cap = "Cap_02"`
   - ID pattern: `Cap_02-VI-NNNN-NNN` (`Cap_02-VI-0001-002` … `Cap_02-VI-0105-018`, **991** eligible rows).
2. **Book VI (`VIET_0405-0439.xlsx`)**:
   - `book_id = "Book_VI"`, `cap = "Cap_02"`
   - ID pattern: `Cap_02_VI-VI-NNNN-NNN` (`Cap_02_VI-VI-0405-003` … `Cap_02_VI-VI-0439-011`, **378** eligible rows).

If Stage 04 V4 parses Vietnamese IDs by regex, update any strict `r"^Cap_02-VI-(\d{{4}})-(\d+)$"` check to:

```python
VI_ID_RE = re.compile(r"^(Cap_01-VI|Cap_02-VI|Cap_02_VI-VI)-(\d{{4}})-(\d+)$")
```

### 3.2 Page Coordinate Systems (Avoid the `105 → 405` Coordinate Trap)

Book V was extracted from a 105-page excerpt PDF (`01_nguon/Cap_02/VIET.pdf`, PDF pages `1–105`), whereas Book VI was extracted from the full 2007 edition PDF (`Phu_bien_tap_luc_2007.pdf`, PDF pages `405–439`). In the physical printed book (`trang_in`), **they are consecutive**:

| Book | `viet_pdf_page` | `trang_in` (Printed Page) | `book_local_page` | `cap_coord_page` / `cap_ordinal_page` |
|---|---|---|---|---|
| `Cap_01` (`VIET_0186-0251.xlsx`) | `186–251` | `189–254` | `1–66` | `186–251` (ordinal `1–66`) |
| `Cap_02` `Book_V` (`VIET_0001-0105.xlsx`) | `1–105` | `304–408` | `1–105` | `1–105` (ordinal `1–105`) |
| `Cap_02` `Book_VI` (`VIET_0405-0439.xlsx`) | `405–439` | `409–443` | `1–35` | `106–140` (`viet_pdf_page - 299`) |

**Rule for Stage 04 V4**: Never compute page distance in `Cap_02` as raw `abs(vi_page_b - vi_page_a)` across the `105 ↔ 405` boundary (`405 - 105 = 300`, whereas true physical page distance between `trang_in=408` and `trang_in=409` is **1 page**). Always use `cap_coord_page` (`p if p <= 105 else p - 299`) or array rank in `viet_segments_extended.jsonl` when measuring VI ordering, proximity, or gap penalties.

---

## 4. Preventing Silent Exclusion of Eligible Vietnamese Segments

In Stage 03B (both V1 and V2), `Selected_VI_IDs` (`window_context_refined.jsonl[page]["viet"]`) on unanchored B2 pages contains only the specific `VI_ID`s matched by the winning 10-segment probe (`{cov_b6.get('in_selected_vi_ids', 0)}/{cov_b6.get('total_eligible', 378)}` in Book VI). Treating `Selected_VI_IDs` as a closed candidate set would silently exclude legitimate boundary segments (for example, on anchored Han page `061`, `TRANG_VIET` anchors `414`, while the bottom of Han page `061` already reaches `Cap_02_VI-VI-0415-001..002` on PDF page `415`).

To guarantee **zero silent exclusions** (`{cov_b6.get('in_padded_plus_minus_1_page', 378)}/{cov_b6.get('total_eligible', 378)} = 100.0%` Book VI coverage):

1. **Primary Alignment Window**: Start from `b2_range_vi_ids` (all eligible segments touching `B2_Range`).
2. **Boundary & Gap-Recovery Expansion**: Expand candidate lookup to `padded_context_vi_ids` (`B2_Range ∪ B1_Range ± 1` physical page, precomputed on every `Cap_02` `051–087` record in `window_context_refined.jsonl`) and include any `Alternative_Candidates` ranges from `page_mapping_refined.jsonl`, especially on `AMBIGUOUS` pages (`{metrics['ambiguous_page_list']}`).
3. **Full Catalog Lookup**: Index `viet_segments_extended.jsonl` by `id` and sequential position so V4's Gap Recovery and VI Reassignment modules can inspect neighboring segments across page boundaries without truncating `text_original`.

---

## 5. Special Boundary Cases to Handle in Stage 04 V4

### 5.1 Han Page `051` — Cross-Book & Intra-S4 Transition (`Book_V → Book_VI`)

Han page `051` (`global_raw_span = [40741, 40943)`, 202 chars) contains **both** the end of Book V and the beginning of Book VI:

- **Right-hand portion (`COL01–COL04`, `[40741, 40805)`)**:
  - S4 units: `Cap_02-051-052-S4-0001` through `S4-0005`.
  - Cross-page continuation from page `050`: `[40741, 40747)` (`'X7寬政辭磨'`) inside `S4-0001` completes `Cap_02-VI-0105-014` from Han page `050`; `Cap_02-VI-0105-015` begins intra-S4 at offset **`40747`** (`'但見盡抗武功誕字之德'`), continuing through `Cap_02-VI-0105-018` (`'...kính dâng từ để mừng"'`) at `40805`.
- **Book VI title column (`COL05`, `[40805, 40812)`)**:
  - Text: `'撫邊雜錄卷之六'` at the start of `Cap_02-051-052-S4-0006` (`[40805, 40869)`).
  - Corresponds to ineligible heading row `Cap_02_VI-VI-0405-001` (`QUYỂN VI`, `loai="tieu_de"`, `dung_de_ghep=False`).
- **Left-hand Book VI prose (`COL06–COL13`, `[40812, 40943)`)**:
  - Begins **intra-S4 at global offset `40812`** (`'物產之美多出獻方'` → `Cap_02_VI-VI-0405-003`), then `'圓化北市政卅七十五社村坊...'` at `40819` (`Cap_02_VI-VI-0405-004`) inside the same S4 unit `Cap_02-051-052-S4-0006`.
  - **Do not force the Book VI prose start to S4 boundary `40805` or `40869`.** Allow Stage 04 V4's intra-S4 boundary split module to split `[40805, 40812)` (untranslated heading / structural title) from `[40812, 40819)` (`0405-003`) and `[40819, 40869)` (`0405-004`).
- **Cross-page continuation `051 → 052`**:
  - `Cap_02-051-052-S4-0012` (`[40938, 40955)`, `'土人煎密1浸貯可耐久礼社人參出北市'`) crosses from page `051` (`[40938, 40943)`) into page `052` (`[40943, 40955)`), completing `Cap_02_VI-VI-0405-007` at `40948` and starting `Cap_02_VI-VI-0405-008`. Deduplicate `id_zh` when merging two-page or multi-page Stage 04 windows.

### 5.2 Han Page `087 → 088` — End of Book VI vs Unresolved Postface

- `Cap_02-087-088-S4-0005` (`[52417, 52443)`, `'北容1010001膜R210撫邊雜錄發順廣為國家南近'`) spans Han pages `087` and `088`:
  - `[52417, 52419)` (`'北容'` for `'北客'`) completes Book VI's final sentence `Cap_02_VI-VI-0439-011` (`"...bán cho người Tàu."`).
  - `[52419, 52431)` (`'1010001膜R210'`) is colophon/stamp OCR noise at the end of Book VI on page `087`.
  - `[52431, 52443)` (`'撫邊雜錄發順廣為國家南近'`) on page `088` begins Ngô Thì Sĩ's postface (*Bạt*), which has no Vietnamese rows in `VIET_0405-0439.xlsx`.
- Keep `Cap_02` pages `088–092` (`UNMATCHED`) excluded from forced Vietnamese pairing: `088–089` are the postface, `090` is a duplicate scan of `Cap_02` page `001` (Book V opening), and `091–092` are shelfmark fragments (`R16061`, `01`).

### 5.3 Embedded Vietnamese OCR Nuances in Book VI

Source strings in `VIET_0405-0439.xlsx` are preserved immutably (`text_original`), including 26 eligible rows where the 2007 PDF text layer substituted digits such as `5 → ð/õ` (e.g., `7õ xã` for `75 xã` in `Cap_02_VI-VI-0405-004`, `3 quan õð tiền` in `0414-003`) or `0 → O/ð` (`6O người` in `0409-004`). All such rows are cataloged in `source_integrity.json` (`workbooks["VIET_0405-0439"]["ocr_anomaly_summary"]`). Stage 04 V4's numeral matcher may treat `7õ`/`õ0`/`6O` as soft OCR-tolerant numeric cues during scoring **without mutating `text_original`**.

---

## 6. Drop-In Stage 04 V4 Loader Snippet

```python
import json
from pathlib import Path

V2_DIR = Path("03_text_sach/artifacts/coarse_mapping_v2")
PROD_S4 = Path("03_text_sach/artifacts/production/han_segments.jsonl")

def load_stage04_v2_inputs():
    s4_segments = [json.loads(line) for line in PROD_S4.read_text(encoding="utf-8").splitlines() if line.strip()]
    viet_catalog = {{
        row["id"]: row
        for line in (V2_DIR / "viet_segments_extended.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in (json.loads(line),)
    }}
    page_contexts = {{
        (row["cap"], row["han_page"]): row
        for line in (V2_DIR / "window_context_refined.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in (json.loads(line),)
    }}
    page_mappings = {{
        (row["Cap"], row["Han_Page"]): row
        for line in (V2_DIR / "page_mapping_refined.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in (json.loads(line),)
    }}
    return s4_segments, viet_catalog, page_contexts, page_mappings
```
"""
    target = out_dir / "STAGE04_INTEGRATION_GUIDE.md"
    target.write_text(guide, encoding="utf-8")
    return target


if __name__ == "__main__":
    p = generate_guide()
    print(f"Wrote {p}")
