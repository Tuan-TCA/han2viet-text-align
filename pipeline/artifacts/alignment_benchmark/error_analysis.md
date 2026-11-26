# Phân tích lỗi Alignment API

Lỗi dưới đây là lỗi API, mapping hoặc khác biệt với ứng viên Silver, không phải nhãn lỗi ngữ nghĩa.

## Lỗi tiêu biểu

- **Chỉ số Việt lệch văn bản và thay đổi khoảng trắng trong số.** 23 dòng không truy được đều có vế Hán khớp chỉ số nhưng vế Việt không khớp chuỗi nguồn. Ví dụ direct S4, response `R0005` chứa `4. 349` trong khi nguồn ghi `4.349` và phạm vi Việt chỉ ra hai đoạn khác. Ở E02 `4×1`, chỉ số Việt `0..1` vượt một đoạn đã gửi, cùng dạng sai khác `4. 349`. Việc chèn khoảng trắng làm hỏng khớp chuỗi chính xác; kể cả chuẩn hóa dấu phân cách số, vẫn phải kiểm tra tính duy nhất và báo riêng chỉ số không hợp lệ.
- **Tách phía Việt.** 41 dòng ánh xạ được một phần đoạn Việt nhưng không được tính như một VI_ID đầy đủ; xem `VI_Char_Spans`. Cần dùng các span này nếu sau này gộp dự đoán, tránh cộng trùng hoặc suy nhầm rằng đã phủ hết đoạn.
- **Dóng ngoài phạm vi.** Cả bốn cấu hình direct thành công đều ghép 12 ký tự `[893, 905)` vào đoạn Việt cuối. Đây là phần không được Silver đánh giá; không tự gán `MISSING`, cũng không cộng vào điểm khớp.
- **Ranh giới không nhất quán giữa cửa sổ.** `Cap_01-VI-0187-003` nhận `[326,337)`, `[452,458)` hoặc `[458,531)`. Các đầu ra riêng có thể theo thứ tự nhưng tập ứng viên tổng vẫn xung đột.

## Chi tiết theo request

- `E01-S0` / `R0001`: api_error; xem request và raw response.
- `E01-S1`: unresolved_rows=1; unaligned_han=[[267, 326]]; unaligned_vi=['Cap_01-VI-0187-002']; out_of_scope_han_paired=12.
- `E01-S2`: unresolved_rows=1; unaligned_han=[[267, 326]]; unaligned_vi=['Cap_01-VI-0187-002']; out_of_scope_han_paired=12.
- `E01-S3`: unresolved_rows=1; unaligned_han=[[267, 326], [513, 531]]; unaligned_vi=['Cap_01-VI-0187-002']; out_of_scope_han_paired=12.
- `E01-S4`: unresolved_rows=1; unaligned_han=[[267, 326], [513, 531]]; unaligned_vi=['Cap_01-VI-0187-002']; out_of_scope_han_paired=12.
- `E02-1x1`: unresolved_rows=1; unaligned_han=[[213, 223]]; unaligned_vi=['Cap_01-VI-0187-002'].
- `E02-4x1`: unresolved_rows=1; unaligned_han=[[130, 267]]; unaligned_vi=['Cap_01-VI-0187-002'].
- `E02-4x2`: unaligned_han=[[638, 647]].
- `E02-4x4`: unresolved_rows=1; unaligned_han=[[231, 267]]; unaligned_vi=['Cap_01-VI-0187-001', 'Cap_01-VI-0187-002', 'Cap_01-VI-0187-003'].
- `E02-8x4`: unresolved_rows=1; unaligned_han=[[310, 326]]; unaligned_vi=['Cap_01-VI-0187-002'].
- `E03-h00-v00-s+0`: unresolved_rows=1; unaligned_han=[[55, 122]]; unaligned_vi=['Cap_01-VI-0186-003', 'Cap_01-VI-0187-001'].
- `E03-h02-v00-s-1`: unaligned_vi=['Cap_01-VI-0186-001'].
- `E03-h02-v00-s+0`: unaligned_vi=['Cap_01-VI-0186-001'].
- `E03-h02-v01-s+1`: unresolved_rows=1; unaligned_han=[[130, 213]]; unaligned_vi=['Cap_01-VI-0187-001', 'Cap_01-VI-0187-002'].
- `E03-h06-v01-s+0`: unresolved_rows=1; unaligned_han=[[267, 310]]; unaligned_vi=['Cap_01-VI-0187-001', 'Cap_01-VI-0187-002'].
- `E03-h08-v02-s+0`: unresolved_rows=1; unaligned_han=[[310, 326]]; unaligned_vi=['Cap_01-VI-0187-001', 'Cap_01-VI-0187-002'].
- `E03-h10-v03-s+0`: unresolved_rows=1; unaligned_han=[[310, 326]]; unaligned_vi=['Cap_01-VI-0187-001', 'Cap_01-VI-0187-002'].
- `E03-h14-v04-s-1`: unresolved_rows=1; unaligned_han=[[372, 452]]; unaligned_vi=['Cap_01-VI-0187-002'].
- `E03-h14-v06-s+1`: unaligned_vi=['Cap_01-VI-0187-004'].
- `E03-h18-v06-s+0`: unaligned_vi=['Cap_01-VI-0187-004'].
- `E03-h20-v07-s+0`: unaligned_han=[[678, 710]].
- `E04-negative-1`: unresolved_rows=2; unaligned_han=[[130, 223]]; unaligned_vi=['Cap_01-VI-0221-001', 'Cap_01-VI-0221-002'].
- `E05-E01`: unresolved_rows=1; unaligned_han=[[267, 326]]; unaligned_vi=['Cap_01-VI-0187-002']; out_of_scope_han_paired=12.
- `E05-E03`: unaligned_vi=['Cap_01-VI-0186-001'].
- `E06-E02-4x1-merge`: unresolved_rows=1; unaligned_han=[[130, 267]]; unaligned_vi=['Cap_01-VI-0187-002'].
- `E06-E02-4x1-split`: unaligned_han=[[130, 141], [231, 267]].
- `E06-E02-8x4-split`: unresolved_rows=1; unaligned_han=[[310, 326], [372, 396], [502, 531]]; unaligned_vi=['Cap_01-VI-0187-002'].
- `E06-E02-8x4-context`: unresolved_rows=1; unaligned_han=[[310, 326]]; unaligned_vi=['Cap_01-VI-0187-001', 'Cap_01-VI-0187-002'].
- `E06-E03-h00-v00-s+0-merge`: unresolved_rows=1; unaligned_han=[[0, 122]]; unaligned_vi=['Cap_01-VI-0186-001', 'Cap_01-VI-0186-002', 'Cap_01-VI-0186-003', 'Cap_01-VI-0187-001'].
- `E06-E03-h00-v00-s+0-split`: unresolved_rows=1; unaligned_han=[[47, 122]]; unaligned_vi=['Cap_01-VI-0186-003', 'Cap_01-VI-0187-001'].
- `E06-E03-h00-v00-s+0-context`: unresolved_rows=1; unaligned_han=[[55, 122]]; unaligned_vi=['Cap_01-VI-0186-003', 'Cap_01-VI-0187-001', 'Cap_01-VI-0187-002'].

## Sai khác biên direct với cả hai đề xuất Silver

- `E01-S1` / `PILOT-003`: dự đoán None; CG [55, 213]; DS [55, 213].
- `E01-S1` / `PILOT-004`: dự đoán None; CG [213, 267]; DS [213, 267].
- `E01-S1` / `PILOT-005`: dự đoán None; CG [267, 324]; DS [267, 326].
- `E01-S1` / `PILOT-006`: dự đoán None; CG [324, 337]; DS [326, 337].
- `E01-S1` / `PILOT-007`: dự đoán None; CG [337, 372]; DS [337, 372].
- `E01-S1` / `PILOT-008`: dự đoán [372, 531]; CG [372, 545]; DS [372, 558].
- `E01-S1` / `PILOT-009`: dự đoán [531, 647]; CG [545, 647]; DS [558, 647].
- `E01-S1` / `PILOT-011`: dự đoán None; CG [664, 731]; DS [664, 731].
- `E01-S1` / `PILOT-012`: dự đoán None; CG [731, 893]; DS [731, 893].
- `E01-S2` / `PILOT-003`: dự đoán None; CG [55, 213]; DS [55, 213].
- `E01-S2` / `PILOT-004`: dự đoán None; CG [213, 267]; DS [213, 267].
- `E01-S2` / `PILOT-005`: dự đoán None; CG [267, 324]; DS [267, 326].
- `E01-S2` / `PILOT-006`: dự đoán None; CG [324, 337]; DS [326, 337].
- `E01-S2` / `PILOT-007`: dự đoán None; CG [337, 372]; DS [337, 372].
- `E01-S2` / `PILOT-008`: dự đoán [372, 531]; CG [372, 545]; DS [372, 558].
- `E01-S2` / `PILOT-009`: dự đoán [531, 647]; CG [545, 647]; DS [558, 647].
- `E01-S2` / `PILOT-011`: dự đoán None; CG [664, 731]; DS [664, 731].
- `E01-S2` / `PILOT-012`: dự đoán None; CG [731, 893]; DS [731, 893].
- `E01-S3` / `PILOT-003`: dự đoán None; CG [55, 213]; DS [55, 213].
- `E01-S3` / `PILOT-004`: dự đoán None; CG [213, 267]; DS [213, 267].
- `E01-S3` / `PILOT-005`: dự đoán None; CG [267, 324]; DS [267, 326].
- `E01-S3` / `PILOT-006`: dự đoán None; CG [324, 337]; DS [326, 337].
- `E01-S3` / `PILOT-007`: dự đoán None; CG [337, 372]; DS [337, 372].
- `E01-S3` / `PILOT-008`: dự đoán [372, 513]; CG [372, 545]; DS [372, 558].
- `E01-S3` / `PILOT-009`: dự đoán [531, 647]; CG [545, 647]; DS [558, 647].
- `E01-S3` / `PILOT-011`: dự đoán None; CG [664, 731]; DS [664, 731].
- `E01-S3` / `PILOT-012`: dự đoán None; CG [731, 893]; DS [731, 893].
- `E01-S4` / `PILOT-003`: dự đoán None; CG [55, 213]; DS [55, 213].
- `E01-S4` / `PILOT-005`: dự đoán None; CG [267, 324]; DS [267, 326].
- `E01-S4` / `PILOT-008`: dự đoán [372, 513]; CG [372, 545]; DS [372, 558].
- `E01-S4` / `PILOT-009`: dự đoán [531, 647]; CG [545, 647]; DS [558, 647].
- `E01-S4` / `PILOT-011`: dự đoán [664, 727]; CG [664, 731]; DS [664, 731].
- `E01-S4` / `PILOT-012`: dự đoán None; CG [731, 893]; DS [731, 893].
