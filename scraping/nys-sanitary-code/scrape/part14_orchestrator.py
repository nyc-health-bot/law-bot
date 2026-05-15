"""
Scrape Part 14 (Food Service Establishments) by subpart in parallel.

Each subpart is scraped by a separate worker_subpart.py subprocess and saved as
data/part_14_1.json, data/part_14_2.json, etc.

Usage:
    python part14_orchestrator.py
    python part14_orchestrator.py --workers 4
    python part14_orchestrator.py --out-dir /path/to/data
"""

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import fetch, extract_toc_links, CHAPTER_URL

WORKER = Path(__file__).parent / "worker_subpart.py"
DEFAULT_OUT = Path(__file__).parent.parent / "data"


def _run_worker(index: int, item: dict, out_dir: Path) -> tuple:
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
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[toc] Fetching chapter TOC…")
    html = fetch(CHAPTER_URL)
    parts = extract_toc_links(html)
    part14 = next((p for p in parts if "Part 14" in p["text"]), None)
    if not part14:
        print("ERROR: Part 14 not found in TOC")
        sys.exit(1)

    print(f"[part 14] Fetching subpart list…")
    html = fetch(part14["url"])
    subparts = extract_toc_links(html)
    print(f"  Found {len(subparts)} subparts")

    to_run = []
    for i, item in enumerate(subparts):
        out_file = out_dir / f"part_14_{i + 1}.json"
        if out_file.exists():
            print(f"  [skip] part_14_{i + 1}: already exists")
        else:
            to_run.append((i + 1, item))

    if not to_run:
        print("  Nothing to scrape — all subparts already present.")
        return

    print(f"  Spawning {args.workers} worker(s) for {len(to_run)} subpart(s)…\n")

    completed = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_worker, i, item, out_dir): item
            for i, item in to_run
        }
        for fut in as_completed(futures):
            idx, msg, ok = fut.result()
            tag = "OK  " if ok else "FAIL"
            print(f"  [{tag}] part_14_{idx}: {msg}")
            if ok:
                completed += 1
            else:
                failed += 1

    print(f"\n{completed} succeeded, {failed} failed — files in: {out_dir}")


if __name__ == "__main__":
    main()
