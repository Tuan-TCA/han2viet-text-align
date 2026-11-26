# Chẩn đoán API ghép Hán–Việt

**Cách đã thử thành công:** giữ nguyên cụm 8 câu Hán và thu hẹp danh sách ứng viên Việt. Hai payload vốn lỗi đều trả kết quả khi thử từng nửa cửa sổ Việt. Giảm số câu Hán mà giữ nguyên cửa sổ Việt không khắc phục được hai ca này.

## Phương pháp

Script `04_dong_hang/diagnose_sentence_alignment.py` dựng lại 18 payload từ nhật ký chạy tự động, CSV Hán và Excel Việt. Trong 16 lượt gọi kiểm soát, tám lượt đầu phát lại request từng thành công (#12) và từng lỗi (#1), thay khoảng nghỉ và đổi thứ tự. Tám lượt sau thay đúng một phía của hai request từng lỗi (#1 và #2). Nhật ký lưu dấu băm payload, khoảng nghỉ thực tế, mã HTTP/JSON và thời gian phản hồi.

## Kết quả

- Cả 16 lượt đều trả HTTP 200: 8 thành công (`000000`), 8 lỗi ứng dụng (`000500`, mã bên trong `500001`). Không có HTTP 429 hoặc `Retry-After`.
- Payload #12 thành công 4/4; payload #1 nguyên bản lỗi 4/4. Trong từng nhóm có một lượt gửi sau khoảng nghỉ 0,5 giây; đổi thứ tự gọi và nghỉ khoảng 4 giây không đổi kết quả. Thử nghiệm tuần tự này không cho thấy dấu hiệu giới hạn tốc độ; không dùng kết quả để suy ra giới hạn tại tải cao hơn.

| Payload | Việt nguyên bản | Giữ 8 câu Hán, lấy nửa đầu/nửa sau cửa sổ Việt | Giảm còn 4 câu Hán, giữ nguyên Việt |
| --- | --- | --- | --- |
| #1 | 23 vế, 4.378 ký tự → lỗi | 11 vế, 1.597 ký tự → **OK**, 8 dòng trả về; 12 vế, 2.780 ký tự → **OK**, 6 dòng | Cả hai nửa Hán đều lỗi |
| #2 | 32 vế, 4.403 ký tự → lỗi | 16 vế, 2.723 ký tự → **OK**, 7 dòng; 16 vế, 1.679 ký tự → **OK**, 7 dòng | Cả hai nửa Hán đều lỗi |

Trong 18 payload ban đầu, trung vị số vế Việt là 32 ở cả hai nhóm. Trung vị độ dài Việt ở nhóm thành công là 5.157,5 ký tự, cao hơn 4.136,5 ký tự ở nhóm lỗi; có lượt thành công với 7.520 ký tự. Vì vậy chưa xác định được một giới hạn ký tự chung. Thu hẹp cửa sổ đồng thời thay độ dài, số vế và nội dung, nên chưa thể nói yếu tố nào gây lỗi bên trong server.

## Áp dụng

Ưu tiên lấy cửa sổ Việt nhỏ quanh mốc gần nhất; có thể bắt đầu ở khoảng **11–16 vế** cho các ca tương tự. Nếu nhận `000500`, chia **phía Việt** và giữ nguyên cụm Hán khi thử lại. Các mức này là phạm vi đã thử thành công, không phải hợp đồng giới hạn của API. Một phản hồi `000000` chỉ xác nhận API trả được đề xuất; vẫn cần kiểm tra nội dung trước khi gán nhãn.

Nhật ký: [`sentence_alignment_diagnostics.json`](../04_dong_hang/sentence_alignment_diagnostics.json).

```powershell
python -B -X utf8 04_dong_hang/diagnose_sentence_alignment.py --dry-run
python -B -X utf8 04_dong_hang/diagnose_sentence_alignment.py
```
