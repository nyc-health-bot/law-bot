"""
Scrape a single subpart and save to a JSON file.

Usage:
    python worker_subpart.py --index 1 --text "Subpart 14-1 ..." --url "https://..." --out-dir ../data
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import scrape_subpart


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    item = {"text": args.text, "url": args.url}
    subpart = scrape_subpart(item)

    out_path = Path(args.out_dir) / f"part_14_{args.index}.json"
    out_path.write_text(json.dumps(subpart, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {out_path.name} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
