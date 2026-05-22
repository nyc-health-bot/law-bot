"""
Scrape a single NYC Admin Code Title 17 chapter and save to a JSON file.

Usage:
    python worker.py --number 5 --title "SMOKE-FREE AIR ACT" \
        --url https://nycadmincode.readthedocs.io/t17/c05/index.html \
        --out-dir ../data
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import scrape_chapter, chapter_filename


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--number", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    chapter = scrape_chapter(args.number, args.title, args.url)

    out_path = Path(args.out_dir) / chapter_filename(args.number)
    out_path.write_text(
        json.dumps(chapter, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"saved {out_path.name} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
