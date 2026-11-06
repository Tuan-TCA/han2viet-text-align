
from pathlib import Path
import subprocess
import re


# ==========================================
# 1. CONFIGURATION
# ==========================================

ROOT = Path(__file__).resolve().parents[2]

DPI = 300

TASKS = [
    {
        "part": "Cap_01",
        "language": "han",
        "pdf": ROOT / "01_nguon" / "Cap_01" / "HAN.pdf",
    },
    # {
    #     "part": "Cap_01",
    #     "language": "viet",
    #     "pdf": ROOT / "01_nguon" / "Cap_01" / "VIET.pdf",
    # },
    {
        "part": "Cap_02",
        "language": "han",
        "pdf": ROOT / "01_nguon" / "Cap_02" / "HAN.pdf",
    },
    # {
    #     "part": "Cap_02",
    #     "language": "viet",
    #     "pdf": ROOT / "01_nguon" / "Cap_02" / "VIET.pdf",
    # },
]


# ==========================================
# 2. GET PDF PAGE COUNT
# ==========================================

def get_page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    match = re.search(
        r"^Pages:\s+(\d+)",
        result.stdout,
        re.MULTILINE,
    )

    if not match:
        raise RuntimeError(
            f"Cannot read page count: {pdf_path}"
        )

    return int(match.group(1))


# ==========================================
# 3. CONVERT ONE PAGE
# ==========================================

def convert_page(
    pdf_path: Path,
    page: int,
    output_dir: Path,
):
    output_file = output_dir / f"{page:04d}.png"

    # Avoid overwriting existing images
    if output_file.exists():
        print(f"[SKIP] {output_file.name}")
        return

    prefix = output_dir / f"{page:04d}"

    command = [
        "pdftoppm",
        "-f", str(page),
        "-l", str(page),
        "-r", str(DPI),
        "-png",
        "-singlefile",
        str(pdf_path),
        str(prefix),
    ]

    subprocess.run(command, check=True)

    print(f"[OK] {output_file.name}")


# ==========================================
# 4. CONVERT ENTIRE PDF
# ==========================================

def convert_pdf(task: dict):
    pdf_path = task["pdf"]

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    output_dir = (
        ROOT
        / "02_ocr_tho"
        / task["part"]
        / task["language"]
        / "images"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    total_pages = get_page_count(pdf_path)

    print("\n" + "=" * 50)
    print(f"PDF: {pdf_path.name}")
    print(f"Part: {task['part']}")
    print(f"Language: {task['language']}")
    print(f"Pages: {total_pages}")
    print("=" * 50)

    for page in range(1, total_pages + 1):
        convert_page(
            pdf_path,
            page,
            output_dir,
        )

    print(f"Completed: {output_dir}")


# ==========================================
# 5. MAIN
# ==========================================

def main():
    print(f"Project root: {ROOT}")

    for task in TASKS:
        convert_pdf(task)

    print("\nAll PDF conversions completed.")


if __name__ == "__main__":
    main()
