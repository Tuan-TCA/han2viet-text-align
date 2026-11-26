# Pilot Separate API — Cap_01, Hán 001–002

| Input | HTTP | Mã API | Thời gian (ms) | Ký tự nguồn → API* | Số câu | Trạng thái |
|---|---:|---|---:|---:|---:|---|
| 001 | 200 | 000000 | 1778 | 445 → 445 | 15 | ok |
| 002 | 200 | 000000 | 469 | 459 → 459 | 9 | ok |
| 001+002 | 200 | 000000 | 2002 | 904 → 904 | 29 | ok |

\* Không tính dấu câu và khoảng trắng; so chuỗi theo đúng thứ tự ký tự.

## Kiểm tra ký tự

- **001**: chuỗi ký tự giữ nguyên thứ tự.
- **002**: chuỗi ký tự giữ nguyên thứ tự.
- **001+002**: chuỗi ký tự giữ nguyên thứ tự.

## Ranh giới và câu vắt trang

Chỉ so các ranh giới nằm bên trong phạm vi Silver; bỏ biên cuối phạm vi. Offset được so trên luồng ký tự nội dung, để dấu câu và khoảng trắng không làm lệch vị trí. Đây là đối chiếu biên cụm dóng hàng Silver, không phải độ chính xác tách câu hay khớp nghĩa.

- **Từng trang:** 23 biên nội vùng; trùng Silver (agreed: 8/9, chatgpt: 8/11, deepseek: 9/11); 0 câu vắt trang; có biên tại điểm nối.
- **Ghép hai trang:** 28 biên nội vùng; trùng Silver (agreed: 8/9, chatgpt: 8/11, deepseek: 10/11); 1 câu vắt trang; không có biên tại điểm nối.
  - Span `[372, 452]`: 如有受照機并美底替限例谷宮該合首合附去繫間繁簡者，或減十三貫稽限二家次者咏六貫限八兩尚者侯三長限臺刃五侯司吏二貫鎮祿案詠八貨庫提欲與疾與孫該管歲十四貨庫陽長八貫五。

`agreed` = biên cuối được cả hai nguồn Silver chọn. Với cách tách riêng, biên tại điểm nối là do cách chia input.

**Nhận xét:** Ghép trang giữ được ngữ cảnh vắt trang trong pilot. Nên đưa cách này vào test Alignment API; chưa thể kết luận chất lượng dóng hàng chỉ từ biên câu.
