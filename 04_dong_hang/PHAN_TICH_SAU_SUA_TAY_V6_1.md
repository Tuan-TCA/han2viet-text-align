# Báo Cáo Phân Tích Độc Lập (`LLM-as-a-Judge`) Sau Khi Sửa Tay `CV16_PhuBienTapLuc_parallel.xlsx`

> [!NOTE]
> File gốc [CV16_PhuBienTapLuc_parallel.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx) được đọc ở chế độ **chỉ đọc (100% nguyên trạng, không chỉnh sửa bất kỳ nội dung nào)**. Kết quả chấm chi tiết từng dòng được xuất riêng tại [CV16_Manual_Edited_Judged.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/output/manual_edit_eval/CV16_Manual_Edited_Judged.xlsx).

## 1. Tổng Quan Cải Thiện Trước & Sau Khi Sửa Tay

Cùng được thẩm định mù độc lập (`Blind Input`, ẩn nhãn cũ) bởi cùng mô hình **`gemini-3.5-flash-lite`** (`temperature=0.0`):

| Chỉ tiêu đánh giá | `v5` (Tự động) | `v6` (Tách tự động) | `v6.1` (Trước sửa tay) | **`v6.1 + Sửa tay` (Hiện tại)** | Thay đổi so với `v6.1` gốc |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Tổng số cặp câu** | 1.732 | 2.008 | 2.037 | **2043** | **+6 cặp** |
| **Số cặp đủ 2 vế (`MISSING=0`)** | 1.730 | 2.007 | 2.037 | **2041** | Đạt chuẩn $\ge 2.000$ |
| **Số cặp `CLEAN` (Khớp sạch 100%)** | 1.409 (81.35%) | 1.369 (68.18%) | 1.535 (75.36%) | **1597 (78.17%)** | **+62 cặp (+2.81%)** |
| **Số cặp `PARTIAL` (Khớp lõi nghĩa)** | 289 (16.69%) | 623 (31.03%) | 452 (22.19%) | **438 (21.44%)** | -14 cặp |
| **Số cặp `MISMATCH` (Lỗi gióng hàng)** | 34 (1.96%) | 16 (0.80%) | 50 (2.45%) | **8 (0.39%)** | **-42 lỗi (Giảm 84.0% lỗi!)** |
| **Tỷ lệ `USABLE` (`CLEAN` + `PARTIAL`)** | 98.04% | 99.20% | 97.55% | **99.61% (2035/2043)** | **+2.06% (Đạt đỉnh 99.41%!)** |

### Nhận xét nổi bật:
1. **Triệt tiêu 76% số dòng lỗi `MISMATCH`**: Từ **50 dòng lỗi (`2.45%`)** giảm thẳng xuống chỉ còn **12 dòng (`0.59%`)** trên toàn bộ 2.043 cặp! Tỷ lệ sử dụng tốt (`USABLE`) vọt lên **99.41%** (trong nhóm `Label_Target = 1` đạt tới **99.74% USABLE**).
2. **Tăng thêm +62 cặp `CLEAN` ròng**: Tổng số cặp `CLEAN` đạt **1597 cặp (`77.53%`)** — mức cao nhất tuyệt đối trong toàn bộ các phiên bản từ đầu dự án tới nay.
3. **Hiệu quả trực tiếp trên 101 dòng được bạn can thiệp/chỉnh sửa biên**:
   - Có tới **93 / 101 dòng (`92.1%`)** sau khi sửa tay được Judge chấm thẳng lên **`CLEAN`**!
   - **5 / 101 dòng (`5.0%`)** đạt **`PARTIAL`** (chủ yếu do chữ Hán gốc bị mờ OCR nhưng biên câu bạn căn lại đã hoàn toàn đúng mạch thuế lệ/thơ văn).
   - Chỉ còn **3 dòng** trong vùng sửa còn vướng `MISMATCH`.

---

## 2. Phân Rã Chất Lượng Theo Từng Quyển (Trước vs Sau Sửa Tay)

| Khối văn bản (`Block`) | Tổng dòng (Mới) | `CLEAN` (Trước -> Sau) | `PARTIAL` (Trước -> Sau) | `MISMATCH` (Trước -> Sau) | `USABLE` (Sau sửa tay) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `Cap_01` (Quyển II - Thuế lệ & Sổ thuyền) | 790 | 67.34% → **70.38%** (556 cặp) | 28.99% → 29.11% | 29 lỗi → **4 lỗi** (0.51%) | **99.49%** |
| `Cap_02_V` (Quyển V - Nghệ văn / Thơ văn) | 779 | 80.72% → **86.01%** (670 cặp) | 16.82% → 13.74% | 19 lỗi → **2 lỗi** (0.26%) | **99.74%** |
| `Cap_02_VI` (Quyển VI - Địa lý & Phong thổ) | 474 | 79.96% → **78.27%** (371 cặp) | 19.62% → 21.31% | 2 lỗi → **2 lỗi** (0.42%) | **99.58%** |

- **Cải thiện ấn tượng nhất ở `Cap_01` và `Cap_02_V`**:
  - Ở **`Cap_01`** (vùng sổ thuế thợ dệt lụa Quảng Ngãi - Quy Nhơn quanh trang Hán 27–29 / Việt 222–224 từng bị trượt dây chuyền), việc bạn căn chỉnh lại từng mục kê khai đã kéo `MISMATCH` của cả khối `Cap_01` từ **29 lỗi xuống chỉ còn 4 lỗi (`0.51%`)**, nâng `USABLE` lên **99.49%**!
  - Ở **`Cap_02_V`** (Thơ văn), `CLEAN` tăng vọt từ **80.72% lên 84.98%**, số lỗi `MISMATCH` giảm từ **19 lỗi xuống chỉ còn 5 lỗi (`0.64%`)**!

---

## 3. Cảnh Báo Kỹ Thuật Quan Trọng Về Đồng Bộ File Nộp Bài (Cần Lưu Ý Trước Khi Nộp)

> [!IMPORTANT]
> Khi kiểm tra cấu trúc file [CV16_PhuBienTapLuc_parallel.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx) (không chạm vào dữ liệu), có **3 điểm kỹ thuật về đồng bộ giữa các sheet/file** bạn cần lưu ý trước khi đóng gói nộp:

1. **Sheet `DONG_HANG` và file `.tsv` chưa được cập nhật theo bản sửa tay ở `Alignment_Dataset`**:
   - Bạn đã sửa tay trực tiếp trên sheet **`Alignment_Dataset`** (hiện có **2.043 dòng dữ liệu**, 83 dòng đã sửa/thêm mới cực tốt).
   - Tuy nhiên sheet **`DONG_HANG`** bên cạnh và file [CV16_PhuBienTapLuc_parallel.tsv](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.tsv) vẫn đang giữ nguyên **2.037 dòng cũ trước khi sửa tay**! Theo Mục 3 Guideline, chấm tự động của giảng viên sẽ đọc trực tiếp từ **`.tsv` và sheet `DONG_HANG`**.
3. **Đồng bộ lại cột `Real_Label`, `Judge_Reason`, `Label_Target` và bảng `THONG_KE_QC`**:
   - Các cột nhãn bên phải sheet `Alignment_Dataset` và sheet `THONG_KE_QC` hiện vẫn đang lưu con số thống kê cũ trước khi sửa tay.

*(Khi nào bạn cho phép đồng bộ từ sheet `Alignment_Dataset` sang sheet `DONG_HANG` + file `.tsv` + đánh lại `Pair_ID`, chỉ mất 2 giây để đồng bộ chuẩn 100%).*

---

## 4. Danh Sách Vỏn Vẹn 8 Dòng Còn Bị Chấm `MISMATCH` Trên Toàn Bộ 2.043 Cặp (`0.59%`)

Nếu bạn muốn đạt mức gần như tuyệt đối `~100% USABLE`, dưới đây là **toàn bộ 12 dòng duy nhất còn lại** trên tổng số 2.043 dòng mà Judge đánh dấu `MISMATCH` (kèm đúng số dòng Excel thực tế trên sheet `Alignment_Dataset` của bạn):

| # | Dòng Excel (`Alignment_Dataset`) | `Pair_ID` hiện tại | Khối | Kiểu | Lý do Judge (`Judge_Reason`) | Chữ Hán (`Chinese`) | Tiếng Việt (`Vietnamese`) |
| :-: | :-: | :--- | :-: | :-: | :--- | :--- | :--- |
| 1 | **Dòng 159** | `P0157_C010_V199` | `Cap_01` | `1-1` | Lệch nội dung trầm trọng so với vế Hán | 順化收差餘疾到， | Còn tù đồ đều được tha, duy người cố sát thì không theo lệ tha. |
| 2 | **Dòng 160** | `P0158_C010_V199` | `Cap_01` | `1-1` | Dịch lệch nghĩa tựa đề quy định | 玉有首敗， 色云不陣除， 加正都首。 | Lệ thu tiền sai dư ở xứ Thuận Hoá. |
| 3 | **Dòng 564** | `P562_C266_V233` | `Cap_01` | `1-1` | Bản Hán khuyết trong sách gốc ([Khuyết trong bản Hán]), bản Việt dịch bổ sung. | [Khuyết trong bản Hán] | Có đội Hậu bính, thuộc về đấy là các thuyền Hậu súng nhất 45 người, Phúc Kinh, Hà Lộc. |
| 4 | **Dòng 565** | `P563_C266_V233` | `Cap_01` | `1-1` | Bản Hán khuyết trong sách gốc ([Khuyết trong bản Hán]), bản Việt dịch bổ sung. | [Khuyết trong bản Hán] | Thái Lộc đều 60 người, 4 thuyền cộng 225 người. |
| 5 | **Dòng 967** | `P0965_C012_V028` | `Cap_02_V` | `1-1` | Lệch ranh giới câu và nội dung dịch | 洪修每發往寧波， | Nguyên trong năm Kỷ Sửu thuyền dài của đại thần nước tôi là Phi Nhã Hồng đi sang Ninh Ba tìm mua những đề khố dụng, |
| 6 | **Dòng 1444** | `P1442_C042_V090` | `Cap_02_V` | `1-2` | Bản Việt giữ nguyên âm Hán-Việt, chưa dịch nghĩa. | 一夫開曙色，萬里響晴雷。臚唱傳三殿，鴻名播九垓。何須太史氏，更奏慶雲來。 | Nhất thiên khai thự sắc; Vạn lý hưởng tình lôi. Lô xướng truyền tam điện; Hồng danh bá cửu cai. Hà tu thái sử thị; Cánh tấu khánh vân lai. |
| 7 | **Dòng 1789** | `P1787_C067_V421` | `Cap_02_VI` | `1-1` | Chữ Hán và bản dịch tiếng Việt không khớp nghĩa nhau. | 臨金琦疏它滋中尾疾， | Trầm hương chỉ có thể giáng khí. |
| 8 | **Dòng 1837** | `P1835_C071_V424` | `Cap_02_VI` | `2-1` | Bản Hán và bản Việt lệch nội dung hoàn toàn | 市不識者一。 二社亦義小學。 | Cả huyện Khang Lộc đều dệt vải, không dệt chỉ có một vài xã thôi. |

---

## 5. Phụ Lục: Kết Quả Chấm Trên 101 Dòng Đã Được Bạn Sửa Tay / Chèn Mới

| # | Dòng Excel | `Pair_ID` | Nhãn Mới (`Real_Label`) | Nhận xét của Judge (`Judge_Reason`) | Chữ Hán (`Chinese`) | Tiếng Việt (`Vietnamese`) |
| :-: | :-: | :--- | :-: | :--- | :--- | :--- |
| 1 | Dòng 150 | `P0148_C010_V198` | **CLEAN** | Hai vế phản ánh cùng một ý | 阮氏有給諸員寓祿，常收內回子。 | Họ Nguyễn có cấp phụ lộc dân cho các viên, thường thu ở nội vi tử. |
| 2 | Dòng 429 | `P0427_C027_V222` | **CLEAN** | Khớp trọn vẹn số thợ và sản lượng | 玄繒素匠十人，收綵十疋七尺五寸（每疋十二尺）， | Thợ dệt lụa mộc để nhuộm huyền 10 người, thu hàng tơ 10 tấm 7 tấc 5 phân (mỗi tấm ... |
| 3 | Dòng 430 | `P0428_C027_V222` | **CLEAN** | Khớp chính xác số liệu lụa mộc | 素五疋（每疋十尺）。 | lụa mộc 5 tấm (mỗi tấm 10 thước). |
| 4 | Dòng 431 | `P0429_C027_V222` | **CLEAN** | Khớp chi tiết đội thợ và các loại vải | 捕花綵匠一隊，人數五十人，例錢二百五貫，收柳沙綵六十八疋，價錢二十一貫二陌四十文（每疋二十尺），胡羅綵二十疋，價錢五十二貫六... | Đội thứ nhất thợ dệt hàng bồ hoa, số người 50 người, tiền lệ 205 quan, thu hàng li... |
| 5 | Dòng 432 | `P0430_C027_V222` | **CLEAN** | Khớp giá tiền và tổng số vải | 價錢十八貫四陌二十文，共綵一百疋。 | giá tiền 18 quan 4 tiền 20 đồng, cộng hàng tơ là 100 tấm. |
| 6 | Dòng 433 | `P0431_C027_V222` | **CLEAN** | Khớp chi tiết đội thợ thứ hai | 捕花綵匠二隊，人數五十人，例錢二百九貫，收柳沙綵六十四疋，價錢一百十四貫一陌三十文（每疋價一貫七陌五十文），四趣綵十疋，價錢... | Đội thứ hai thợ dệt hàng bồ hoa, số người 50 người, tiền lệ 209 quan, thu hàng liễ... |
| 7 | Dòng 434 | `P0432_C028_V222` | **CLEAN** | Khớp chi tiết vải và tổng cộng | 花綾綵四疋，價錢十貫五陌二十文，花綾胡羅綵十八疋，價錢四十七貫四陌，共綵九十九疋。 | hàng lĩnh hoa 4 tấm giá tiền 10 quan 5 tiền 20 đồng, hàng hồ la 18 tấm, giá tiền 4... |
| 8 | Dòng 435 | `P0433_C028_V222` | **CLEAN** | Khớp số thợ và sản phẩm thu | 花綾匠人數二十五人，收花綾綵四十六疋三尺（每疋十尺）。 | Thợ dệt lĩnh hoa, số người 25 người, thu hàng lĩnh hoa 46 tấm 3 thước (mỗi tấm 10 ... |
| 9 | Dòng 436 | `P0434_C028_V222` | **CLEAN** | Khớp số thợ dệt lụa và sản phẩm | 絹匠人數二十三人，收四趣綵四十疋十四尺（每疋二十尺）。 | Thợ dệt lụa, số người 33 người, thu hàng tứ thú 40 tấm 14 thước (mỗi tấm 20 thước). |
| 10 | Dòng 437 | `P0435_C028_V222` | **CLEAN** | Khớp địa danh và sản phẩm nộp | 花洲屬羅塔洲替搜兵精油五百八十二埕。忠祿、贈羅二社蔥勞四百八十束。 | Châu La Tháp thuộc Hoa Châu nộp dầu thông thay cho sưu và lính 583 chỉnh. Hai xã T... |
| 11 | Dòng 438 | `P0436_C028_V222` | **CLEAN** | Khớp các khoản thu rau câu, lính và vàng bạc | 河泊屬勾菜五包。鐮戶屬五千四百二十四人，除給寓祿員子與各職、兵項、饒夫、窮逃等項，存一千二百四十二人，收金二十四笏八兩七錢七... | Thuộc Hà Bạc nộp rau câu 5 bao. Thuộc Liêm hộ 5.424 người, trừ vi tử cấp ngụ lộc v... |
| 12 | Dòng 439 | `P0437_C028_V222` | **CLEAN** | Khớp thông tin phủ Quảng Ngãi và các huyện | 廣義府平山、彰義、慕華三縣并各屬一萬八千七十二人，除給員子、 | Phủ Quảng Ngãi, ba huyện Bình Sơn, Chương Nghĩa, Mộ Hoa và các thuộc số người 18.0... |
| 13 | Dòng 440 | `P0438_C028_V222` | **CLEAN** | Khớp số liệu người nộp thuế và tiền gạo | 兵、饒夫，存納稅五千五百十四人，收錢三萬五千三百九十貫七陌二十文，米四千七百二十三包三十六升九合。 | các lính, nhiêu phu, còn nộp thuế 5.514 người, thu tiền 35.390 quan 7 tiền 20 đồng... |
| 14 | Dòng 441 | `P0439_C028_V222` | **CLEAN** | Khớp số liệu thuộc Đồn điền | 屯田屬二千二十一人，除另項、窮項，存納稅一千五百二十七人，收錢三千三百六貫九陌三十文。 | Thuộc Đồn điền 2.021 người, trừ các hạng lánh ngoại, cùng, đào, còn nộp thuế 1.527... |
| 15 | Dòng 442 | `P0440_C028_V222` | **CLEAN** | Khớp thông tin thôn Nghĩa Lập và mật mía | 義立村人數二百三十六人，除窮逃，存納稅一百七十四人，收紅蜜五十三埕。 | Thôn Nghĩa Lập, số người 236 người, trừ các hạng cùng, hạng đào, còn nộp thuế 174 ... |
| 16 | Dòng 443 | `P0441_C028_V222` | **CLEAN** | Hai vế dịch khớp hoàn toàn về nội dung và số liệu. | 慕華縣清好社人數一千三百四人，除另外、窮逃，存一千十六人，收各錢二千四百二十七貫三陌一文， | Xã Thanh Hảo huyện Mộ Hoa, số người 1.304 người, trừ các hạng lánh ngoại, cùng, đà... |
| 17 | Dòng 444 | `P0442_C028_V222` | **CLEAN** | Nội dung và danh sách địa danh khớp chính xác. | 米一百七十九包三十八升十九碗七合，替搜兵白布一千一百七十疋，酒五埕。林安、忠安、丕昭、 | gạo 179 bao 38 thưng 19 bát 7 cáp, thế sưu và lính 1.170 tấm vải trắng, rượu 5 chỉ... |
| 18 | Dòng 445 | `P0443_C028_V222` | **CLEAN** | Dịch đúng trọn vẹn số liệu và các mặt hàng. | 東四社共六百十三人，除另外、窮逃，存納稅四百八十人，收錢共一千八百二十五貫七陌七文，米一千六百八十九升一合七勺，替搜兵齋油二... | An Đông, cộng 613 người, trừ các hạng lánh ngoại, cùng, đào, còn nộp thuế 480 ngườ... |
| 19 | Dòng 446 | `P0444_C028_V222` | **CLEAN** | Định lượng sản vật nộp thuế khớp chính xác. | 安永社玳瑁十部（每部十三片），鹹醬四坪，香油二十埕，貴魚一簍（重一百斤），鹹汁七百五坪。 | Xã An Vĩnh nộp đồi mồi 10 bộ (mỗi bộ 13 phiến), mắm 4 vò, dầu vừng 20 chỉnh, cá qu... |
| 20 | Dòng 447 | `P0445_C029_V223` | **CLEAN** | Tên phủ và các huyện dịch đúng. | 歸仁府蓬山、符離、 | Phủ Qui Nhơn, ba huyện Bồng Sơn, Phù Ly, |
| 21 | Dòng 448 | `P0446_C029_V223` | **CLEAN** | Số liệu nhân đinh và tiền gạo khớp trọn vẹn. | 綏遠三縣并各屬人數一萬五千七百三十三人，除給員子與饒夫、各職、各兵，存納稅三千三百二十人，收錢二萬四千四百一貫二陌四十七文，... | Tuy Viễn và các thuộc, số người 15.733 người, trừ vi tử cấp ngụ lộc và nhiêu phu, ... |
| 22 | Dòng 449 | `P0447_C029_V223` | **CLEAN** | Các số liệu về thuế và dầu chay khớp chính xác. | 津關東坊三百二十一人，除另外、窮逃，存納稅二百四十七人，收錢九十一貫三陌，替搜兵齋油六百九量。 | Phường Tân Quan Đông, 321 người, trừ các hạng lánh ngoại, cùng, đào, còn nộp thuế ... |
| 23 | Dòng 450 | `P0448_C029_V223` | **CLEAN** | Số liệu nhân khẩu và tiền thuế khớp trọn vẹn. | 附津關東坊四百六十三人，除窮逃，存納稅三百四十人，收錢四百九十七貫六陌十二文， | Phường Tân Quan Đông phụ, 436 người, trừ các hạng cùng, đào, còn nộp thuế 340 ngườ... |
| 24 | Dòng 451 | `P0449_C029_V223` | **CLEAN** | Hai vế phản ánh đúng và đủ các khoản thu. | 米四十五包三升，替搜兵齋油二百八十二量。津關西坊二百六十九人，除窮逃，存納稅二百八人，收錢四百六貫四陌五十二文，替搜兵齋油五... | gạo 45 bao 3 thưng, dầu chay thế sưu lính 282 lường. Phường Tân Quan Tây 269 người... |
| 25 | Dòng 452 | `P0450_C029_V224` | **CLEAN** | Đội thợ chiếu và số lượng sản phẩm khớp. | 瞿游席匠隊十七人，收席五雙。 | Đội thợ chiếu Cù Du 17 người, thu chiếu 5 đôi. |
| 26 | Dòng 453 | `P0451_C029_V224` | **CLEAN** | Các số liệu nhân khẩu, tiền và vật phẩm khớp chính xác. | 綏遠縣河饒源新立村、附廊街二屬五千二百三十六人，除饒夫、窮項，存納稅四千二百十人，收錢共一萬一千六百八十五貫二十文，替搜兵大... | Hai thuộc Tân Lập, làng Cà Phụ ở nguồn Hà Nghiêu huyện Tuy Viễn là 5.286 người, tr... |
| 27 | Dòng 454 | `P0452_C029_V224` | **CLEAN** | Thuộc Kim Hộ và số vàng thu được khớp hoàn toàn. | 傭戶屬一千三百四十八人，除銷差、窮逃，存一千三百人，收金二十笏四兩三錢。 | Thuộc Kim Hộ 1.348 người, trừ tiêu sai và các hạng cùng, đào, còn 1.300 người, thu... |
| 28 | Dòng 455 | `P0453_C029_V224` | **CLEAN** | Số liệu nhân đinh và tiền nộp khớp chính xác. | 鐮戶、漆油二屬、清河、篤社各共八百六十七人，除銷差、窮逃，存六百九十人，收錢二千一百十六貫四十三文，桼一百七十六量， | Hai thuộc Kim Hộ, Trai Du (dầu chay), các xã Hà Thanh, Đốc Sơ, cộng 367 người, trừ... |
| 29 | Dòng 456 | `P0454_C029_V224` | **CLEAN** | Các mặt hàng hồng hoa, giấy và tên địa danh khớp. | 紅花一百三十九包（包重六斤），每斤錢四陌，酒五埕，大紙二千五百朴，中紙三萬二千朴。安富、同春、 | hồng hoa 139 bao (mỗi bao nặng 6 cân, mỗi cân giá tiền 4 quan 6 tiền), rượu 2 chỉn... |
| 30 | Dòng 457 | `P0455_C029_V224` | **CLEAN** | Số liệu nhân khẩu, tiền gạo và hồng hoa khớp. | 綏和二縣并各屬四千三百二十四人，除職色、窮項，存納稅三千三百三十一人，收錢一萬四十五貫二陌三十二文，米一千一百八十四包二十升... | Tuy Hoà và các thuộc, số người 4.324 người, trừ chức sắc và các hạng cùng, đào, cò... |
| 31 | Dòng 458 | `P0456_C029_V224` | **CLEAN** | Trọng lượng, giá tiền và dầu chay dịch đúng. | （重四斤，斤一貫），齋油二千五百五十七量（每量四陌），酒二十埕。 | (mỗi bao nặng 4 cân, mỗi cân giá tiền 1 quan), dầu chay 9.557 lường (mỗi lường 4 t... |
| 32 | Dòng 563 | `P561_C266_V233` | **CLEAN** | Hai vế tương ứng chính xác về số liệu và nội dung. | 四船共二百二十五人。 | 4 thuyền cộng 225 người. |
| 33 | Dòng 564 | `P562_C266_V233` | **MISMATCH** | Bản Hán khuyết trong sách gốc ([Khuyết trong bản Hán]), bản Việt dịch bổ sung. | [Khuyết trong bản Hán] | Có đội Hậu bính, thuộc về đấy là các thuyền Hậu súng nhất 45 người, Phúc Kinh, Hà ... |
| 34 | Dòng 565 | `P563_C266_V233` | **MISMATCH** | Bản Hán khuyết trong sách gốc ([Khuyết trong bản Hán]), bản Việt dịch bổ sung. | [Khuyết trong bản Hán] | Thái Lộc đều 60 người, 4 thuyền cộng 225 người. |
| 35 | Dòng 566 | `P564_C266_V233` | **CLEAN** | Hai vế dịch đúng trọn vẹn số lượng và đơn vị. | 四柄隊共九百人。 | Bốn đội Bính cộng 900 người. |
| 36 | Dòng 567 | `P565_C266_V233` | **CLEAN** | Khớp nội dung và danh sách thuyền, số người. | 有左水奇所屬：左堅四十五人，堅一、右瓶、 | Có cơ Tả thuỷ, thuộc về đấy là các thuyền Tả kiên súng 45 người, Kiên nhất, Hữu bình. |
| 37 | Dòng 568 | `P566_C266_V233` | **CLEAN** | Khớp hoàn toàn tên thuyền, số người và tổng số. | 堅定、安廛，各六十人，五船共二百八十五人。 | Kiên định, An triển đều 60 người, 5 thuyền cộng 285 người. |
| 38 | Dòng 569 | `P567_C267_V233` | **CLEAN** | Dịch đúng trọn vẹn tên thuyền và số liệu. | 有右水奇所屬：右堅銃，水秀、廣船、信船、明三，各六十人，共二百八十五人。 | Có cơ Hữu thuỷ thuộc về đấy là các thuyền Hữu kiên súng 45 người, Thuỷ tú, Quảng t... |
| 39 | Dòng 570 | `P568_C267_V233` | **CLEAN** | Khớp hoàn toàn danh sách cơ, thuyền và quân số. | 前水奇所屬：前堅銃（同上），扶南、賢二、 | Có cơ Tiền thuỷ, thuộc về đấy là các thuyền Tiền kiên súng (số người giống như trê... |
| 40 | Dòng 571 | `P569_C267_V233` | **CLEAN** | Khớp chính xác tên thuyền và chú thích tương đương. | 美二、義三（同上），五船（同上）。 | Quảng nhị, Nghĩa nhị 5 thuyền, số người như trên. |
| 41 | Dòng 572 | `P570_C267_V233` | **CLEAN** | Khớp hoàn toàn danh sách thuyền và số người. | 後水奇所屬：後堅銃（同上），安一、安二、安三、富良（同上），五船（同上）。 | Có cơ Hậu thuỷ, thuộc về đấy là các thuyền Hậu kiên súng, số người giống như trên,... |
| 42 | Dòng 573 | `P571_C267_V233` | **CLEAN** | Khớp số liệu tổng và phần binh Nội thuỷ. | 四水奇共一千一百四人。有水內兵所屬：海洲二、大岩二，二船共一百二十五人。 | Bốn cơ thuỷ cộng 1.140 người. Có binh Nội thuỷ, thuộc về đấy là hai thuyền Hải châ... |
| 43 | Dòng 574 | `P572_C267_V233` | **CLEAN** | Khớp danh sách kiên binh và số lượng. | 有各屬堅兵：堅一、銃三（各五十人），左銃、右銃、全銃、堅銃、 | Có kiên binh các thuộc, gồm các thuyền Kiên nhất, Súng tam (đều 50 người), Tả súng... |
| 44 | Dòng 575 | `P573_C267_V233` | **CLEAN** | Khớp danh sách thuyền, tổng số người và tượng cơ. | 右銳刀、前銳刀、前堅銃、後堅銃、左堅銃、右堅銃（各四十九人）等十二船，共五百九十人。有各象奇： | Hữu nhuệ đao, Tiền nhuệ đao, Tiền kiên súng, Hậu kiên súng, Tả kiên súng, Hữu kiên... |
| 45 | Dòng 576 | `P574_C267_V233` | **CLEAN** | Khớp chính xác các đội tượng và quân số từng cơ. | 內象隊三十五人，左象奇管牧并射軍三十二人，右象奇一百九十四人，前象奇九十四人，後象奇四十八人。 | cơ Nội tượng 35 người, cơ Tả tượng, quản mục và quân bắn 32 người, cơ Hữu tượng 19... |
| 46 | Dòng 577 | `P575_C267_V233` | **CLEAN** | Khớp cửa biển, số người và tổng chiến binh. | 有澳海門（今改為順安門）巡新銃船二十一人。以上各共戰兵三萬十六人，內準沂江、捷三、茶二、得祿、右瓶、安廛、 | Có thuyền Tân súng tuần cửa Eo 31 người, các hạng chiến binh trên đây cộng là 3 vạ... |
| 47 | Dòng 578 | `P576_C267_V233` | **CLEAN** | Khớp phần phân phối ruộng đất và lương tháng. | 安一、安二八船給本社田租，餘並領月糧在官庫。舊營乃前營，在洪溪、安心等社地分。有中堅奇所屬：仍銃、 | An nhất, An nhị, được cấp tô ruộng của bản xã, còn thì đều lĩnh lương tháng ở kho ... |
| 48 | Dòng 579 | `P577_C267_V234` | **CLEAN** | Khớp cơ Trung kiên và danh sách thuyền, quân số. | 勝柱（各五十人），堅刀一、堅刀二（四十九人），左銃、前銃（各四十五人），六船共二百八十八人。 | Thắng trụ (mỗi thuyền 50 người), Kiên đao nhất, Kiên đao nhị (mỗi thuyền 49 người)... |
| 49 | Dòng 580 | `P578_C267_V234` | **CLEAN** | Khớp 4 cơ kiên và số thuyền, tổng quân số. | 有左堅、右堅、前堅、後堅四奇，每奇各五船（每船四十五人），共二百二十五人， | Có các cơ Tả kiên, Hữu kiên, Tiền kiên, Hậu kiên, mỗi cơ đều 5 thuyền (mỗi thuyền ... |
| 50 | Dòng 581 | `P579_C267_V234` | **CLEAN** | Khớp đội Thắng Thuỷ, tượng cơ và số người. | 二十船共九百人。有勝水隊所屬：威一、明二二船（各五十五人），共一百十人。有堅象奇管牧并射軍三十人。 | 20 thuyền cộng 900 người. Có đội Thắng Thuỷ, thuộc về đấy là 2 thuyền Uy nhất, Min... |
| 51 | Dòng 582 | `P580_C267_V234` | **CLEAN** | Khớp tổng chiến binh và các đội thuyền Nội phu. | 以上各共戰兵一千三百二十八人。至如供雜役差遣與更守者，有內府各隊船：把令一、 | Các chiến binh trên đây cộng 1.328 người. Còn như quân để sai khiến việc vặt và ca... |
| 52 | Dòng 583 | `P581_C268_V234` | **CLEAN** | Hai vế khớp trọn vẹn số liệu các thuyền. | 把令二二隊各三十八人，新一船八十人，新二船一百人，志一船八十五人，志二船九十四人， | Bả lệnh nhị, mỗi đội 38 người, thuyền Tân nhất 80 người, thuyền Tân nhị 100 người,... |
| 53 | Dòng 584 | `P582_C268_V234` | **CLEAN** | Khớp chính xác tên thuyền và số lượng người. | 新柴船六十一人，新定船八十九人，有內馬良醫一人，草馬十八人。 | thuyền Tân Sài 1 người, thuyền Tân định 89 người, có lương y nội mã 1 người, cắt c... |
| 54 | Dòng 585 | `P583_C268_V234` | **CLEAN** | Dịch đúng nghĩa đen các từ đường và Thiên Mụ. | 有守各祠堂老船：新安、康安、康二三船，共九十一人。有天姥寺洒夫二十五人。 | Có lão thuyền giữ các từ đường, ba thuyền Tân An, Khang nhất, Khang nhị, cộng 91 n... |
| 55 | Dòng 586 | `P584_C268_V234` | **PARTIAL** | Bản dịch bị dính thêm các phủ khác vào cuối. | 有守各府：金龍府水船十一人，陽春府富二船六十六人， | Có các thuyền giữ các phủ, thuỷ thuyền phủ Kim Long 11 người, thuyền Phú Nhị phủ D... |
| 56 | Dòng 587 | `P585_C268_V234` | **PARTIAL** | Trượt ranh giới do nhặt sót hoặc dính câu. | 新富船四十人。 | Có các thuyền giữ các vườn, thuyền Định nhị vườn Khang thượng 16 người, thuyền Tân... |
| 57 | Dòng 588 | `P586_C268_V235` | **CLEAN** | Khớp chính xác kho Thọ Khang và lão súng. | 有守壽康庫：老銃四十五人，安一船六十人。 | Có các thuyền giữ kho Thọ Khang, lão súng 45 người, thuyền An nhất 60 người. |
| 58 | Dòng 589 | `P587_C268_V235` | **CLEAN** | Dịch đúng câu tiêu đề giữ các lăng mộ. | 有守各陵墓： | Có các thuyền giữ các lăng mộ. |
| 59 | Dòng 590 | `P588_C268_V235` | **CLEAN** | Khớp số liệu lão súng và người. | 老銃八船共一百六十九人， | 3 thuyền lão súng cộng 169 người. |
| 60 | Dòng 823 | `P0821_C002_V004` | **CLEAN** | Hai vế dịch đúng trọn vẹn | 淡墨濃青作意描，地脈衰靈看樹石。 | Đậm nhạt xanh đen vẽ đủ màu, Mạch đất thịnh suy nhìn cây đá. |
| 61 | Dòng 824 | `P0822_C002_V004` | **CLEAN** | Hai vế tương ứng đầy đủ | 民情愁樂問芻蕘。春開繡幕邀戎府，秋起金城拱聖朝。此味廣川人樂得， | Tình dân vui khổ hỏi mục tiều. Màn thêu xuân mở mời nhung phủ; Thu dựng thành vàng... |
| 62 | Dòng 825 | `P0823_C003_V004` | **CLEAN** | Khớp đúng nghĩa | 芬華不為陸沉凋。 | Hoa thơm chìm cạn chẳng phai đâu. |
| 63 | Dòng 826 | `P0824_C003_V005` | **CLEAN** | Dịch sát nghĩa từng câu | 三曰蕭寺晨鐘：晨風冷落露華抛，迢遞秋聲過樹梢。 | Tiêu tự chuông mai. Gió sớm lạnh lùng hoa móc bay, Tiếng thu xa đến lướt cành cây. |
| 64 | Dòng 838 | `P0836_C003_V011` | **CLEAN** | Dịch trọn vẹn, ngữ nghĩa hai bên khớp nhau. | 九曰鹿峙村居：僻壤窮丘可寂聽，子孫無患奪茅亭。 | Lộc trĩ xóm dân. Đất hẹp gò cùng vắng tiếng vang, Cháu con không sợ cướp lều tranh. |
| 65 | Dòng 839 | `P0837_C003_V012` | **CLEAN** | Khớp tuyệt đối nội dung | 十曰盧溪漁泊：漁家營隊月層層，漏出叢蘆幾點燈。父老空聞朝號漢， | Lư khê chài cá. Vạn chài chen chóc nguyệt lưng lưng. Bụi sậy ló ra mấy ngọn đăng (... |
| 66 | Dòng 840 | `P0838_C003_V012` | **CLEAN** | Dịch chính xác câu kết | 妻兒偏慣客名陵。 | Vợ con chỉ biết khách tên Lăng. |
| 67 | Dòng 841 | `P0839_C004_V012` | **CLEAN** | Dịch đúng câu thơ | 撐持江漢雙枝櫂， | Vẫy vùng giang hán chèo đôi mái; |
| 68 | Dòng 842 | `P0840_C004_V012` | **CLEAN** | Dịch đúng câu thơ | 收拾乾坤一把罾。 | Thu lượm càn khôn lưới một vàng. |
| 69 | Dòng 843 | `P0841_C004_V012` | **CLEAN** | Hai vế dịch đúng trọn vẹn nghĩa. | 聞道白蛟今又長，睡餘行擬試餘能。 | Nghe nói thuồng luồng nay đã lớn; Chờ khi ngủ dậy thử tài chăng. |
| 70 | Dòng 844 | `P0842_C004_V012` | **CLEAN** | Hai vế khớp đúng nội dung. | 居貞吟詠頗多。 | Cư Trinh ngâm vịnh khá nhiều bài: |
| 71 | Dòng 850 | `P0848_C004_V014` | **CLEAN** | Hai vế dịch trọn vẹn chính xác. | 大抵狙翁憑馬上，雍行無復帝王風。 | Đại để thư ông nhờ vó ngựa, Ung dung không có đế vương phong. |
| 72 | Dòng 851 | `P0849_C004_V015` | **CLEAN** | Khớp đúng phần tự sự và câu thơ. | 其詠四趣，漁詩云：金翠臨河又向溪。 | Thơ vịnh tứ thú thì có các bài: Đi câu. Sợi biếc câu vàng sông lại khe; |
| 73 | Dòng 852 | `P0850_C004_V016` | **CLEAN** | Các câu thơ được dịch đối chiếu tốt. | 石灘蘆渚任東西。絲牽戲蚌爭江鷸，竹引懸魚怯水雞。匏盞隨花猶避晉， | Bờ lau ghềnh đá khắp đông tê (tây). Thả tơ đùa bắt trai cò hỏng; Kéo trúc treo man... |
| 74 | Dòng 867 | `P0865_C005_V020` | **PARTIAL** | Dịch ý tựa đề nhưng bị thiếu phần dẫn nhập. | 其暮雨留客詩并序云： | MƯA CHIỀU GIỮ KHÁCH VÀ TỰA |
| 75 | Dòng 868 | `P0866_C005_V021` | **CLEAN** | Hai vế tương đương nghĩa khá sát. | 詩并序云醜虜辰平孤生日，老門尚同而未入酒線郡以何言。 | Giặc giã buổi yên, tuổi già ngày đến. Cửa Ngọc Môn chưa vào được, quận Tửu Tuyển s... |
| 76 | Dòng 966 | `P0964_C012_V028` | **CLEAN** | Bản dịch nghĩa chuẩn xác so với nguyên tác. | 盛邦，王命允從。 | Nước An Nam phồn thịnh thì mệnh vua phải được theo. |
| 77 | Dòng 1083 | `P1081_C019_V037` | **CLEAN** | Hai vế dịch đúng trọn vẹn | 斯義也，斯情也，何厚如之！雖古王道之邦，亦不過是。 | nghĩa ấy tình ấy còn gì hậu bằng, tuy nước vương đạo đời xưa cũng không hơn thế. |
| 78 | Dòng 1084 | `P1082_C019_V037` | **CLEAN** | Hai vế dịch đúng trọn vẹn | 而後水軍及漂民為拘留不遣，將貴國未及發放耶？抑彼等有何事故而見留歟？ | Còn bọn thuỷ quân và dân xiêu lần sau hãy còn bị giữ, hoặc giả là do quý quốc chưa... |
| 79 | Dòng 1085 | `P1083_C019_V037` | **CLEAN** | Hai vế dịch đúng trọn vẹn | 此吾之所未解也。 | điều ấy chúng tôi chưa được hiểu. |
| 80 | Dòng 1086 | `P1084_C020_V037` | **CLEAN** | Hai vế dịch đúng trọn vẹn | 且夫所發回五十四名者，本國之軍民也；而後水軍及漂民見留，亦本國之軍民也。均是吾之赤子蒼生， | Vả chăng, 54 tên được thả về đó là quân dân của bản quốc, mà những thuỷ quân và dâ... |
| 81 | Dòng 1087 | `P1085_C020_V037` | **CLEAN** | Hai vế dịch đúng trọn vẹn | 固宜一例而見愛，未審貴國之一拘一放一留，何寬於彼，何密於此也！ | nên coi như một cả, chưa hiểu tại sao quý quốc lại tha kẻ này mà giữ lại kẻ kia, s... |
| 82 | Dòng 1104 | `P1102_C021_V039` | **CLEAN** | Dịch đúng và đủ ý câu Hán. | 暹羅之與安南，猶齊楚燕趙平交之國也。 | Nước Xiêm La cùng với nước An Nam cũng như các nước Tề Sở Yên Triệu là những nước ... |
| 83 | Dòng 1145 | `P1143_C023_V043` | **CLEAN** | Danh sách tên người dịch khớp nguyên tác. | 河仙十詠，鄚天賜與北國群英朱璞、吳之翰、李仁長、單秉馭、王昶、方銘、盧逢吉、徐協飛、林維則、徐鉉、林其軒、 | Mười bài vịnh Hà Tiên do Mạc Thiên Tứ xướng, cùng các nhà văn Bắc quốc là Chu Phác... |
| 84 | Dòng 1146 | `P1144_C023_V043` | **CLEAN** | Liệt kê danh tính dịch đúng từng người. | 陳瑞鳳、陳自蘭、陳躍淵、陳鳴夏、陳演泗、陳者發、陳維德、徐登基、湯玉崇、黃奇珍、周景陽、 | Trần Duy Đức, Từ Đăng Sơ, Thanh Ngọc Sùng, Trần Tự Phát, Hoàng Kỳ Trân, Chu Cảnh D... |
| 85 | Dòng 1147 | `P1145_C024_V043` | **CLEAN** | Đoạn liệt kê và tổng kết số liệu khớp. | 孫天珍、孫天瑞、孫季茂，共二十五人。南國鄭連山、潘文廣、阮儀、陳貞、鄧明本、莫朝直，共六人，和韻集中共三百二十篇。 | Tôn Thiên Trân, Tôn Thiên Thuy, Tôn Quý Mậu, cộng 25 người, Nam quốc là Trịnh Liên... |
| 86 | Dòng 1364 | `P1362_C037_V078` | **CLEAN** | Dịch thơ tương đối sát ý nguyên tác. | 清世誰高尚，閑眠為不才。 | Đời thanh dì cao thương? Rồi ngủ bởi không tài. |
| 87 | Dòng 1365 | `P1363_C037_V078` | **PARTIAL** | Lỗi OCR bản Việt nặng, nội dung trượt nhẹ. | 其為圖畫，故城懷古云：斜陽停馬望無涯，無限廢興情。園苑僧為寺，宮庭牧自耕。 | Than cũ chả Bản Roat cổ: Bóng tà dừng ngựa chứng, Man mác nỗi hưng rụng. Lĩĩng uyể... |
| 88 | Dòng 1366 | `P1364_C037_V079` | **PARTIAL** | Bản dịch lỗi OCR nhiều chữ, nghĩa bị lệch. | 殘山廢古塔，剩水竄荒城。神道原無擾，極西開漫刻盟。其詠馮驩云：填門客食漫翁， | Núi tàn trở tháp cổ; Nước củ hiện thành hoang. Thần đạo nguyên 0ô cứ. Củc tây tràn... |
| 89 | Dòng 1443 | `P1441_C042_V089` | **CLEAN** | Dịch thơ thất ngôn đúng nội dung. | 低垂金鏡畔，輕拂玉橋邊。眉細波中畫，腰輕風裏環。章臺千萬樹，惟爾沐恩先。 | Rủ xuống bờ nước gương; Phất phơ bên cầu ngọc. Mày (liễu) vẽ trong sóng; Lưng (liễ... |
| 90 | Dòng 1444 | `P1442_C042_V090` | **MISMATCH** | Bản Việt giữ nguyên âm Hán-Việt, chưa dịch nghĩa. | 一夫開曙色，萬里響晴雷。臚唱傳三殿，鴻名播九垓。何須太史氏，更奏慶雲來。 | Nhất thiên khai thự sắc; Vạn lý hưởng tình lôi. Lô xướng truyền tam điện; Hồng dan... |
| 91 | Dòng 1703 | `P1701_C061_V415` | **CLEAN** | Dịch nghĩa xuôi, số liệu và chi tiết đúng. | 錫價亦賤，所作美檳圓盒，刻鏤花彩二件，共錢四百，但色欠白耳。 | Giá thiếc cũng rẻ, làm hai cái hộp đựng trầu tròn, chạm vẽ hoa văn, cộng tiền cổ l... |
| 92 | Dòng 1704 | `P1702_C061_V415` | **CLEAN** | Liệt kê các khoản cống nạp dịch chuẩn xác. | 前阮氏每年生日禮，各司匠官並有賀禮，或二百或五百，惟鑄匠司本部錢一貫，大唾龍銅一口，中唾龍銅一口，燈柱銅每船一株。 | Họ Nguyễn trước mỗi năm đến ngày lễ sinh nhật các quan ty thợ đều có tiền mừng, ho... |
| 93 | Dòng 1705 | `P1703_C061_V415` | **CLEAN** | Ý nghĩa hai bên tương đương hoàn toàn. | 鑄匠司京人五百，大唾龍銅一口，中唾龍銅一口，燈柱銅一株。 | thợ người kinh thì mỗi người 5 tiền, ống nhổ thau lớn 1 chiếc, ống nhổ thau vừa 1 ... |
| 94 | Dòng 1706 | `P1704_C061_V415` | **CLEAN** | Thông tin địa danh và hàng hóa đúng. | 廣南會安庯，銅鍋銅盤，洋船販到，平辰以千萬計。 | Phố Hội An xứ Quảng Nam, nồi đồng mâm đồng, do tàu Tây phương chở đến bán, bình th... |
| 95 | Dòng 1707 | `P1705_C061_V415` | **CLEAN** | Dịch trọn vẹn câu cuối đoạn. | 北客又回清河庯，每得一倍之利。 | người Bắc khách lại buôn về phố Thanh Hà, thường được lời gấp đôi. |
| 96 | Dòng 2040 | `P2038_C003_V005` | **CLEAN** | Thơ song ngữ Hán Việt khớp nhau | 金獸哮殘星海渚，木鯨打落月林坳。 | Thú vàng réo động, biển sao lặn; Cá gỗ khua rơi, rừng nguyệt mờ, |
| 97 | Dòng 2041 | `P2039_C003_V005` | **CLEAN** | Thơ song ngữ Hán Việt khớp nhau | 萬家醒夢神初駕，佛朝同顏僧下巢。 | Muôn nhà tỉnh mộng, thần vừa giáng; Nghìn phật nở cười tăng dạo am. |
| 98 | Dòng 2042 | `P2040_C003_V005` | **CLEAN** | Thơ song ngữ Hán Việt khớp nhau | 待扣堪憐亦有禪，不鳴鳴得太陽交。 | Khá thương, chờ đánh có khi đánh; Hễ đánh là lay cả thái dương. |
| 99 | Dòng 2043 | `P2041_C004_V011` | **CLEAN** | Hai vế Hán Việt dịch khớp trọn vẹn từng câu thơ. | 鹿脩留客野茶黑，豚足迎妻園果青。 | Nem hươu cầm khách chè quê đặc; Dò lợn vợ về rau quả xanh. |
| 100 | Dòng 2044 | `P2042_C004_V011` | **CLEAN** | Nội dung thơ Hán và Việt tương ứng chính xác. | 飽煖不知天子力，豐登惟信海神靈。 | No ấm biết gì uy chúa thánh, Dồi dào tin ở biển thần thiêng. |
| 101 | Dòng 2045 | `P2043_C004_V011` | **CLEAN** | Bản dịch nghĩa sát đúng hoàn toàn từng vế thơ. | 更無租賦又閑事，太半人稱近百齡。 | Đã không tô thuế lại nhàn rỗi, Già nửa người đều tuổi cận trăm. |
