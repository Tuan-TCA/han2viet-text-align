import pandas as pd
import os
import numpy as np

def convert_to_template(source_file, target_file):
    # 1. Đọc file kết quả align
    if not os.path.exists(source_file):
        print(f"Lỗi: Không tìm thấy file {source_file}")
        return

    df_src = pd.read_excel(source_file)
    
    # Định nghĩa 11 cột của file Template
    template_columns = [
        'Pair_ID', 'Chinese', 'Vietnamese', 'OMISSION', 'ADDITION', 'MISSING',
        'Alignment_Type', 'Punct_Anchor_Match', 'Label_Target', 'OCR_Conf_Min', 'Note'
    ]

    # 2. Kiểm tra file đích đã tồn tại chưa để lấy Index bắt đầu
    if os.path.exists(target_file):
        df_target = pd.read_excel(target_file)
        start_idx = len(df_target) + 1
        print(f"Tìm thấy file Template cũ. Sẽ append từ dòng {start_idx}...")
    else:
        df_target = pd.DataFrame(columns=template_columns)
        start_idx = 1
        print("Chưa có file Template. Sẽ tạo file mới...")

    new_rows = []

    # 3. Duyệt qua từng dòng của file kết quả
    for i, row in df_src.iterrows():
        idx = start_idx + i
        pair_id = f"C{idx:03d}_V{idx:03d}"
        
        zh_text = str(row['Han_Text']).strip() if pd.notna(row['Han_Text']) else ""
        vi_text = str(row['Viet_Text']).strip() if pd.notna(row['Viet_Text']) else ""

        # --- Xử lý logic cho các cột bắt buộc ---
        
        # Xác định MISSING (1-0, 0-1, 0-0)
        missing = 0
        align_type = "1-1"
        
        if not zh_text and (not vi_text or vi_text == "[TRỐNG]"):
            missing = 1
            align_type = "0-0"
        elif not zh_text:
            missing = 1
            align_type = "0-1"
        elif not vi_text or vi_text == "[TRỐNG]":
            missing = 1
            align_type = "1-0"
            
        # Mẹo nhỏ để đoán Alignment_Type dựa trên độ dài (bạn có thể sửa lại thủ công sau)
        if missing == 0:
            if len(vi_text) > len(zh_text) * 3:
                align_type = "1-N"
            elif len(zh_text) > len(vi_text) * 3:
                align_type = "N-1"

        # Tạo dictionary cho dòng mới
        new_row = {
            'Pair_ID': pair_id,
            'Chinese': zh_text,
            'Vietnamese': vi_text,
            'OMISSION': 0,  # Mặc định là 0, người dùng sẽ tự gán nhãn nếu có lỗi
            'ADDITION': 0,  # Mặc định là 0
            'MISSING': missing,
            'Alignment_Type': align_type,
            'Punct_Anchor_Match': 0, # Mặc định 0
            # Cột Label_Target sẽ tự động tính toán dựa trên công thức Excel
            'Label_Target': f"=IF(SUM(D{idx}:F{idx})=0, 1, 0)", 
            'OCR_Conf_Min': 1.0, # Mặc định 1.0 vì file PDF đã bóc text (không qua OCR ảnh)
            'Note': f"Page {row.get('Page', '')}"
        }
        new_rows.append(new_row)

    # 4. Ghép dữ liệu mới vào DataFrame đích và xuất ra file
    if new_rows:
        df_new = pd.DataFrame(new_rows)
        df_final = pd.concat([df_target, df_new], ignore_index=True)
        
        # Đảm bảo đúng thứ tự cột
        df_final = df_final[template_columns]
        
        df_final.to_excel(target_file, index=False)
        print(f"Thành công! Đã chuyển đổi và lưu {len(new_rows)} dòng vào: {target_file}")
    else:
        print("Không có dữ liệu mới để chuyển đổi.")

if __name__ == "__main__":
    import os
    
    # 1. Lấy đường dẫn tuyệt đối của thư mục chứa file script này (04_dong_hang)
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Tự động nối đường dẫn tới 2 file (vì chúng cùng cấp với script)
    SOURCE_EXCEL = os.path.join(SCRIPT_DIR, 'KetQua_Final.xlsx')
    TEMPLATE_EXCEL = os.path.join(SCRIPT_DIR, 'Cap-01-P01.xlsx')
    
    # 3. In ra để kiểm tra (nếu cần)
    print(f"Đang đọc file: {SOURCE_EXCEL}")
    
    if os.path.exists(SOURCE_EXCEL):
        convert_to_template(SOURCE_EXCEL, TEMPLATE_EXCEL)
    else:
        print(f"LỖI: Không tìm thấy file {SOURCE_EXCEL}")