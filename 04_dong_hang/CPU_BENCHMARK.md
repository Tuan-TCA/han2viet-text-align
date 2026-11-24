# Thử nghiệm tách câu và đồng hàng trên CPU

Pilot Cặp 01: Hán trang PDF 1–2 (16 đơn vị đã rà ranh giới); cửa sổ Việt do `TRANG_VIET` chọn là trang PDF 186–188. Hai phương án đầu vào dùng cùng bản Hán: giữ ranh giới Việt trong workbook hoặc tách lại từng đơn vị Việt bằng Underthesea. Cả API và BertAlign nhận các vế Việt tách từ cùng cửa sổ; API áp dụng giới hạn số vế trên từng request.

| Đầu vào | API: cặp / đơn vị Hán phủ | BertAlign: cặp / đơn vị Hán phủ | Hybrid: cặp / đơn vị Hán phủ | API | BertAlign CPU |
|---|---:|---:|---:|---:|---:|
| Ranh giới đã có | 11 / 12 | 13 / 16 | 12 / 13 | 15,7 s | 49,6 s, gồm tải/nạp model lần đầu và khởi tạo |
| Tách lại Việt bằng Underthesea | 11 / 12 | 12 / 16 | 12 / 13 | 21,5 s | 34,2 s |

Underthesea đổi 12 đơn vị Việt thành 13. API trả thành công cả 4 lượt. Hybrid giữ các cặp API đã được chọn và chỉ thêm cặp BertAlign không chồng lấn và không đảo thứ tự: thêm 1 đề xuất cho mỗi biến thể. Workbook tham chiếu có 4 cặp mang nhãn hợp lệ trên toàn workbook; không cặp đề xuất nào trùng khớp cả hai văn bản sau chuẩn hóa khoảng trắng. Vì vậy chưa có số `label=1` hoặc độ chính xác có thể so sánh trên pilot. Cột `Label_Target` để trống cho cặp chưa đối chiếu được.

## Chạy lại

Từ thư mục `CV16`, dùng Python 3.11 trong môi trường `.venv_cpu_benchmark`. Bản thử dùng `torch==2.7.1`, `sentence-transformers==3.2.1`, `transformers==4.52.4`, `numpy==2.2.6`, `underthesea==6.8.4`, cùng `requests`, `openpyxl`, `pandas`, `faiss-cpu`, `numba`, `sentence-splitter`, `googletrans`. Lấy source [BertAlign Việt](https://github.com/vuongquocphong/bert_base_vn_deploy/tree/master) và đưa đường dẫn qua `--bert-source`; mặc định là `.venv_cpu_benchmark/bert_base_vn_deploy-master` dưới thư mục script. LaBSE được tải vào cache trong lần nạp đầu. Script đặt `zh`/`vi` cố định thay cho bước gọi Google Translate. Đặt `SINONOM_TOKEN` trong môi trường nếu chạy API. Thư mục đầu ra phải chưa tồn tại.

```powershell
$py = '.\04_dong_hang\.venv_cpu_benchmark\Scripts\python.exe'
& $py -B -X utf8 .\04_dong_hang\cpu_alignment_benchmark.py --self-test
& $py -B -X utf8 .\04_dong_hang\cpu_alignment_benchmark.py --pages 1 2 --max-calls 12 --output .\04_dong_hang\cpu_benchmark_runs\cap01_rerun
```

Dùng `--max-calls 0` để chỉ chạy local. Tệp `summary.json` ghi thời gian, số cặp và kết quả từng lượt API. Các tệp `*_review.csv` chứa đề xuất; tọa độ Việt trong mỗi tệp thuộc phương án tách câu tương ứng.

Jiayan chưa chạy được: gói Python cài được, nhưng KenLM không build được trong môi trường Windows hiện tại (CMake/NMake không có cấu hình compiler phù hợp). Trên môi trường có KenLM, cài `jiayan` và `opencc-python-reimplemented`, rồi thêm `--jiayan-models <thư-mục>` chứa `jiayan.klm`, `cut_model`, `punc_model` để bật biến thể bổ sung.
