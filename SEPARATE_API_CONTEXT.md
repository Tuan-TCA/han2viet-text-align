# Ngữ cảnh kiểm nghiệm Kim Hán Nôm Separate API

Khảo sát local, chỉ đọc dữ liệu, workspace và lịch sử Git (`HEAD` tại thời điểm khảo sát: `5cb7273`). Không gọi API, không chạy pipeline, không cài thư viện. `UNKNOWN` nghĩa là chưa xác minh từ nguồn local; trong bản chép Excel, `UNKNOWN` cũng biểu diễn ô trống, không phải nhãn 0.

## 1. Project structure

Thư mục gốc và working directory của các lệnh tài liệu: `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16`. Các đường dẫn tương đối dưới đây tính từ gốc này. Cây rút gọn nhóm các file lặp theo trang và bỏ Git, môi trường ảo, cache, thư mục ảnh lớn; không liệt kê sâu submodule OmniAlign.

```text
CV16/
├── 01_nguon/
│   ├── Cap_01/{HAN.pdf, VIET.pdf}
│   ├── Cap_02/{HAN.pdf, VIET.pdf, Phu_bien_tap_luc_2007.pdf}
│   └── Kiem_ke_nguon.xlsx
├── 02_ocr_tho/
│   ├── Cap_01/
│   │   ├── Cap_01_HAN_all_pages.txt
│   │   ├── HAN/{pages/, raw/}
│   │   └── VIET/{VIET_0186-0251.xlsx, viet-ocr.py, VIET_pdfplumber/}
│   ├── Cap_02/
│   │   ├── Cap_02_HAN_all_pages.txt
│   │   ├── HAN/{pages/, raw/}
│   │   └── VIET/VIET_0001-0105.xlsx
│   ├── Han_OCR/{HAN_OCR_batch.xlsx, run_report.csv, HAN_OCR_full_sample_raw_old_style (1).ipynb}
│   ├── New folder/Han_OCR/ [cùng tên file như Han_OCR bên trên]
│   └── Viet_OCR/{viet_ocr_batch.py, viet_han_anchors.json}
├── 03_text_sach/Cap_01/HAN/
│   ├── segmented/{0001–0010-sentences.csv, run_summary.json}
│   └── reviewed/{0001–0010-reviewed.csv}
├── 04_dong_hang/temp/
│   ├── batch_han_sentence_split.py
│   ├── batch_sentence_alignment.py
│   ├── align_sinonom_api.py
│   ├── cpu_alignment_benchmark.py
│   ├── CPU_BENCHMARK.md
│   ├── Cap01_0001-0010_alignment_reviewed.xlsx
│   ├── cpu_benchmark_runs/cap01_pilot/
│   └── ground_truth_draft_eval/{evaluate.py, predictions.csv, pair_review.csv, summary.json}
├── docs/{03_04_GUIDE.md, ALIGNMENT_API_DIAGNOSTICS.md, PHASE1_AUDIT.md, PIPELINE.md}
├── OmniAlign/
├── pipeline/
│   ├── scripts/normalize_phase1.py
│   └── artifacts/phase1/{han_pages.jsonl, viet_segments.jsonl, page_mapping.jsonl, silver_benchmark.jsonl, audit.json}
├── Cap01_Silver_Benchmark_Merged.xlsx
├── PROJECT_CONTEXT.md
├── README.md
└── SEPARATE_API_CONTEXT.md
```

`batch_han_sentence_split.py` là client Separate đang có trong workspace. `batch_sentence_alignment.py` và `align_sinonom_api.py` dùng endpoint khác (`sentence-alignment`); `cpu_alignment_benchmark.py` và `ground_truth_draft_eval/evaluate.py` phục vụ dóng hàng/đánh giá. Hai notebook có tên nêu trên là OCR Hán; notebook gọi Separate trong workspace: `UNKNOWN`. `pipeline/scripts/normalize_phase1.py` chuẩn hóa dữ liệu và ghi offset, không tách câu bằng API. Script thí nghiệm chỉ còn trong Git được ghi ở mục 3–4.

## 2. Input data

### 2.1 Hán OCR cả hai Cap

| File tuyệt đối | Định dạng |
|---|---|
| `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\02_ocr_tho\Cap_01\Cap_01_HAN_all_pages.txt` | TXT, đọc bằng UTF-8-SIG, 53 trang; marker `=== Cap_01 \| PAGE NNN ===` |
| `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\02_ocr_tho\Cap_02\Cap_02_HAN_all_pages.txt` | TXT, đọc bằng UTF-8-SIG, 92 trang; marker `=== Cap_02 \| PAGE NNN ===` |

Mẫu thật (dòng nội dung được cắt ở bên phải để minh họa):

```text
=== Cap_01 | PAGE 001 ===
爭納歲願惡示至今有一社至十六七將臣二十餘社長百得應務者正許知押為額目耳各賦有給夫干人免民丁雜役使取其齋鄉為寓祿

=== Cap_02 | PAGE 001 ===
撫邊雜錄卷之五RiG6823人才何代無之順化在同胡辰有鄧悉父子以將無顯若其在十國闕順天洪德间則阮子雍
```

Batch Separate dùng JSON theo trang, không dùng trực tiếp hai TXT. Ví dụ input `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\02_ocr_tho\Cap_01\HAN\pages\Cap01-001.json`; đây là một phần bản ghi thật (`info` còn nhiều trường, `rows` còn các segment sau):

```json
{"info":{"cap":"Cap_01","page":1,"detected":18,"kept":16},"rows":[{"id":"Cap01-001-001","han":"爭納歲願惡示至今有一社至十六七將臣二十餘社長百得應務者正許","confidence":0.8057503700256348,"cap":"Cap_01","page":1,"segment":1,"column":"Cap01-001-COL02"}]}
```

### 2.2 Việt đã xử lý

- Cap_01: `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\02_ocr_tho\Cap_01\VIET\VIET_0186-0251.xlsx` — XLSX; 786 dòng mục Việt, 66 dòng trang, không tính tiêu đề.
- Cap_02: `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\02_ocr_tho\Cap_02\VIET\VIET_0001-0105.xlsx` — XLSX; 1.394 dòng mục Việt, 105 dòng trang, không tính tiêu đề.

Cả hai dùng cùng schema. Các dòng mẫu bên dưới theo thứ tự cột (dòng đầu Cap_01, dòng sau Cap_02; `null` là ô trống):

`CAU_VIET`: `id_vi, viet_page_start, viet_page_end, loai, text_vi, dung_de_ghep, co_ra_soat`.

```json
[
  ["Cap_01-VI-0186-001", 186, 186, "van_xuoi", "nộp tiển lĩnh bằng, đến nay có chỗ một xã có đến 16 hay 17 tướng thần, hơn 20 xã trưởng, đều được làm việc, chỉ cho viên tri áp làm đầu mục thôi.", true, "đầu đoạn cắt giữa câu"],
  ["Cap_02-VI-0001-001", 1, 1, "tieu_de", "QUYỀN V", false, null]
]
```

`TRANG_VIET`: `viet_pdf_page, trang_in, so_muc_ghep_cham_trang, han_trang_co_moc, han_trang_ung_vien, han_cua_so_tu, han_cua_so_den, trang_thai_moc, can_cu`.

```json
[
  [186, 189, 3, "1", null, 1, 2, "đã xác minh mốc", "Hán 1: nộp tiền lĩnh bằng, đến nay — Mở đầu bản Hán giữa đoạn về lệ lĩnh bằng; câu Việt bị cắt ở đầu."],
  [1, 304, 6, "1", null, 1, 2, "đã xác minh mốc", "Hán 1: hân tài đời nào là không có — 人才何代無之 — mở đầu Quyển V."]
]
```

Dùng `dung_de_ghep = TRUE` để lấy mục được bật. Theo `docs/PHASE1_AUDIT.md`, cửa sổ Việt hiện có của Cap_02 chỉ phủ trang Hán 001–051; 052–092 không có cửa sổ, không suy ra `MISSING` từ khoảng trống này.

### 2.3 Template và tài liệu API

- **Template XLSX:** `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\04_dong_hang\Sino_Vietnamese_Sentence_Alignment_Template.xlsx` là đường dẫn lịch sử, file đã bị xóa trong working tree. Nguồn đã đọc: `HEAD:04_dong_hang/Sino_Vietnamese_Sentence_Alignment_Template.xlsx`. Một sheet `Alignment_Dataset`, 11 cột; dưới đây là header và một dòng ví dụ có thật trong template.

```csv
Pair_ID,Chinese,Vietnamese,OMISSION,ADDITION,MISSING,Alignment_Type,Punct_Anchor_Match,Label_Target,OCR_Conf_Min,Note
C001_V001,床前明月光，疑是地上霜。,"Đầu giường ánh trăng sáng, ngỡ là sương trên mặt đất.",0,0,0,1-1,1,1,0.98,Cặp câu chuẩn 1-1
```

- **Hướng dẫn nội bộ Markdown:** `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\docs\03_04_GUIDE.md`. Trích nguyên văn: “`batch_han_sentence_split.py` | Nối OCR đúng thứ tự rồi gọi `separate-sentences`; ghi kết quả vào `segmented/`.” Phần chạy lại có lệnh lịch sử và tên biến môi trường. `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\docs\ALIGNMENT_API_DIAGNOSTICS.md` mô tả thực nghiệm của endpoint dóng hàng, không phải Separate. Tài liệu chính thức của nhà cung cấp, quy trình cấp token và thông số quota/rate limit của Separate: `UNKNOWN`.

### 2.4 Benchmark XLSX

`C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\Cap01_Silver_Benchmark_Merged.xlsx`. Header từng sheet (không tính header: lần lượt 12, 12, 12, 13, 1 và 13 dòng):

```text
Alignment_Dataset: Pair_ID, Chinese, Vietnamese, OMISSION, ADDITION, MISSING, Alignment_Type, Punct_Anchor_Match, Label_Target, OCR_Conf_Min, Note, VI_ID, Han_Start_0, Han_End_exclusive, Han_Page, Silver_Status, Boundary_Agreement, ChatGPT_Confidence, DeepSeek_Confidence, DeepSeek_Label, Adjudication, Han_Corrected_Provisional
Comparison: Pair_ID, VI_ID, ChatGPT_Han, DeepSeek_Han, CG_Start, CG_End, DS_Start, DS_End, Boundary_Agreement, CG_Evidence, DS_Evidence, DS_Correction, Adjudication
ChatGPT_Source: Pair_ID, Chinese, Vietnamese, OMISSION, ADDITION, MISSING, Alignment_Type, Punct_Anchor_Match, Label_Target, OCR_Conf_Min, Note, VI_ID, Han_Start_0, Han_End_exclusive, Han_Page, Review_Status, Review_Confidence, Evidence_Review, Han_Corrected_Provisional, Review_Decision
DeepSeek_Source: ID, Han_Page, Han_OCR, Correction, VI_ID, Vietnamese, OMISSION, ADDITION, MISSING, Label_Target, Confidence, Evidence
Unaligned: Han_Page, Start_0, End_exclusive, Han_OCR, Status, Note
README: Mục, Giá trị / giải thích
```

Mẫu ô thật từ các sheet phụ: `Comparison`: `PILOT-005`, `CG_Start=267`, `CG_End=324`, `DS_Start=267`, `DS_End=326`, `Boundary_Agreement=DIFFERENT`; `ChatGPT_Source`: `PILOT-001`, `Review_Status=REVIEWED_SINGLE_MODEL`, `Review_Confidence=MEDIUM`; `DeepSeek_Source`: `H001`, `VI_ID=186-001`, `Label_Target=1`, `Confidence=HIGH`; `Unaligned`: `002,893,905,雜川人阮金珠同春人陳文見,OUT_OF_SCOPE`; `README`: `Phạm vi` → `Cap_01 Hán 001–002; Việt 186–188`.

Offset là Unicode code point trên chuỗi **nối thân hai trang sau `strip()`**, giữ khoảng trắng nội trang, không thêm dấu phân cách. Dùng `s[Han_Start_0:Han_End_exclusive]`; tổng 905 ký tự. `Alignment_Dataset` dùng biên ChatGPT, không phải gold. Theo `Comparison`, biên DeepSeek giống ở 8 cặp; 4 cặp khác: `PILOT-005 [267,326)`, `PILOT-006 [326,337)`, `PILOT-008 [372,558)`, `PILOT-009 [558,647)`. `[893,905)` nằm ngoài phạm vi. `Label_Target=1` chỉ là nhãn dương tạm của ba cặp; 9 ô chưa xác minh. `DeepSeek_Label` là ý kiến nguồn, không thay thế `Label_Target`; `OCR_Conf_Min` trống cả 12 dòng. Không dùng tập này để ước lượng độ chính xác tổng thể.

**Đủ 12 cặp từ `Alignment_Dataset`** (dấu `|` phân cột, giữ nguyên OCR và văn bản Việt):

```text
Pair_ID|Chinese|Vietnamese|VI_ID|Han_Page|Han_Start_0|Han_End_exclusive|Alignment_Type|Label_Target|OCR_Conf_Min|ChatGPT_Confidence|DeepSeek_Confidence|DeepSeek_Label|Silver_Status|Boundary_Agreement
PILOT-001|爭納歲願惡示至今有一社至十六七將臣二十餘社長百得應務者正許知押為額目耳|nộp tiển lĩnh bằng, đến nay có chỗ một xã có đến 16 hay 17 tướng thần, hơn 20 xã trưởng, đều được làm việc, chỉ cho viên tri áp làm đầu mục thôi.|Cap_01-VI-0186-001|001|0|35|1-1 (ứng viên)|UNKNOWN|UNKNOWN|MEDIUM|HIGH|1|UNRESOLVED|SAME
PILOT-002|各賦有給夫干人免民丁雜役使取其齋鄉為寓祿|Các chức được cấp phu bao nhiêu người được miễn dân đinh tạp dịch, cho lấy tiền thuế thân của phu Ấy làm ngụ lộc.|Cap_01-VI-0186-002|001|35|55|1-1 (ứng viên)|1|UNKNOWN|HIGH|MEDIUM|1|SILVER_PROVISIONAL|SAME
PILOT-003|又同納候夫禮歲禮米雇借附船獻祕富春卯已丑年升葬府亥府庚一長五改米十五秩黃陽到導各年貞七門辛十五深記府一貫記陽祀座該總法憂各八內朱十二秩後官正司官路一貫三門司官一長二門米十五鉢首合後合各九約朱十三餘將臣七陌米十餘社長七限米八 中等记函七兩米十年下等祀丞六四米八詩各斬共二百七十八人成共二百十三貞七門米共二千七百二十七年|Lại phải nộp tiền lễ, gạo lễ về phu hầu để thuê mướn người đi theo thuyền thuế chở đến Phú Xuân, như năm Kỷ Sửu, tri phủ phủ Thăng Hoa nộp tiền 1 quan 5 tiền, gạo 15 bát, tri huyện huấn đạo mỗi người 1 quan 1 tiền, gạo 1õ bát, cai phủ 1 quan 7 tiền, gạo 15 bát, ký phủ 1 quan, gạo 15 bát, ký huyện, ký thuộc cai tổng, cai man, mỗi người 8 tiền, gạo mỗi người 12 bát, cai quan, chính ty trưởng, mỗi người 1 quan 3 tiền, gạo 15 bát, ty quan 1 quan 2 tiền, gạo 1ð bát, thủ hợp, cai thuộc, mỗi người 9 tiền, gạo 13 bát, thủ lăng đội trưởng, từ đường thứ đội trưởng, mỗi người 1 quan, gạo 15 bát, thủ lăng thứ đội trưởng 6 tiền, gạo 10 bát, tướng thần 7 tiền, gạo 8 bát, thượng đẳng từ thừa 8 tiền, gạo 12 bát, trung đẳng từ thừa 7 tiển, gạo 10 bát, hạ đăng từ thừa 6 tiền, gạo 8 bát, các chức cộng 278 người, nộp tiển 213 quan 7 tiển, gạo cộng 2.727 bát.|Cap_01-VI-0186-003|001|55|213|1-1 (ứng viên)|UNKNOWN|UNKNOWN|LOW|MEDIUM|1|UNRESOLVED|SAME
PILOT-004|其餘作富祿及别初别載又社坊又捉見丁數富祿礼侯每人十二文每百人呈面米五升美味大往一陷中社三十文稱歲每人七文二分|Ngoài ra các xã phường cấp ngụ lộc và biệt nạp biệt tái, lại cứ số định hiện có, thu tiền lễ ngụ lộc mỗi người 12 đồng, cứ 100 người thì thu gạo trình diện 5 thưng; tiền trầu thì xã lớn 1 tiền, xã vừa 30 đồng; tiền đầu quan mỗi người 7 đồng 9 phân.|Cap_01-VI-0187-001|001|213|267|1-1 (ứng viên)|UNKNOWN|UNKNOWN|MEDIUM|MEDIUM|1|UNRESOLVED|SAME
PILOT-005|卯已丑升華府各縣屬一萬四千三百四十九人收各歲共四百八十三三四三十六文米共七百十四升九合除產借成每一百四陌米每色一陌|Như năm Kỷ Sửu các huyện thuộc phủ Thăng Hoa cộng 1 vạn 4.349 người, thu các tiển cộng 483 quan 3 tiển 36 đồng, gạo cộng 714 thưng 9 cáp, trừ tiền thuê mướn chở đi mỗi 100 quan là 4 tiển, gạo mỗi bao là 4 tiền, còn bao nhiêu thì chở nộp.|Cap_01-VI-0187-002|001|267|324|1-1 (ứng viên)|UNKNOWN|UNKNOWN|LOW|HIGH|1|UNRESOLVED|DIFFERENT
PILOT-006|不狹廣南於順化亦然亦細碎矣|Không riêng một xứ Quảng Nam, xứ Thuận Hoá cũng thế, rất là tủn mủn.|Cap_01-VI-0187-003|001|324|337|1-1 (ứng viên)|1|UNKNOWN|HIGH|HIGH|1|SILVER_PROVISIONAL|DIFFERENT
PILOT-007|順廣諸營許司吏与祚各縣本堂或色各效眾亥按收丁侯田粟其收各吏各既不為控矣|Các dinh ở Thuận Quảng đặt ty lại và chức sắc bản đường các phủ huyện, số người rất nhiều, khiến họ thu tiền thóc đình điền, lấy ở các lại các chức cũng không phải nhẹ.|Cap_01-VI-0187-004|001|337|372|1-1 (ứng viên)|UNKNOWN|UNKNOWN|MEDIUM|MEDIUM|1|UNRESOLVED|SAME
PILOT-008|如有受照機并美底替限例谷宮該合首合附去繫間繁簡者或減十三貫稽限二家次者咏六貫限八兩尚者侯三長限臺刃五侯司吏二貫鎮祿案詠八貨庫提欲與疾與孫該管歲十四貨庫陽長八貫五改司官八貫五內弦場侯属各八貫祀府十貫祀縣祀屬侯總欣社各四貨五門糧吏三步五陌祠圍今史舍庚各一長五陽祠堂次陽長迎所庫与土產各隊次陽長各二長通夾祀丞樣夫各一巨五問主各船社坊有換懸新禮各一支一陌|Như có lệ nộp tiền lĩnh bằng, tiền trầu và tiền thế bạc thì ở các định, cai hợp, thủ hợp tuỳ chỗ nhiều việc ít việc, chỗ nhiều việc thì hoặc tiền là 13 quan, bạc lá để" 2 hốt, chỗ vừa thì tiền 6 quan, bạc 8 lạng, chỗ ít thì tiển 2 quan bạc 1 lạng ð đồng cân, ty lại 2 quan, cai án trấn 8 quan, đề lĩnh kho và cai quan trấn tuần nguồn 14 quan, đội trưởng kho 8 quan ð tiền, cai trường, cai thuộc mỗi người 8 quan, _ký phủ 10 quan, ký huyện, ký thuộc, cai tổng, cai xã mỗi người 4 quan ð tiền, để lại 3 quan ð tiền, từ thừa, lệnh sử, xá lại thuộc 1 quan 1 tiền, thứ đội trưởng từ đường, thứ đội trưởng tuần khố và các đội thổ sản mỗi người 2 quan, thông lại, duyện lại mỗi người 1 quan 5 tiền, cho đến các thuyền, các xã, các phường, có đổi bằng mới, đều nộp 1 quan 1 tiển.|Cap_01-VI-0187-005|001–002|372|545|1-1 (ứng viên)|UNKNOWN|UNKNOWN|LOW|MEDIUM|1|UNRESOLVED|DIFFERENT
PILOT-009|有印侯并美成各營侯奇該合賦其聲間或一長九限或一長五門或一長五兩或一亥一門司夾五門發屋祿案後收各一長六門癸近源欣官三長四門後府司官一貫玖陌记縣记在該孫張莊提吏各一長三門犯垂舍更合史一貫七門祠堂迎庫次侯隊八陌|Có lệ nộp tiền ấn và tiển trầu ở các dinh, cai hợp, thủ hợp tuỳ chỗ nhiều việc ít việc, hoặc 1 quan 9 tiền, hoặc 1 quan 9 tiển, hoặc 1 quan 1 tiền, ty lại 5 tiển, cai án, cai thu, trấn thuộc mỗi người I quan 6 tiển, cai quan trấn tuần nguồn 3 quan 4 tiền, cai phủ, ty quan 1 quan 9 tiền, ký huyện, ký thuộc cai tổng, cai xã, đề lại mỗi người 1 quan 3 tiền, từ thừa, lệnh sử, xá lại thuộc 1 quan 7 tiền, thứ đội trưởng từ đường, tuần, khố 8 tiền, thông lại, duyện lại, viên tử, nhiêu phu, tướng thần lại, xã trưởng, mỗi người 5 tiền, các thuyển, các xã, thôn, phường, đổi bằng mới đều mỗi người l quan 1 tiền.|Cap_01-VI-0188-001|002|545|647|1-1 (ứng viên)|UNKNOWN|UNKNOWN|LOW|MEDIUM|1|UNRESOLVED|DIFFERENT
PILOT-010|此為內房侍女為內外五右吏礼部官之祿|Đó là lộc của thị nữ nội phòng, cùng các quan nội ngoại tả hữu, Lại bộ, LỄ bộ.|Cap_01-VI-0188-002|002|647|664|1-1 (ứng viên)|1|UNKNOWN|HIGH|HIGH|1|SILVER_PROVISIONAL|SAME
PILOT-011|至來每年正旦生日所四二处各然各職皆有禮限自一二時以上至二三易美孫自十五文以上五貫沙在公堂官收彼雖社長之微亦有八張一族美孫三十文諱日亦照|Còn như hàng năm ngày Chính đán và Sinh nhật, các chức ở hai xứ đều có bạc lễ từ 1 đồng cân trở lên đến 2 hay 3 hốt, tiển trầu từ 15 đồng trở lên đến 5 quan, quan công đường sở tại phải thu nộp, tuy chức xã trưởng là bé, cũng có người phải nộp 1 đồng cân bạc, 30 đồng tiền trầu; ngày ky cũng thế.|Cap_01-VI-0188-003|002|664|731|1-1 (ứng viên)|UNKNOWN|UNKNOWN|MEDIUM|MEDIUM|1|UNRESOLVED|SAME
PILOT-012|順廣選揚有許各人納草揚門与羽單乞升賦次內禮限侯所得亦多丙戌年符離驟將臣殿福昭陰祀府上禮限二十易五兩替侯五百十五貴又重亦限一易二歲五玄替年二千五長六百十二文附礼精限四易替味一百二貴五陌又重升限二兩五分替祿五貴一四十五文并榕限四兩替九辰武陌又重升限二鄉階陳四阳卅六文美底六阪餘祫內堂呈而禮并鬼子承柳之三頭共城六百六十四長三四女文|Tuyển trường ở hai xứ Thuận Quảng, có cho người ta nộp đơn ở cửa trường và nộp đơn xin thăng chức bậc, thu được bạc tiền thượng lễ, nội lễ cũng nhiều, như năm Bính Tuất. huyện Phù Ly có Tướng thần là Đoàn Phúc Chiêm thăng chức ký phủ, nộp thượng lễ là 20 hốt 5 lạng bạc tốt, thay bằng tiền là 512 quan ð tiển, với 1 hốt 2 đồng cân 5 phân bạc nặng cân, thay bằng tiền là 25 quan 6 tiền 12 đồng; nộp nội lễ 4 hốt bạc tốt, thay bằng tiền là 102 quan 5 tiền, với 2 lạng ð phân bạc nặng cân, thay bằng tiển là 5 quan 1 tiền 15 đồng, cùng 4 lạng bạc lá để, thay bằng tiền là 9 quan 9 tiền, với 2 đông cân bạc nặng cân, thay bằng tiển là 4 tiền 36 đồng, và tiền trầu 6 tiền, ngoài ra lễ trình diện nộp ở nội đường và tiển quà trẻ con là 8 quan 3 tiền; cộng các tiền là 664 quan 3 tiển 6 đồng.|Cap_01-VI-0188-004|002|731|893|1-1 (ứng viên)|UNKNOWN|UNKNOWN|MEDIUM|MEDIUM|1|UNRESOLVED|SAME
```

## 3. Separate API

### 3.1 Nguồn code và phiên bản ưu tiên

| Vị trí | Vai trò |
|---|---|
| `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\04_dong_hang\temp\batch_han_sentence_split.py` | Batch được ưu tiên. Nội dung giống byte với `5cb7273:04_dong_hang/batch_han_sentence_split.py` (blob `63d2ac8964851665849dd36c2f887077de091b6a`). Log và CSV của batch ghi lần chạy thành công ở layout cũ. |
| `5cb7273:04_dong_hang/experiment_seg_align.py` | Thử nghiệm V0–V6: gọi Separate theo trang hoặc theo block, có cache và kiểm tra ký tự. Chỉ còn trong Git. |
| `4851c43:04_dong_hang/han_sentence_split.py` | Smoke test `requests.post`, body cũ chỉ gồm `text` và `ocr_id`, timeout 120 giây. |
| `4851c43:04_dong_hang/test_separate_sentences_13han.py` | Thử 13 câu ghép liền, có `--url` để chọn host `kimhannom.fit.hcmus.edu.vn`; host mặc định trong script là `kimhannom.clc.hcmus.edu.vn`. |
| `4851c43:04_dong_hang/test_alignment_urllib.py` và `4851c43:04_dong_hang/test_sinonom_endpoints.py` | Probe lịch sử dựng URL từ host và đường dẫn endpoint. Cũng tìm thấy hai script này trong snapshot Git `14efeb1`. |
| `4851c43:04_dong_hang/separate_sentences_request.json` | Payload lịch sử; bộ trường dùng ở lần batch thành công được chép riêng bên dưới. |

### 3.2 Hợp đồng quan sát từ batch

- `POST https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences`; `requests.Session`, không theo redirect; timeout kết nối 10 giây, đọc 90 giây.
- Headers: `Authorization: Bearer <giá trị từ SINONOM_TOKEN>`, `Accept: application/json`, `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36`. `requests` đặt `Content-Type: application/json` qua `json=`.
- Đọc token từ `SINONOM_TOKEN`, bỏ whitespace đầu/cuối, bỏ prefix `bearer ` không phân biệt hoa thường nếu có. Không có bước phát hành token trong client; cách xin/cấp/refresh hợp lệ: `UNKNOWN`.

Body minh họa cấu trúc với một vế OCR thật (batch thực gửi toàn bộ trang, không gửi riêng snippet này):

```json
{"text":"各賦有給夫干人免民丁雜役使取其齋鄉為寓祿","ocr_id":1,"genre":"history","punctuation_group":"all"}
```

- Parser batch: HTTP `200` và `is_success is True`; lấy `data.sentences` dạng chuỗi. Nếu chuỗi bắt đầu bằng `{` sau `lstrip()`, parse lớp JSON bên trong và lấy trường `sentences` dạng chuỗi lần nữa. Regex cắt theo dấu hết câu hoặc xuống dòng, giữ dấu kết thúc và dấu đóng theo sau. Kiểm tra nội dung nối lại sau khi bỏ whitespace và nhóm dấu câu Unicode `P*`. `experiment_seg_align.py` còn yêu cầu `code == '000000'`; batch chỉ ghi mã này vào log, không sử dụng nó làm điều kiện thành công riêng.
- Giới hạn input, quota, rate limit phía máy chủ: `UNKNOWN`. Một lần chạy đã xử lý 393–485 ký tự/trang; đây là khoảng kích thước quan sát, không phải giới hạn. Delay 0,5 giây là cấu hình client. Không chuyển kết luận từ `sentence-alignment` sang Separate.

### 3.3 Response đã lưu và lỗi

`4851c43:kimhannom_sentence_test/raw_response.json`:

```json
{
  "is_success": false,
  "code": "000108",
  "message": {"title":"t_field_value_required","text":"m_field_value_required","web_text":"Giá trị truyền lên không hợp lệ, vui lòng thử lại!","debug_msg":null},
  "data": null
}
```

`4851c43:04_dong_hang/separate_sentences_response.json`; lỗi cũng được ghi trong `4851c43:han_sentence_benchmark/report.json`:

```json
{
  "is_success": false,
  "code": "000403",
  "message": {"title":"t_access_denied","text":"m_access_denied","web_text":"Truy cập bị từ chối!","debug_msg":null},
  "data": null
}
```

HTTP status và nguyên nhân cụ thể của hai response trên: `UNKNOWN`. `000108` là lỗi trường/giá trị theo message (mã này thuộc nhóm làm batch dừng, không tự động kết luận token sai). `000403` là lỗi truy cập theo message. `--reparse-saved` có logic khôi phục trường hợp wrapper JSON từng bị ghi như câu; trạng thái `content_mismatch` sau chạy hiện đăng trong log của 10 trang: không có. HTTP `429`/`5xx`, lỗi kết nối, timeout và thiếu `data.sentences` là nhánh trong client; chưa có bằng chứng chúng xảy ra trong log Separate đã khảo sát.

**JSON raw của response thành công: `UNKNOWN`.** Log thật `03_text_sach/Cap_01/HAN/segmented/run_summary.json` ghi `requests=10`, `delay_seconds=0.5`, cả 10 trang `status=ok`, mỗi trang HTTP 200 và mã `000000`. Dưới đây là phần tử đầu tiên của `pages` trong log, không phải server response:

```json
{"page":1,"source":"Cap01-001.json","ocr_segments":16,"input_chars":445,"attempts":[{"http_status":200,"api_code":"000000"}],"status":"ok","sentence_count":15,"output":"0001-sentences.csv"}
```

Ba dòng đầu ra thật từ `03_text_sach/Cap_01/HAN/segmented/0001-sentences.csv`:

```csv
id_zh,text_zh
Cap01-001-S001,爭納歲願，惡示至今。
Cap01-001-S002,有一社至十六七，將臣二十餘社長百得應務者，正許知押為額目耳。
Cap01-001-S003,各賦有給夫干人，免民丁雜役，使取其齋鄉為寓祿。
```

### 3.4 Toàn bộ batch code

Bản chép mã lịch sử/working tree, chưa thực thi trong khảo sát. `ROOT` bên dưới là nguyên văn; khi file nằm trong `temp/`, `parents[1]` cho ra `CV16/04_dong_hang`, không phải `CV16`.

```python
"""Split the first ten Cap_01 OCR pages with SinoNom's sentence API."""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import time
import unicodedata

import requests


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '02_ocr_tho/Cap_01/HAN/pages'
OUTPUT = ROOT / '03_text_sach/Cap_01/HAN/segmented'
URL = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences'
RETRYABLE = {408, 429, 500, 502, 503, 504}


def content(text):
    """Ignore punctuation and whitespace, but retain OCR letters and numbers."""
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def load_page(page):
    src = SOURCE / f'Cap01-{page:03}.json'
    data = json.loads(src.read_text(encoding='utf-8-sig'))
    rows = sorted(data['rows'], key=lambda row: row['segment'])
    if (data['info']['cap'] != 'Cap_01' or data['info']['page'] != page
            or [row['segment'] for row in rows] != list(range(1, len(rows) + 1))):
        raise ValueError(f'Invalid page or segment sequence: {src.name}')
    text = ''.join(''.join(row['han'].split()) for row in rows)
    if not content(text):
        raise ValueError(f'Empty OCR page: {src.name}')
    return src, rows, text


def split_result(result):
    if not isinstance(result, str):
        return []
    if result.lstrip().startswith('{'):
        try:
            wrapped = json.loads(result)
        except ValueError:
            return []
        result = wrapped.get('sentences') if isinstance(wrapped, dict) else None
        if not isinstance(result, str):
            return []
    return [line.strip() for line in re.findall(r'[^。！？!?\r\n]+(?:[。！？!?]+[」』”’）】]*)?', result)
            if line.strip()]


def write_page(page, text, lines, record):
    output = OUTPUT / f'{page:04}-sentences.csv'
    with output.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['id_zh', 'text_zh'])
        writer.writerows((f'Cap01-{page:03}-S{i:03}', line) for i, line in enumerate(lines, 1))
    same_content = content(''.join(lines)) == content(text)
    record.update(status='ok' if same_content else 'content_mismatch',
                  sentence_count=len(lines), output=output.name)


def reparse_saved(pages):
    """Recover responses stored as literal JSON wrapper rows by an earlier run."""
    report_path = OUTPUT / 'run_summary.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    updates = []
    for record in report['pages']:
        if record['status'] != 'content_mismatch' or 'output' not in record:
            continue
        with (OUTPUT / record['output']).open(encoding='utf-8-sig', newline='') as f:
            result = '\n'.join(row['text_zh'] for row in csv.DictReader(f))
        if result.lstrip().startswith('{') and (lines := split_result(result)):
            updates.append((record['page'], pages[record['page'] - 1][2], lines, record))
    for args in updates:
        write_page(*args)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['status'] == 'ok' for row in report['pages']) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delay', type=float, default=0.5, help='Seconds between pages')
    parser.add_argument('--reparse-saved', action='store_true', help='Recover saved JSON wrapper rows without API calls')
    args = parser.parse_args()
    if args.delay < 0:
        parser.error('--delay must be nonnegative')
    pages = [load_page(page) for page in range(1, 11)]
    if args.reparse_saved:
        return reparse_saved(pages)
    token = os.environ.get('SINONOM_TOKEN', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        parser.error('Set SINONOM_TOKEN before running the batch')

    OUTPUT.mkdir(exist_ok=True)
    summary = []
    with requests.Session() as session:
        session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'),
        })
        for page, (src, rows, text) in enumerate(pages, 1):
            if page > 1:
                time.sleep(args.delay)
            record = {'page': page, 'source': src.name, 'ocr_segments': len(rows),
                      'input_chars': len(text), 'attempts': [], 'status': 'failed'}
            summary.append(record)
            stop = False
            for attempt in range(2):
                try:
                    response = session.post(URL, json={
                        'text': text, 'ocr_id': 1, 'genre': 'history', 'punctuation_group': 'all',
                    }, timeout=(10, 90), allow_redirects=False)
                except (requests.ConnectionError, requests.Timeout) as exc:
                    record['attempts'].append({'error': type(exc).__name__})
                    if not attempt:
                        time.sleep(2)
                        continue
                    break

                status = response.status_code
                info = {'http_status': status}
                record['attempts'].append(info)
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if not isinstance(body, dict):
                    body = {}
                code = body.get('code')
                if isinstance(code, (int, str)):
                    info['api_code'] = code
                if status in (401, 403) or str(code) in {'000108', '000401', '000403', '401', '403'}:
                    stop = True
                    break
                if status == 429 and attempt:
                    stop = True
                    break
                if status in RETRYABLE and not attempt:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after and (not retry_after.isdecimal() or int(retry_after) > 30):
                        stop = True
                        break
                    time.sleep(max(2, int(retry_after or 0)))
                    continue
                if status != 200 or body.get('is_success') is not True:
                    break
                data = body.get('data')
                result = data.get('sentences') if isinstance(data, dict) else None
                lines = split_result(result)
                if not lines:
                    info['error'] = 'Missing data.sentences'
                    break
                write_page(page, text, lines, record)
                break
            print(f'Page {page:02}: {record["status"]} ({record.get("sentence_count", 0)} sentences), '
                  f'{record["attempts"]}', flush=True)
            if stop:
                summary.extend({'page': remaining, 'status': 'not_attempted'} for remaining in range(page + 1, 11))
                break

    report = {'endpoint': URL, 'delay_seconds': args.delay,
              'requests': sum(len(row.get('attempts', [])) for row in summary), 'pages': summary}
    (OUTPUT / 'run_summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['status'] == 'ok' for row in summary) else 1


if __name__ == '__main__':
    raise SystemExit(main())
```

## 4. Segmentation, chunks và ánh xạ OCR

### 4.1 Batch trong workspace

Code đầy đủ ở mục 3.4: một chunk là một trang Cap_01 (trang 1–10), kiểm tra segment liên tục từ 1, xóa whitespace từng segment rồi nối, gọi Separate, cắt theo dấu và xuất CSV UTF-8-SIG `id_zh,text_zh`. Không có thuật toán nội bộ của máy chủ (`UNKNOWN`), không cắt cứng theo số ký tự, không overlap hay ghép qua biên trang. CSV không ghi offset hay ánh xạ segment/ký tự; kiểm tra `content()` chỉ đảm bảo chuỗi nội dung sau chuẩn hóa còn nguyên. Bản `reviewed/` có mã đoạn nguồn và trang đầu/cuối, theo `03_04_GUIDE.md`.

Client batch không có cache request/response tổng quát. `--reparse-saved` đọc và **có thể ghi lại** CSV/log, không gọi API. Batch giới hạn hai lượt thử/trang: lỗi kết nối/timeout nghỉ 2 giây trước thử lại; HTTP 408, 429, 500, 502, 503, 504 dùng `max(2, Retry-After)`; dừng nếu `Retry-After` khác số thập phân nguyên hoặc >30 giây, nếu 429 lặp lại hoặc nếu thuộc nhóm lỗi dừng sớm ở code. Delay mặc định 0,5 giây giữa các trang. Các giá trị này là chính sách client.

### 4.2 Thí nghiệm trong lịch sử Git

`5cb7273:04_dong_hang/experiment_seg_align.py` chạy V0–V6: V0 ranh giới câu, V1 thêm chấm phẩy, V2 thêm phẩy/đốn hiệu/hai chấm, V3 chia cụm dài theo V2 và gom theo `--long-chars` (45 mặc định; có thể vượt nếu một mảnh đơn quá dài), V4 gọi Separate trên toàn block thay vì từng trang, V5/V6 dùng kết quả dóng hàng để điều chỉnh biên. Input: JSON theo trang + workbook Việt; output: CSV từng biến thể (`segmented`, `alignment`) và file so sánh/review/log. Trích đoạn logic đã dùng:

```python
def content(s):
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))

def split_marks(s, marks):
    # Attach punctuation to the preceding text; newline is a boundary, not content.
    parts=re.split('(['+re.escape(marks)+r']+[」』”’）】]*)',s)
    out=[]; current=''
    for i,x in enumerate(parts):
        current+=x
        if i%2 and content(current): out.append(current.strip()); current=''
    if content(current): out.append(current.strip())
    elif current.strip() and out: out[-1]+=current.strip()
    return out

SENT='。！？!?\r\n'; SEMI=SENT+'；;'; FINE=SEMI+'，,、：:'

def boundaries(parts):
    ends=[0]
    for p in parts:
        if content(p): ends.append(ends[-1]+len(content(p)))
    return ends

def resegment(parts, cuts):
    text=''.join(parts); n=len(content(text)); cuts=sorted(set(cuts)|{0,n})
    # Map character-content offset to raw string offset; attach punctuation left.
    loc=[i for i,c in enumerate(text) if content(c)]
    pos=[0]+loc[1:]+[len(text)]
    return [text[pos[a]:pos[b]].strip() for a,b in zip(cuts,cuts[1:]) if a<b]

def local_long(parts, limit):
    out=[]
    for p in parts:
        if len(content(p))<=limit: out.append(p); continue
        chunks=split_marks(p,FINE); buf=''
        for c in chunks:
            if buf and len(content(buf+c))>limit: out.append(buf); buf=''
            buf+=c
        if buf: out.append(buf)
    return out
```

Block theo trang (`--block-pages` mặc định 2). Trích các dòng tạo block và ánh xạ biên kết quả sau khi kiểm tra `content(''.join(parts)) == content(raw)`; bỏ các bước dóng hàng giữa hai đoạn:

```python
for start in range(0,len(pages),args.block_pages):
    block=pages[start:start+args.block_pages]; first,last=block[0][0],block[-1][0]
    raw=''.join(t for _,t in block); n=len(content(raw)); page_ends=boundaries([t for _,t in block]); block_id=f'{first:04}-{last:04}'
    # ... build parts for each variant ...
    ends=boundaries(parts); cuts=set(ends)
    units=[]
    for j,(a,b) in enumerate(zip(ends,ends[1:])):
        p0=block[bisect.bisect_right(page_ends,a)-1][0]
        p1=block[bisect.bisect_left(page_ends,b)-1][0]
        units.append({'id_zh':f'{block_id}-S{j+1:04}','text_zh':parts[j], 'han_page_start':p0,'han_page_end':p1,'char_start':offset+a,'char_end':offset+b})
    # ... after processing variants ...
    offset+=n
```

`resegment` quy đổi offset nội dung vào **chuỗi đã được chấm câu**; `char_start/char_end` dùng luồng bỏ whitespace và dấu câu, không phải offset raw của workbook. Trích client thử nghiệm, với `self.session` đã cấu hình Bearer từ `SINONOM_TOKEN` như batch; `dump` ghi JSON UTF-8 và tạo thư mục cha. Không có retry tự động riêng trong đoạn mã này.

```python
def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

# Methods from Client:
def cached(self, kind, payload, fn):
    path=self.a.output/'cache'/f'{kind}_{digest(payload)}.json'
    if path.exists(): self.hits+=1; return json.loads(path.read_text(encoding='utf-8'))
    if self.calls>=self.a.max_calls: raise BudgetError('Global API call budget exhausted')
    if self.calls: time.sleep(self.a.delay)
    self.calls+=1
    result=fn(); dump(path,result); return result

def punctuate(self, text):
    payload={'text':text,'ocr_id':1,'genre':'history','punctuation_group':'all'}
    def request():
        r=self.session.post(URL,json=payload,timeout=(10,self.a.timeout),allow_redirects=False)
        r.raise_for_status(); body=r.json()
        if body.get('is_success') is not True or str(body.get('code'))!='000000':
            raise RuntimeError(f'Segmentation API: {body.get("code")}')
        return body
    body=self.cached('split',payload,request)
    s=body['data']['sentences']
    if isinstance(s,str) and s.lstrip().startswith('{'): s=json.loads(s)['sentences']
    if not isinstance(s,str) or content(s)!=content(text):
        raise ValueError('Segmentation changed OCR content; response rejected')
    return s.strip()
```

Cache dùng cả dòng dóng hàng (loại `align`) lẫn tách câu (loại `split`). Mặc định `--max-calls 100`, `--delay 0.5`, `--timeout 90`; cache hit không tiêu budget. Thành công HTTP/JSON được cache trước khi `punctuate` kiểm tra bảo toàn OCR. Không thấy file cache Separate trong workspace/Git đã khảo sát.

`5cb7273:04_dong_hang/joint_seg_align_cpu.py` dùng lattice span theo stride + ranh giới segment/dấu câu rồi chọn đường bằng dóng hàng CPU; `5cb7273:04_dong_hang/hybrid_alignment_cpu.py` (V18–V23) kết hợp các helper của thí nghiệm Separate và joint CPU, không có client Separate độc lập. Các script alignment lịch sử khác: `5cb7273:04_dong_hang/{batch_alignment_2x2.py,diagnose_sentence_alignment.py}`; `align_pure_api.py` được mô tả trong `PROJECT_CONTEXT.md` nhưng không phải client Separate. Đoạn local candidate (trích joint CPU; `ZHNUM` là regex số của script):

```python
def han_source(pages):
    raw=''; preferred={0}; page_ends=[]
    for p,parts in pages.items():
        for part in parts:
            raw+=part; preferred.add(len(raw))
        page_ends.append((len(raw),p))
    for m in re.finditer(r'[。！？；，、：!?;,]+',raw): preferred.add(m.end())
    return raw,preferred,page_ends

def candidate_spans(raw, preferred,stride,minlen,maxlen):
    n=len(raw); cuts=sorted(set(range(0,n,stride))|preferred|{n})
    # Do not begin/end inside an unbroken numeric expression or immediately before punctuation.
    forbidden={i for m in ZHNUM.finditer(raw) for i in range(m.start()+1,m.end())}
    cuts=[x for x in cuts if x in (0,n) or (x not in forbidden and not unicodedata.category(raw[x]).startswith('P'))]
    spans=[]
    for i,a in enumerate(cuts[:-1]):
        for j in range(i+1,len(cuts)):
            b=cuts[j]
            if b-a>maxlen: break
            if b-a>=minlen or a==0 or b==n:
                if content(raw[a:b]): spans.append((i,j,raw[a:b]))
    return cuts,spans
```

### 4.3 Offset raw tương thích benchmark

`pipeline/artifacts/phase1/han_pages.jsonl` lưu `file_body_span`, `file_text_span`, `global_raw_span`, `global_nfc_span`. Đoạn dưới từ `pipeline/scripts/normalize_phase1.py` là cách ánh xạ về **file TXT OCR gốc**, không phải mã ánh xạ trực tiếp response API. Nếu có biên raw trong trang, lấy `file_text_span[0] + biên`; nếu có biên trên luồng content bỏ whitespace/dấu thì không dùng công thức đó trước khi quy đổi. Không tìm thấy hàm trong batch ánh xạ trực tiếp response về offset TXT/JSON OCR gốc.

```python
HEADER = re.compile(r"^=== (Cap_\d+) \| PAGE (\d+) ===[^\S\r\n]*\r?$", re.M)

def load_han(cap, path, pages_expected, raw_offset, norm_offset):
    text = (ROOT / path).read_bytes().decode("utf-8-sig")
    markers = list(HEADER.finditer(text))
    if (not markers or text[:markers[0].start()].strip()
            or [m[1] for m in markers] != [cap] * pages_expected
            or [int(m[2]) for m in markers] != list(range(1, pages_expected + 1))):
        raise ValueError(f"Missing, duplicate, or out-of-order page header in {path}")
    rows = []
    for i, m in enumerate(markers):
        page = int(m[2])
        body_start = m.end() + (text[m.end():m.end()+1] == "\n")
        body_end = markers[i+1].start() if i+1 < len(markers) else len(text)
        body = text[body_start:body_end]
        raw = body.strip()
        if not raw:
            raise ValueError(f"Empty OCR page: {cap} {page}")
        normalized = nfc(raw)
        trim_start = body_start + len(body) - len(body.lstrip())
        rows.append({"id": f"{cap}-HAN-{page:03d}", "cap": cap, "han_pdf_page": page,
                     "pdf_path": f"01_nguon/{cap}/HAN.pdf", "source": source(path),
                     "file_body_span": [body_start, body_end],
                     "file_text_span": [trim_start, trim_start + len(raw)],
                     "body_original": body, "text_original": raw, "text_nfc": normalized,
                     "global_raw_span": [raw_offset, raw_offset + len(raw)],
                     "global_nfc_span": [norm_offset, norm_offset + len(normalized)]})
        raw_offset += len(raw)
        norm_offset += len(normalized)
    return rows, raw_offset, norm_offset
```

`nfc(text)` gọi `unicodedata.normalize("NFC", text)`; `source(path)` lưu `{"path": path.as_posix()}`. Với file JSON OCR theo trang, trường `segment`, `id`, `column` cho định danh cột; chưa có bảng nối ký tự theo cột trong output batch.

## 5. Runtime environment và lệnh hiện có

- Microsoft Windows 11 Home, kernel báo `Microsoft Windows NT 10.0.26300.0`, PowerShell 5.1. Python 3.11.9 64-bit (AMD64); `python` và đường dẫn `.venv` đều báo executable `C:\Users\Tuan TCA\OneDrive\Tai_Lieu\3ndYear\NLP\Midterm\CV16\.venv\Scripts\python.exe`.
- `python -B -m pip list --disable-pip-version-check`: `requests 2.34.2`, `urllib3 2.8.0`, `certifi 2026.10.23`, `openpyxl 3.1.5`, `pandas 2.2.3`, `numpy 1.26.4`, `scipy 1.17.1`, `regex 2026.11.9`, `jieba 0.42.1`, `nltk 3.9.2`, `sentence-splitter 1.4`, `cn2vn 0.2.1`, `cn2an 0.5.24`, `faiss-cpu 1.11.0`, `numba 0.61.2`, `torch 2.7.1`, `transformers 4.56.1`, `sentence-transformers 5.0.0`, `scikit-learn 1.9.1`, `pillow 13.0.0`. Batch Separate chỉ import thêm `requests` ngoài thư viện chuẩn. Không đồng nhất danh sách này với môi trường CPU benchmark ghi trong tài liệu cũ.

Lệnh lịch sử từ `docs/03_04_GUIDE.md` (ghi để tham khảo, chưa chạy trong khảo sát):

```powershell
python -B 04_dong_hang/batch_han_sentence_split.py
python -B 04_dong_hang/batch_sentence_alignment.py --han-dir 03_text_sach/Cap_01/HAN/reviewed --viet-xlsx 02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx --pages 1 10 --output 04_dong_hang/Cap01_0001-0010_alignment_auto.xlsx --max-calls 18 --timeout 22
```

Hai đường dẫn script trên không còn tại chỗ tài liệu chỉ. Bản hiện có nằm trong `04_dong_hang/temp/`; chỉ đổi cwd hoặc đường dẫn lệnh không sửa được `ROOT` của batch Separate vì tính từ `__file__`. Lệnh gọi đầu-cuối đã xác minh cho layout hiện tại: `UNKNOWN`. Với layout cũ, tùy chọn offline `--reparse-saved` vẫn là thao tác ghi, không phải kiểm tra chỉ đọc. Tương tự, `docs/PHASE1_AUDIT.md` ghi `python -B scripts/normalize_phase1.py --output artifacts/phase1`, nhưng script hiện nằm dưới `pipeline/scripts/` và dùng `parents[1]` làm `ROOT`; không coi lệnh tài liệu là lệnh tái lập đã xác minh cho layout này.
