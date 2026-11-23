# ==========================================
# FILE 1: LÀM SẠCH CHỮ HÁN (clean_zh.py)
# Nằm trong thư mục HAN
# ==========================================
import sys
import subprocess
import importlib.util
import re
import os 

def check_and_install(package):
    if importlib.util.find_spec(package) is None:
        print(f"Thư viện '{package}' chưa có. Đang tự động cài đặt...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    else:
        print(f"Thư viện '{package}' đã có sẵn.")

print("=== KIỂM TRA THƯ VIỆN ===")
check_and_install("pandas")
check_and_install("openpyxl")

import pandas as pd

def clean_zh_text(text):
    if pd.isna(text): return ""
    text = str(text)
    # Loại bỏ các ký tự rác, dấu ngoặc kép, dấu sao...
    text = re.sub(r'[ð?“”*_!]', '', text)
    return " ".join(text.split())

# --- LẤY ĐƯỜNG DẪN THƯ MỤC CHỨA FILE SCRIPT NÀY ---
# Dù bạn đứng ở Terminal nào, nó luôn tìm ra thư mục HAN
current_dir = os.path.dirname(os.path.abspath(__file__))

# Danh sách các file cần xử lý (hỗ trợ cả Excel và CSV)
files_to_process = [
    "0001-corrected", 
    "0002-corrected"
]

for file_prefix in files_to_process:
    # Thử tìm file .xlsx trước, nếu không có thì tìm .csv
    input_path_xlsx = os.path.join(current_dir, f"{file_prefix}.xlsx")
    input_path_csv = os.path.join(current_dir, f"{file_prefix}.csv")
    
    if os.path.exists(input_path_xlsx):
        input_path = input_path_xlsx
        print(f"\n[1/2] Đang xử lý file Hán (Excel): {file_prefix}.xlsx")
        df = pd.read_excel(input_path)
    elif os.path.exists(input_path_csv):
        input_path = input_path_csv
        print(f"\n[1/2] Đang xử lý file Hán (CSV): {file_prefix}.csv")
        # Đọc CSV với utf-8-sig để nhận diện đúng tiếng Việt
        df = pd.read_csv(input_path, encoding='utf-8-sig')
    else:
        print(f"\nBỎ QUA: Không tìm thấy file {file_prefix}.xlsx hoặc .csv trong thư mục HAN.")
        continue

    try:
        # Kiểm tra xem file có cột 'Corrected text' không
        if 'Corrected text' not in df.columns:
            print(f"LỖI: File {file_prefix} không có cột 'Corrected text'. Vui lòng kiểm tra lại.")
            continue

        df_cleaned = df[['Cột', 'Corrected text']].copy()
        df_cleaned.columns = ['id_zh', 'text_zh']
        df_cleaned['text_zh'] = df_cleaned['text_zh'].apply(clean_zh_text)
        
        # Lưu file output ngay tại thư mục HAN với encoding utf-8-sig
        output_filename = f"{file_prefix.split('-')[0]}-cleaned.csv"
        output_path = os.path.join(current_dir, output_filename)
        
        df_cleaned.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        print(f"   -> THÀNH CÔNG! Đã lưu file '{output_filename}' tại thư mục HAN.")
        print(f"   -> Tổng cộng: {len(df_cleaned)} câu chữ Hán.")
        
    except Exception as e:
        print(f"Lỗi khi xử lý file {file_prefix}: {e}")

print("\n=== HOÀN TẤT TẤT CẢ ===")