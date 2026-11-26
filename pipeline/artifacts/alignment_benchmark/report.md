# Benchmark Alignment API — Cap_01

**42 request thực tế**, 1 lần dùng cache. Trạng thái dừng: hoàn tất tập thử nghiệm khả thi.

Hán gửi nguyên `[0, 905)` trong direct; `[893, 905)` được theo dõi ngoài phạm vi Silver. Không gán OMISSION/ADDITION/MISSING tự động. S1–S4 thay biên trên chữ OCR gốc để cô lập tác động của segmentation.

| Thí nghiệm | Job có kết quả | Request thực | Trạng thái job | Lỗi theo request | Latency trung vị (ms) |
|---|---:|---:|---|---:|---:|
| E01 | 5 | 5 | {'api_error': 1, 'success': 4} | 0.2 | 10458 |
| E02 | 8 | 8 | {'success': 8} | 0.0 | 1420.5 |
| E03 | 17 | 16 | {'success': 17} | 0.0 | 2086.5 |
| E04 | 2 | 2 | {'success': 2} | 0.0 | 1646.5 |
| E05 | 2 | 2 | {'success': 2} | 0.0 | 3114.5 |
| E06 | 9 | 9 | {'success': 9} | 0.0 | 1970 |

## E01 — direct, cùng phạm vi đầu vào

| Cấu hình | Trạng thái | Cặp truy được | Exact CG / DS | Exact đồng thuận | IoU CG / DS |
|---|---|---:|---:|---:|---:|
| S0 | api_error | — | — / — | —/— | — / — |
| S1 | success | 10 | 3 / 3 | 3/8 | 0.39986545744468804 / 0.38517334074898035 |
| S2 | success | 10 | 3 / 3 | 3/8 | 0.39986545744468804 / 0.38517334074898035 |
| S3 | success | 10 | 3 / 3 | 3/8 | 0.3911949372134742 / 0.3771088246199481 |
| S4 | success | 13 | 5 / 6 | 5/8 | 0.7067326333481853 / 0.7054670335751719 |

## Diễn giải

- **Cách API trả kết quả:** request `han`/`vi` là hai chuỗi phân dòng; response dự kiến `data.result` chứa các nhóm chỉ số inclusive. Script đối chiếu văn bản nếu API trả văn bản, và cho phép ánh xạ substring duy nhất để phát hiện biên trong đơn vị.
- **Segmentation:** chiến lược dùng cho cửa sổ: S2 (chọn theo lỗi cấu trúc direct, không dựa vào Silver). Bảng direct so ảnh hưởng đến độ đồng thuận, chưa xác minh nghĩa.
- **Direct / sliding:** đối chiếu từng cặp ở `pair_comparison.csv`; tập tham chiếu từng cửa sổ có thể khác nhau. Các đề xuất sliding chưa được hợp nhất thành một dự đoán toàn pilot.
- **Đối chứng âm:** Việt 221 (thống kê Phú Châu/Tịch Tượng, có mốc Hán 027) và Việt 250 (lệ lính cắt cỏ voi/ngựa, có mốc Hán 052) nằm ngoài vùng Hán 001–002 theo nguồn độc lập Silver. Số cặp truy được: E04-negative-1=0 (success), E04-negative-2=1 (success).
- **N–M:** 28 lượt nhóm N–M truy được trên các job (có thể trùng do cửa sổ chồng lấn/lượt lặp). Đây là dấu hiệu hỗ trợ cấu trúc, không phải xác minh nghĩa.
- **Stability:** [{'comparison': ['E01-S2', 'E05-E01'], 'same_groups_spans': True, 'same_including_scores': True, 'row_counts': [11, 11]}, {'comparison': ['E03-h02-v00-s-1', 'E05-E03'], 'same_groups_spans': True, 'same_including_scores': True, 'row_counts': [3, 3]}].
- **Post-processing:** kiểm tra trùng ký tự, đảo thứ tự, thiếu phủ, biên nội đơn vị và cả đoạn ngoài phạm vi; xem `metrics.csv` và `error_analysis.md`.
- **Consensus / DP:** dữ liệu pilot chỉ đủ nhận diện lỗi cấu trúc và đưa ra giả thuyết; cần rà nghĩa và xác nhận trên vùng mới trước khi chọn kiến trúc.

Mẫu số exact/IoU: chỉ cặp Silver có đủ cả vế Việt và hai span tham chiếu trong input. Một dự đoán hợp lệ phải phủ đúng một VI_ID đầy đủ và duy nhất; thiếu/không duy nhất nhận IoU 0 theo quy ước đối chiếu, không phải nhãn sai nghĩa. Mẫu số direct thành công là 12.

## Kết luận từ lần chạy

1. **Cách API hoạt động.** Response thành công có `han_start`, `han_end`, `vi_start`, `vi_end`, hai chuỗi và `score`. API có thể chia nhỏ phía Việt: 41/142 dòng có vế Việt chỉ phủ một phần đoạn nguồn. Không có cặp ánh xạ được mà API cắt vào giữa một đơn vị Hán trong lần chạy này. Không quan sát header quota hoặc rate limit; điều đó không xác nhận quota không giới hạn.
2. **Tác dụng của Separate API.** Direct S0 (một dòng Hán) trả HTTP 200 nhưng mã ứng dụng `000500`, với `500001` lồng trong `message.debug_msg`. S1–S4 đều trả kết quả. Biên từ Separate giúp direct chạy được trên đầu vào pilot này; S0 lỗi chung, chưa đủ để kết luận định dạng không được hỗ trợ hoặc để định lượng cải thiện về nghĩa.
3. **Chọn baseline.** Direct **S4** tốt nhất theo hai tham chiếu: exact **5/12 CG, 6/12 DS**, IoU trung bình **0,707 / 0,705**; có 9/12 đoạn Việt ứng với một dự đoán duy nhất, so với 5/12 của các cấu hình S1–S3. Với 3 cặp dương tạm thời, S4 trùng cả hai biên ở `PILOT-002` và `PILOT-010`; `PILOT-006` chỉ trùng DeepSeek. S4 vẫn gán `[808, 905)` cho `PILOT-012` thay vì `[731, 893)` và kéo phần đuôi ngoài phạm vi vào cặp.
4. **Direct và sliding.** E03 dùng S2, có 18 lượt so đủ dữ liệu cho 10 cặp Silver khác nhau. Trên chính 18 lượt đó, sliding khớp 7/18 CG và 8/18 DS; tra lại direct S2 theo cùng ID cho 7/18 và 7/18. Các lượt lặp ID không độc lập, 4 ID có span Hán khác nhau giữa các cửa sổ, và chưa thử sliding S4 trong lần chạy này. Chưa thấy lý do chuyển mặc định sang sliding. E02 có 3 lượt đủ vế tham chiếu, không có exact; chưa dùng mẫu nhỏ này để xếp hạng kích thước cửa sổ.
5. **Ép dóng hàng.** Cả hai đối chứng âm trả nhóm. Với đối chứng Việt 250, API dóng Hán `[664, 710)` với cả hai đoạn về lính cắt cỏ voi/ngựa, score 0,146; đây là cặp truy được nhưng không tương ứng. Đối chứng Việt 221 không có cặp truy được, do chỉ số/văn bản Việt không ánh xạ chính xác, chứ API không từ chối. Không dùng `SUCCESS` hay `score` làm bộ xác minh nghĩa.
6. **N–M.** API trả nhóm nhiều-nhiều có thể truy nguồn (ví dụ 3 nhóm ở direct S2), gồm cả một nhóm ở đối chứng âm. Hiệu quả về nghĩa của loại liên kết này chưa được xác nhận.
7. **Hiệu chỉnh theo lỗi.** Thêm biên yếu cho cửa sổ E02 `8×4` nâng exact từ 0/2 lên 1/2 CG và 2/2 DS. Trái lại, thêm biên ở cửa sổ E03 đầu làm giảm từ 2/2 cả hai xuống 0/2; mở ngữ cảnh ở cửa sổ đó vẫn giữ 2/2. Ưu tiên phát hiện chỉ số lệch, thay đổi văn bản trả về, xung đột giữa cửa sổ và phần dồn sai vào cặp cuối. Không áp dụng gộp hoặc tách thêm đồng loạt.
8. **Quyết định triển khai.** Dùng direct S4 làm baseline đối chiếu trên pilot kế tiếp, với kiểm tra ánh xạ nghiêm ngặt. Trước khi chọn Consensus/DP, cần rà khớp nghĩa trên mẫu mới và có thêm ca cửa sổ cho thấy lợi ích rõ ràng.

Tái lập: `python -B pipeline/scripts/benchmark_alignment_api.py --dry-run`. Chạy mới dùng `--output` trỏ đến thư mục chưa tồn tại; dùng `--resume` để đọc lại log/cache của một lượt đang dang dở. Không có trần request mặc định; `--request-budget` là tuỳ chọn.
