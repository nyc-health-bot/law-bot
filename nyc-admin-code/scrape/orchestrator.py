"""
Scrape all NYC Administrative Code Title 17 chapters in parallel.

Each chapter is scraped by a worker.py subprocess and saved as
data/chapter_NN.json.

Usage:
    python orchestrator.py                        # all chapters, 4 workers
    python orchestrator.py --workers 3            # raise/lower concurrency
    python orchestrator.py --chapters 5 7 10      # specific chapters only
    python orchestrator.py --out-dir /path        # custom output directory
"""

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import CHAPTERS, chapter_filename

WORKER = Path(__file__).parent / "worker.py"
DEFAULT_OUT = Path(__file__).parent.parent / "data"


def _run_worker(number: str, title: str, url: str, out_dir: Path) -> tuple[str, str, bool]:
    result = subprocess.run(
        [
            sys.executable, str(WORKER),
            "--number", number,
            "--title", title,
            "--url", url,
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
    )
    ok = result.returncode == 0
    msg = (result.stdout.strip() or result.stderr.strip())[:160]
    return number, msg, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4, metavar="N")
    ap.add_argument("--chapters", nargs="*", type=int, metavar="N")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chapters = CHAPTERS
    if args.chapters:
        wanted = set(args.chapters)
        chapters = [c for c in CHAPTERS if int(c[0]) in wanted]
        print(f"Filtered to {len(chapters)} chapter(s): {sorted(wanted)}")

    to_run = []
    for number, title, url in chapters:
        out_file = out_dir / chapter_filename(number)
        if out_file.exists():
            print(f"  [skip] chapter_{int(number):02d}: already exists")
        else:
            to_run.append((number, title, url))

    if not to_run:
        print("Nothing to scrape — all chapters already present.")
        return

    print(f"Spawning {args.workers} worker(s) for {len(to_run)} chapter(s)…\n")

    completed = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_worker, num, title, url, out_dir): num
            for num, title, url in to_run
        }
        for fut in as_completed(futures):
            num, msg, ok = fut.result()
            tag = "OK  " if ok else "FAIL"
            print(f"  [{tag}] chapter_{int(num):02d}: {msg}")
            if ok:
                completed += 1
            else:
                failed += 1

    print(f"\n{completed} succeeded, {failed} failed — files in: {out_dir}")


if __name__ == "__main__":
    main()
