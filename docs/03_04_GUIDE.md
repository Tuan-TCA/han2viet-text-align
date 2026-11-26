# Bước 03–04: Tách câu Hán và ghép Hán–Việt

Luồng hiện tại chạy thử trên **10 trang PDF đầu của Hán Cặp 01**. Đầu vào ở bước 02: JSON OCR `02_ocr_tho/Cap_01/HAN/pages/Cap01-001.json` đến `Cap01-010.json` và workbook `02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx` (sheet `CAU_VIET`).

## `03_text_sach/Cap_01/HAN/`

| File | Dùng để làm gì |
| --- | --- |
| `segmented/0001-sentences.csv` đến `0010-sentences.csv` | Kết quả tách câu Hán ban đầu từ API. |
| `segmented/run_summary.json` | Nhật ký tách câu: số lượt gọi, số câu mỗi trang và trạng thái kiểm tra bảo toàn ký tự OCR. |
| `reviewed/0001-reviewed.csv` đến `0010-reviewed.csv` | Bản rà ranh giới để ghép. Có mã đoạn nguồn và trang đầu/cuối cho câu vắt trang. `scan_verified` là đoạn đã so ảnh; `boundary_review` là đoạn rà ranh giới, chưa xác nhận từng chữ. |

## `04_dong_hang/`

| File | Dùng để làm gì |
| --- | --- |
| `batch_han_sentence_split.py` | Nối OCR đúng thứ tự rồi gọi `separate-sentences`; ghi kết quả vào `segmented/`. |
| `batch_sentence_alignment.py` | Đọc các CSV Hán đã tách hoặc đã rà và Excel Việt bước 02. Tự chọn cửa sổ từ `TRANG_VIET`, gọi API theo cụm và xuất đề xuất có thể truy về nguồn. |
| `align_sinonom_api.py` | Hàm gọi API `sentence-alignment` mà script batch sử dụng. |
| `Sino_Vietnamese_Sentence_Alignment_Template.xlsx` | Mẫu cột, quy tắc và ví dụ gán nhãn SINO. |
| `Cap01_0001-0010_alignment_auto.xlsx` | Báo cáo tự động: `Alignment_Dataset` là kết quả chọn theo thứ tự và các đơn vị Hán chưa ghép; `API_Candidates` lưu đề xuất, điểm và vị trí trích từ Excel Việt. |
| `Cap01_0001-0010_alignment_auto_run.json` | Nhật ký ghép theo cụm: đầu vào, phản hồi API, thống kê và lỗi từng lượt. |
| `Cap01_0001-0010_alignment_reviewed.xlsx` và `Cap01_0001-0010_alignment_run.json` | Kết quả rà thủ công và nhật ký của đợt thử cũ, dùng để đối chiếu. |

## Chạy lại

Từ thư mục gốc, dùng môi trường Python có `requests`, `pandas`, `openpyxl` và đặt biến môi trường `SINONOM_TOKEN` trước khi gọi API:

```powershell
python -B 04_dong_hang/batch_han_sentence_split.py
python -B 04_dong_hang/batch_sentence_alignment.py --han-dir 03_text_sach/Cap_01/HAN/reviewed --viet-xlsx 02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx --pages 1 10 --output 04_dong_hang/Cap01_0001-0010_alignment_auto.xlsx --max-calls 18 --timeout 22
```

Đổi `--han-dir`, `--viet-xlsx`, `--pages` và `--output` để chạy dữ liệu khác. Có thể dùng thư mục `segmented/` nếu chưa có bản rà ở bước 03. Script nghỉ 0,5 giây giữa lượt gọi theo mặc định; khi lỗi tạm thời, thử cụm nhỏ hơn trong giới hạn `--max-calls`.

**Quy tắc duyệt:** lấy câu Hán làm mốc; phía Việt có thể là một vế trích nguyên văn từ Excel. Báo cáo tự động để trống `Label_Target`; chỉ gán `1` khi xác nhận `OMISSION=0`, `ADDITION=0` và `MISSING=0`. Điểm API chỉ hỗ trợ chọn cặp để rà.
