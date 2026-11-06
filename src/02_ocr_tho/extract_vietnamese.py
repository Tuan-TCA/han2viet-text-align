
from pathlib import Path
import subprocess
import re


# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

# File location: CV16/src/02_ocr_tho/extract_vietnamese.py
# Project root: CV16/
ROOT = Path(__file__).resolve().parents[2]

TASKS = [
    {
        "part": "Cap_01",
        "pdf": ROOT / "01_nguon" / "Cap_01" / "VIET.pdf",
    },
    {
        "part": "Cap_02",
        "pdf": ROOT / "01_nguon" / "Cap_02" / "VIET.pdf",
    },
]


# ==================================================
# 2. GET PDF PAGE COUNT
# ==================================================

def get_page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    match = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)

    if not match:
        raise RuntimeError(f"Cannot read page count: {pdf_path}")

    return int(match.group(1))


# ==================================================
# 3. EXTRACT EACH PAGE
# ==================================================

def extract_pdf(pdf_path: Path, part: str):
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = ROOT / "02_ocr_tho" / part / "viet" / "raw"
    corrected_dir = ROOT / "02_ocr_tho" / part / "viet" / "corrected"

    output_dir.mkdir(parents=True, exist_ok=True)
    corrected_dir.mkdir(parents=True, exist_ok=True)

    total_pages = get_page_count(pdf_path)

    print(f"\nProcessing: {pdf_path.name}")
    print(f"Total pages: {total_pages}")

    failed_pages = []

    for page in range(1, total_pages + 1):
        output_file = output_dir / f"{page:04d}.txt"

        command = [
            "pdftotext",
            "-f", str(page),
            "-l", str(page),
            "-layout",
            "-enc", "UTF-8",
            str(pdf_path),
            str(output_file),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        if result.returncode != 0:
            failed_pages.append(page)
            print(f"\n[ERROR] Page {page}: {result.stderr}")
            continue

        print(
            f"\rProgress: {page}/{total_pages}",
            end="",
            flush=True,
        )

    print(f"\nCompleted: {part}")
    print(f"Output: {output_dir}")
    print(f"Extracted: {total_pages - len(failed_pages)}/{total_pages}")

    if failed_pages:
        print(f"Failed pages: {failed_pages}")

    return {
        "part": part,
        "total": total_pages,
        "failed": failed_pages,
    }


# ==================================================
# 4. MAIN
# ==================================================

def main():
    print(f"Project root: {ROOT}")

    results = []

    for task in TASKS:
        result = extract_pdf(
            pdf_path=task["pdf"],
            part=task["part"],
        )
        results.append(result)

    print("\n========== SUMMARY ==========")

    for result in results:
        print(
            f"{result['part']}: "
            f"{result['total'] - len(result['failed'])}/"
            f"{result['total']} pages"
        )

    print("\nExtraction process finished.")


if __name__ == "__main__":
    main()
