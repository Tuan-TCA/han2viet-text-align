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
    text = re.sub(r'[ð?“”*_!]', '', text)
    return " ".join(text.split())

print("\n[1/2] Đang xử lý file chữ Hán...")

# --- LẤY ĐƯỜNG DẪN THƯ MỤC CHỨA FILE SCRIPT NÀY ---
# Dù bạn đứng ở Terminal nào, nó luôn tìm ra thư mục HAN
current_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(current_dir, '0001-corrected.xlsx')

if not os.path.exists(file_path):
    print(f"LỖI: Không tìm thấy file tại đường dẫn: {file_path}")
    print("Vui lòng kiểm tra lại xem file Excel đã nằm cùng thư mục với file code này chưa.")
    sys.exit()

try:
    df = pd.read_excel(file_path)
    
    df_cleaned = df[['Cột', 'Corrected text']].copy()
    df_cleaned.columns = ['id_zh', 'text_zh']
    df_cleaned['text_zh'] = df_cleaned['text_zh'].apply(clean_zh_text)
    
    # Lưu file output ngay tại thư mục HAN
    output_path = os.path.join(current_dir, 'zh_cleaned.csv')
    df_cleaned.to_csv(output_path, index=False, encoding='utf-8-sig')
    
    print(f"   -> THÀNH CÔNG! Đã lưu file 'zh_cleaned.csv' tại thư mục HAN.")
    print(f"   -> Tổng cộng: {len(df_cleaned)} câu chữ Hán.")
except Exception as e:
    print(f"Lỗi khi xử lý file Hán: {e}")