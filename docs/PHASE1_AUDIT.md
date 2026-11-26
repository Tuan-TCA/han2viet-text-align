# Giai đoạn 1 — Kiểm kê và chuẩn hóa Hán–Việt

Chạy từ thư mục gốc bằng Python hiện có (`openpyxl`):

```powershell
python -B scripts/normalize_phase1.py --output artifacts/phase1
```

Thư mục phải chưa tồn tại; đổi `--output` sang một đường dẫn mới khi cần tái lập. Đầu vào được định danh bằng SHA-256 trong `audit.json`.

| Đầu ra | Nội dung |
|---|---|
| `han_pages.jsonl` | ID trang, vị trí trong tệp OCR, trang PDF, nguyên văn và bản NFC |
| `viet_segments.jsonl` | Các mục `dung_de_ghep = TRUE`, ID gốc đã có tiền tố cặp, trang đầu/cuối và số dòng `CAU_VIET` |
| `page_mapping.jsonl` | Dòng `TRANG_VIET` nguyên gốc kèm mốc giao nhau đã xác minh, ứng viên và cửa sổ tìm kiếm. Mốc có chú thích nửa trang giữ nguyên chú thích. |
| `silver_benchmark.jsonl` | 12 cặp có sẵn, hai phương án biên, nhãn gốc và liên kết tới OCR/Excel |
| `audit.json` | Số lượng, bất thường, cặp nghi trùng, báo cáo truy nguồn Silver và phần ngoài phạm vi |

## Quy ước offset

- Mọi span dùng Unicode code point, tính từ 0, điểm cuối loại trừ. `file_body_span` và `file_text_span` trỏ vào tệp OCR sau giải mã `utf-8-sig`, giữ nguyên ký tự xuống dòng. `body_original` giữ toàn bộ phần thân trang sau dòng tiêu đề; `text_original` chỉ bỏ khoảng trắng hai đầu phần thân.
- `global_raw_span` cắt luồng nối `text_original`; `global_nfc_span` cắt luồng nối `text_nfc`. Hai luồng nối các trang theo thứ tự `Cap_01` rồi `Cap_02`, không xen ký tự phân cách và không bỏ nội dung trong trang. Tổng độ dài mỗi luồng trong bản này là 53.328 ký tự. NFC không thay đổi nội dung các trang Hán hiện tại.
- Offset Silver gốc trỏ vào 905 ký tự đầu của luồng raw. Cả 12 vế Hán trong `Alignment_Dataset` và các phương án Hán trong `Comparison` đều cắt đúng văn bản OCR tại offset đã ghi; cả 12 vế Việt khớp đoạn theo ID. Offset này chỉ xác minh truy nguồn, không xác minh nghĩa.

## Kết quả kiểm kê

| Cặp | Trang Hán OCR/PDF | Phạm vi Việt PDF trong Excel | Mục Việt dùng / loại | Đoạn Việt vắt trang | Mốc xác minh / chưa xác minh |
|---|---:|---|---:|---:|---:|
| Cap_01 | 53/53 | 186–251 | 685 / 101 | 60 | 6 / 60 |
| Cap_02 | 92/92 | 1–105 | 991 / 403 | 46 | 7 / 98 |

Đã đối chiếu số trang PDF bằng `pdfinfo`, kiểm tra thứ tự trang, ID Việt, span và số mục chạm trang. Không phát hiện lỗi ở các kiểm tra đó. Có 5 nhóm đoạn Việt trùng nguyên văn sau NFC và bỏ khoảng trắng đầu/cuối; tất cả vẫn được giữ với ID riêng.

**Khoảng trống mapping Cap_02:** các cửa sổ trong workbook chỉ phủ Hán 001–051. Mốc cuối ở Việt 105 chỉ tới nửa phải Hán 051 (cuối Quyển V). Hán 052–092 hiện không có cửa sổ Việt trong workbook. Giữ đủ 92 trang; khi mở rộng alignment ngoài vùng đã có, trước hết cần xác minh phạm vi bản dịch tương ứng. Không suy ra nhãn `MISSING` từ khoảng trống mapping.

**Trang Hán cần so với PDF:** dùng `SequenceMatcher` hai chiều (lấy giá trị lớn hơn), trên chuỗi NFC bỏ khoảng trắng; ngưỡng 0,90. Ba cặp của Cap_01 cần rà: 036–037 (90,66%), 038–039 (94,58%) và 049–050 (94,16%). Không cặp nào giống hệt theo phép so này. Chưa đối chiếu ảnh PDF, chưa xóa hay sửa nội dung OCR.

## Benchmark và template

Workbook hợp nhất có sáu sheet như dự kiến. Trong 12 cặp, 8 cặp đồng thuận biên Hán, 4 cặp bất đồng; `PILOT-002`, `PILOT-006`, `PILOT-010` có nhãn dương tạm thời, 9 cặp giữ `null`. `PILOT-006` vẫn mang cờ bất đồng ranh giới. Đoạn `[893, 905)` của trang 002 được giữ ở `silver.unaligned` với trạng thái `OUT_OF_SCOPE`. Không dùng Silver để suy ra độ chính xác tổng thể.

Template `04_dong_hang/Sino_Vietnamese_Sentence_Alignment_Template.xlsx` đọc được từ `HEAD`; không khôi phục tệp đã bị xóa trong working tree. Sheet `Alignment_Dataset` có 11 cột; `OMISSION` là thiếu một phần nội dung, `ADDITION` là thừa/lệch phạm vi, `MISSING` là khuyết vế tương ứng. Các kiểu cho phép gồm `1-1`, `1-N`, `N-1`, `N-M`, `1-0`, `0-1`. Kết quả giai đoạn này là dữ liệu đầu vào, chưa phải Excel nộp bài. Chưa tìm thấy v16/v17 để tái lập baseline.

Đã kiểm tra độc lập trực tiếp trên artifact: 5 hash nguồn, ID duy nhất, span raw/NFC liên tục và khớp nguồn cho cả 145 trang, 1.676 dòng Việt và 171 dòng mapping khớp Excel, 12 liên kết Silver và biên thay thế khớp bản OCR. Chạy lại với cùng đường dẫn đầu ra trả mã 2 để tránh ghi đè.
