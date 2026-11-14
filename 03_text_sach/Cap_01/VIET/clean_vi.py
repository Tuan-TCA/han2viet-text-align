# ==========================================
# FILE 2: LÀM SẠCH TIẾNG VIỆT (clean_vi.py)
# Nằm trong thư mục VIET (cùng chỗ với file 170-190.csv)
# ==========================================
import sys
import subprocess
import importlib.util
import re
import os  # Thư viện xử lý đường dẫn

def check_and_install(package):
    if importlib.util.find_spec(package) is None:
        print(f"Thư viện '{package}' chưa có. Đang tự động cài đặt...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    else:
        print(f"Thư viện '{package}' đã có sẵn.")

print("=== KIỂM TRA THƯ VIỆN ===")
check_and_install("pandas")

import pandas as pd

def clean_vi_text(text):
    if pd.isna(text): return ""
    text = str(text)
    # Xóa các ký tự rác từ OCR
    text = re.sub(r'[ð?“”*_!]', '', text)
    return " ".join(text.split())

print("\n[2/2] Đang xử lý file tiếng Việt...")

# --- LẤY ĐƯỜNG DẪN THƯ MỤC CHỨA FILE SCRIPT NÀY ---
# Tự động lấy thư mục hiện tại chứa file clean_vi.py
current_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(current_dir, '170-190.csv')


# Kiểm tra xem file CSV có thực sự tồn tại ở đó không
if not os.path.exists(file_path):
    print(f"LỖI: Không tìm thấy file tại đường dẫn: {file_path}")
    print("Vui lòng kiểm tra lại xem file '170-190.csv' đã nằm cùng thư mục với file code này chưa.")
    sys.exit()

try:
    # Đọc file CSV với encoding utf-8-sig để không bị lỗi font tiếng Việt
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    
    # Chỉ lấy các cột cần thiết (ID, trang, nội dung)
    df_cleaned = df[['id', 'page', 'page_end', 'Corrected text']].copy()
    df_cleaned.columns = ['id_vi', 'page_start', 'page_end', 'text_vi']
    
    # Làm sạch văn bản
    df_cleaned['text_vi'] = df_cleaned['text_vi'].apply(clean_vi_text)
    
    # Lưu file output ngay tại thư mục chứa code (thư mục VIET)
    output_path = os.path.join(current_dir, 'vi_cleaned.csv')
    df_cleaned.to_csv(output_path, index=False, encoding='utf-8-sig')
    
    print(f"   -> THÀNH CÔNG! Đã lưu file 'vi_cleaned.csv' tại thư mục VIET.")
    print(f"   -> Tổng cộng: {len(df_cleaned)} câu tiếng Việt.")
    
except Exception as e:
    print(f"Lỗi khi xử lý file Việt: {e}")