# Đánh giá lại Alignment API (offline)

Đọc lại **42** phản hồi gốc; bỏ 1 lượt dùng cache. Chạy lại V0 bằng logic cũ và đối chiếu trực tiếp các dòng metrics/cặp Silver lưu từ lần trước. Không gọi API.

| Chỉ số | V0 | V1 | V2 |
|---|---:|---:|---:|
| Dòng chưa ánh xạ được | 23 | 17 | 17 |
| Nhóm gộp | 0 | 0 | 0 |
| VI_ID đầy đủ theo phản hồi | 98 | 125 | 125 |
| VI_ID đầy đủ duy nhất theo phản hồi | 98 | 125 | 125 |
| VI_ID đầy đủ khác nhau toàn pilot (kể cả đối chứng) | 12 | 14 | 14 |
| Exact ChatGPT | 27/94 | 27/94 | 27/94 |
| Exact DeepSeek | 30/94 | 35/94 | 35/94 |
| Exact đồng thuận | 27/66 | 27/66 | 27/66 |
| IoU Hán trung bình (CG / DS) | 0.430 / 0.426 | 0.482 / 0.479 | 0.482 / 0.479 |
| Độ phủ ký tự Hán / Việt | 83.62% / 81.70% | 88.85% / 90.82% | 88.85% / 90.82% |
| Ký tự Hán / Việt bị phủ trùng | 0 / 0 | 0 / 0 | 0 / 0 |

“VI_ID đầy đủ” tính một lần cho mỗi cặp (phản hồi, VI_ID) có toàn bộ đoạn nằm trong một ứng viên Hán–Việt ánh xạ được; chỉ số “duy nhất” loại các trường hợp có nhiều ứng viên cùng phủ hết ID. Độ phủ/trùng tính bên trong từng phản hồi thành công rồi cộng, không coi việc chạy lại hay cửa sổ chồng lấn là lỗi. Silver dùng cùng mẫu số cho ba phiên bản và không dùng điều khiển mapping/gộp; IoU bằng 0 nếu không có một dự đoán duy nhất cho cả đoạn Việt. Đây là số liệu đồng thuận ranh giới, không phải xác nhận nghĩa.

## Direct S4

| Phiên bản | Exact CG / DS | Exact đồng thuận | IoU CG / DS |
|---|---:|---:|---:|
| V0 | 5/12 / 6/12 | 5/8 | 0.707 / 0.705 |
| V1 | 5/12 / 7/12 | 5/8 | 0.787 / 0.789 |
| V2 | 5/12 / 7/12 | 5/8 | 0.787 / 0.789 |

## Thay đổi thực tế

- V1 khôi phục 20 dòng chưa ánh xạ ở V0; 14 dòng đi theo chiều ngược lại. Fallback không chấp nhận cắt giữa một số, ví dụ chỉ trả `727 bát` trong khi `727` là phần cuối của số nguồn.
- V2 tạo 0 nhóm liên tục, đủ đoạn. Không tự nối qua khoảng trống, overlap hay dòng của một VI_ID khác.
  - Không gộp E01-S4 / Cap_01-VI-0188-004, dòng [12, 13]: điểm nối Hán [808, 808], điểm nối Việt [169, 170]. Hai đầu phải bằng nhau ở cả hai vế.

Trạng thái ánh xạ Hán / Việt của các dòng còn lại ở V1: `indices_text / text_mismatch`: 17.

Workbook `comparison.xlsx`: `Mapping rows` giữ từng dòng API và kết quả V0/V1/V2; V2 lặp span nhóm trên các dòng nguồn trong bảng truy vết, nhưng mỗi nhóm chỉ tính một lần trong metrics. `Silver comparison` hiển thị ba dự đoán và hai tham chiếu trên cùng dòng.
