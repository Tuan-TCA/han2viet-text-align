# Separate API: `culture` so với `history` và Silver

Pilot Cap_01, Hán 001–002. Gọi ba lần với `culture`; dùng [kết quả history đã lưu](../separate_pilot_cap01/results.json). Đã xác nhận văn bản OCR, span, `ocr_id` và `punctuation_group` giống nhau trên từng payload; chỉ `genre` thay đổi. Hai lần chạy ở thời điểm khác nhau.

| Input | Ký tự nội dung giữ nguyên (cả hai) | Số câu, history → culture | Biên thêm / mất khi đổi sang culture | Thời gian history → culture (ms) |
|---|---:|---:|---:|---:|
| 001 | 445/445 | 15 → 15 | 0 / 0 | 960 → 1.778 |
| 002 | 459/459 | 9 → 9 | 0 / 0 | 426 → 469 |
| 001+002 | 904/904 | 29 → 29 | 0 / 0 | 1.012 → 2.002 |

Mọi response đều HTTP 200 / `000000`. Danh sách câu sau parse giống hệt giữa hai genre, kể cả dấu câu. Đếm ký tự bỏ dấu câu và khoảng trắng, giữ thứ tự. Thời gian chỉ là quan sát từng lượt, không đủ để kết luận genre nào nhanh hơn.

| Cách gửi (giống nhau ở hai genre) | Biên nội vùng Silver | Trùng biên đồng thuận | Trùng biên ChatGPT | Trùng biên DeepSeek | Câu vắt trang |
|---|---:|---:|---:|---:|---:|
| Từng trang | 23 | 8/9 | 8/11 | 9/11 | 0 |
| Ghép hai trang | 28 | 8/9 | 8/11 | 10/11 | 1 |

Điểm nối trang ở offset OCR raw `446`. Gửi từng trang tạo biên tại điểm nối do cách chia đầu vào; gửi ghép, cả hai genre có cùng một câu vắt trang ở `[372, 452)`. Nếu ghép trang, tìm thêm được một biên DeepSeek nhưng số biên đồng thuận trùng không đổi. Các tỷ lệ trên là số biên nằm bên trong phạm vi 12 cặp Silver được tìm thấy, không phải độ chính xác tách câu hay dóng hàng.

**Kết luận:** Trong ba đầu vào này, đổi `history` sang `culture` không làm thay đổi đầu ra tách câu quan sát được. Chưa có căn cứ ưu tiên `culture` dựa trên Silver pilot này.

Nguồn: [kết quả culture](results.json), [báo cáo culture](report.md), [kết quả history](../separate_pilot_cap01/results.json).
