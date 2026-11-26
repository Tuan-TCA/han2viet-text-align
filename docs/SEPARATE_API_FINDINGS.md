# Separate API — Cap_01, Hán 001–002

Nguồn: [`results.json`](../pipeline/artifacts/separate_pilot_cap01/results.json) và [báo cáo pilot](../pipeline/artifacts/separate_pilot_cap01/report.md).

| Chỉ số | Tách từng trang | Ghép hai trang |
|---|---:|---:|
| Request | 2 | 1 |
| Giữ nguyên ký tự nội dung theo đúng thứ tự | 904/904 | 904/904 |
| Đơn vị tách | 24 | 29 |
| Biên nội vùng trùng Silver (đồng thuận / ChatGPT / DeepSeek) | 8/9 · 8/11 · 9/11 | 8/9 · 8/11 · 10/11 |
| Câu vắt trang | 0 | 1 |
| Tổng thời gian request | 1.386 ms | 1.012 ms |

Ba request đều thành công. OCR ghép hai trang chứa 905 code point, trong đó có 904 ký tự nội dung theo phép so bỏ khoảng trắng và dấu câu. Mỗi payload chỉ được thử một lần.

- **Vắt trang:** Ghép trang cho câu `[372, 452)` băng qua offset 446; cách gửi riêng buộc cắt ở điểm nối. Biên 452 vẫn sớm hơn cả hai biên Silver 545 và 558 của cụm liên quan.
- **Tách quá nhỏ:** `PILOT-003` có span Silver `[55, 213)` nhưng API tách thành `[55, 122)`, `[122, 130)` và `[130, 213)`. Cần cho phép gộp các đơn vị Hán liền kề.
- **Thiếu biên:** `PILOT-011` / `PILOT-012` có biên 731 bên trong câu Separate API `[710, 758)`. Chỉ cho phép gộp không xử lý được ca này; cần thêm phép thử tách lại hoặc biên ứng viên khác.
- **Lệch biên:** `PILOT-005` / `PILOT-006` có biên ChatGPT 324, DeepSeek 326 và Separate API 326. Sự trùng nhau không xác minh biên đúng về nghĩa.
- **Ngoài phạm vi:** Silver kết thúc ở 893; `[893, 905)` không thuộc vùng Việt 186–188 đã rà. Giữ toàn bộ đầu vào OCR, đánh dấu phần đuôi khi đánh giá và không tự gán `MISSING`.

Separate API sinh biên ứng viên. Tiêu chí chọn phương án là chất lượng dóng hàng; thỏa thuận biên Silver không đủ để kết luận khớp nghĩa hoặc ưu thế tổng quát.
