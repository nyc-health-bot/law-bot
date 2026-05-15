"""
Download and extract one NYC Health Code PDF (article or commissioner's regulation chapter).

Usage:
    python worker.py --type article --number 81 --title "Food Preparation..." --path /assets/... --out-dir ../data
    python worker.py --type chapter --number 23 --title "Food Service..." --path /assets/... --out-dir ../data
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import fetch_pdf, extract_pdf_text, parse_sections, article_filename, chapter_filename


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["article", "chapter"], required=True)
    ap.add_argument("--number", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--path", required=True, help="URL path to the PDF")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    pdf_bytes = fetch_pdf(args.path)
    extracted = extract_pdf_text(pdf_bytes)

    result = {
        "type": args.type,
        "number": args.number,
        "title": args.title,
        "source_url": f"https://www.nyc.gov{args.path}",
        **extracted,
        "sections": parse_sections(extracted["text"]),
    }

    if args.type == "article":
        filename = article_filename(args.number)
    else:
        filename = chapter_filename(args.number)

    out_path = Path(args.out_dir) / filename
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {out_path.name} ({out_path.stat().st_size // 1024} KB, {result['page_count']} pages)")


if __name__ == "__main__":
    main()
