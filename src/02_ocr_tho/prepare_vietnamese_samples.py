
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

TASKS = [
    {
        "part": "Cap_01",
        "pdf": ROOT / "01_nguon" / "Cap_01" / "VIET.pdf",
        "pages": [1, 100, 251],
    },
    {
        "part": "Cap_02",
        "pdf": ROOT / "01_nguon" / "Cap_02" / "VIET.pdf",
        "pages": [1, 50, 105],
    },
]

DPI = 300


def extract_page(pdf_path, page, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

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

    print(f"[OK] {prefix.name}.png")


def main():
    for task in TASKS:
        output_dir = (
            ROOT / "02_ocr_tho"
            / task["part"] / "viet" / "images"
        )

        for page in task["pages"]:
            extract_page(task["pdf"], page, output_dir)

    print("Sample image extraction completed.")


if __name__ == "__main__":
    main()
