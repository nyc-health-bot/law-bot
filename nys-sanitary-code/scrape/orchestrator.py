"""
Fetch the NYS Sanitary Code TOC and scrape all parts in parallel.

Each part is scraped by a separate worker.py subprocess and saved as
data/part_NNN.json.

Usage:
    python orchestrator.py                   # all parts, 4 workers
    python orchestrator.py --workers 6       # raise concurrency
    python orchestrator.py --parts 1 2 5    # specific parts only
    python orchestrator.py --out-dir /path  # custom output directory
"""

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import fetch, extract_toc_links, CHAPTER_URL

WORKER = Path(__file__).parent / "worker.py"
DEFAULT_OUT = Path(__file__).parent.parent / "data"


def _part_number(text: str):
    m = re.search(r"Part\s+(\d+)", text)
    return int(m.group(1)) if m else None


def _run_worker(index: int, item: dict, out_dir: Path) -> tuple[int, str, bool]:
    result = subprocess.run(
        [
            sys.executable, str(WORKER),
            "--index", str(index),
            "--text", item["text"],
            "--url", item["url"],
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
    )
    ok = result.returncode == 0
    msg = (result.stdout.strip() or result.stderr.strip())[:120]
    return index, msg, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4, metavar="N")
    ap.add_argument("--parts", nargs="*", type=int, metavar="N")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[toc] Fetching chapter TOC…")
    html = fetch(CHAPTER_URL)
    parts = extract_toc_links(html)
    print(f"  Found {len(parts)} parts")

    if args.parts:
        wanted = set(args.parts)
        parts = [p for p in parts if _part_number(p["text"]) in wanted]
        print(f"  Filtered to {len(parts)} part(s): {sorted(wanted)}")

    parts_to_run = []
    for i, item in enumerate(parts):
        out_file = out_dir / f"part_{i + 1:03d}.json"
        if out_file.exists():
            print(f"  [skip] part_{i + 1:03d}: already exists")
        else:
            parts_to_run.append((i + 1, item))

    if not parts_to_run:
        print("  Nothing to scrape — all parts already present.")
        return

    print(f"  Spawning {args.workers} worker(s) for {len(parts_to_run)} part(s)…\n")

    completed = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_worker, i, item, out_dir): item
            for i, item in parts_to_run
        }
        for fut in as_completed(futures):
            idx, msg, ok = fut.result()
            tag = "OK  " if ok else "FAIL"
            print(f"  [{tag}] part_{idx:03d}: {msg}")
            if ok:
                completed += 1
            else:
                failed += 1

    print(f"\n{completed} succeeded, {failed} failed — files in: {out_dir}")


if __name__ == "__main__":
    main()
