# Stage04 V4 Handoff Package

## Mục tiêu

Gói này chuẩn bị dữ liệu và đặc tả để Agent hoàn thành pipeline Stage04 qua 4 bước:

1. Khép phần Hán–Việt nối tiếp ở Cap_01, trang Hán 2–4.
2. Kiểm tra tình trạng Gold và tạo bộ review độc lập.
3. Tổng quát hóa thuật toán V4, không hardcode offset/VI_ID.
4. Benchmark trên các cửa sổ mới của cả Cap_01 và Cap_02, kiểm tra tương thích Stage04.

## Bắt đầu

1. Giải nén `Stage04_V4_Handoff_Package.zip` vào thư mục gốc repository.
2. Mở `AGENT_PROMPT.md`.
3. Gửi toàn bộ nội dung prompt cho Agent và yêu cầu Agent thực thi, không chỉ lập kế hoạch.
4. Agent phải kiểm tra các request log hiện có trước khi xác nhận sáu benchmark windows là mới.

## Các file quan trọng và cách dùng

| File | Agent phải dùng để làm gì |
|---|---|
| `inputs/han_segments_full.jsonl` | Nguồn S4 đầy đủ của cả hai Caps; dùng làm đầu vào Han và truy xuất offset. |
| `inputs/window_context_refined.jsonl` | Context Han–Việt theo trang; dựng input Stage04. |
| `inputs/page_mapping_refined.jsonl` | Context mapping trang; phân biệt VERIFIED, estimated, ambiguous. |
| `inputs/VIET_Cap01_0186-0251.xlsx` | Nguồn câu Việt Cap_01, VI_ID và cờ OCR. |
| `inputs/VIET_Cap02_0001-0105.xlsx` | Nguồn câu Việt Cap_02 cho benchmark. |
| `candidate_data/page3_4_candidate_extension.json` | 8 giả thuyết mapping nguồn [893,1499), không phải Gold. |
| `candidate_data/page3_4_candidate_extension.xlsx` | Bảng đọc thủ công, S4 trace và ảnh scan trang Hán/Việt. |
| `candidate_data/v4_candidate_extended.json` | Ghép 12 nhóm V4 pilot với 8 candidate extension để test trên [0,1499). |
| `candidate_data/v4_candidate_extended.xlsx` | Bảng Excel của candidate V4 mở rộng. |
| `candidate_data/Stage04_V4_Handoff_Review_Pack.xlsx` | Bộ review mù: 15 baseline + 8 extension, nguồn scan, VI text, Gold audit. |
| `candidate_data/fresh_benchmark_seed.jsonl` | Sáu cửa sổ benchmark cùng raw Han và Vietnamese context. |
| `candidate_data/fresh_benchmark_candidates.csv` | Manifest sáu cửa sổ và metadata. |
| `candidate_data/fresh_benchmark_seed.xlsx` | Bản xem xét benchmark bằng Excel. |
| `candidate_data/benchmark_exclusions.json` | Các trang đã dùng trong các thí nghiệm trước; Agent phải đối chiếu thêm request logs. |
| `candidate_data/source_integrity_report.json` | Kiểm chứng 2,808 S4 segments và offset round-trip. |
| `spec/gold_status_audit.md` | Chứng minh file `verified_v2` chưa có Reviewer_Label; tránh gọi nhầm là Gold. |
| `spec/v4_generalization_spec.md` | Hợp đồng thuật toán V4 tổng quát. |
| `spec/benchmark_protocol.md` | Quy trình benchmark và metric. |
| `spec/four_step_execution_plan.md` | Tóm tắt bốn bước. |
| `AGENT_PROMPT.md` | Prompt đầy đủ để Agent thực thi. |
| `previous_v4/` | Code, tests và kết quả V4 pilot cũ để đối chiếu, không ghi đè. |
| `tests/test_handoff_pack.py` | 11 kiểm thử nguồn, offset, candidate và benchmark seed. |

## Phát hiện nguồn cần chú ý

- Cap_01 có 53 trang, 23,738 ký tự; Cap_02 có 92 trang, 29,590 ký tự.
- Full Stage03 S4 có 2,808 segments. Kiểm tra lại cho kết quả 0 sai lệch `global_raw_span` và 0 sai lệch `source.file_span`.
- Cap_01 page 3 = `[905,1371)`; page 4 = `[1371,1764)`.
- Candidate extension `[893,1499)` gồm VI 0189-001 đến VI 0190-005.
- VI workbook `viet_page_start/end` 189–190 là PDF page indices; ảnh scan cho thấy số trang in là 192–193.
- `Semantic_Gold_Review_verified_v2.xlsx` có 15 dòng Proposed_Label với số đếm theo từng dòng là 5 TRUE / 7 FALSE / 3 UNKNOWN. Sheet Readme báo 5/8/2, có mâu thuẫn. Cả 15 `Reviewer_Label` đều trống.
- `Stage04_Gold_Review_Pack.xlsx` có 24 dòng blind review và cả 24 `Reviewer_Label` đều trống. Chưa có Gold độc lập.

## Kiểm thử gói handoff

Chạy từ thư mục gốc repository sau khi giải nén:

```bash
python -B Stage04_V4_Handoff/tests/test_handoff_pack.py
python -B Stage04_V4_Handoff/previous_v4/test_stage04_v4.py
```

Kết quả kiểm tra trước khi đóng gói:
- Handoff tests: 11/11 PASS.
- Previous V4 pilot tests: 9/9 PASS.

Có cảnh báo warmup của spreadsheet runtime khi Python khởi động trong môi trường hiện tại; đây không phải lỗi test, cả hai bộ test đều kết thúc `OK`.

## Giới hạn

Gói này không phải production release. Các page3–4 spans là source-backed candidates, không phải API outputs hay Gold. Không chạy full-corpus live Alignment. Agent chỉ được thực hiện continuation experiment và fresh benchmark theo prompt.
