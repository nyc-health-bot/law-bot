"""
Download and extract all NYC Health Code articles and Commissioner's Regulation chapters in parallel.

Each PDF is processed by a separate worker.py subprocess and saved as:
  data/article_001.json, data/article_081.json, ...
  data/chapter_01.json,  data/chapter_23.json,  ...

Usage:
    python orchestrator.py                        # all articles + chapters, 6 workers
    python orchestrator.py --workers 4
    python orchestrator.py --only articles        # articles only
    python orchestrator.py --only chapters        # chapters only
    python orchestrator.py --out-dir /path/to/data
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import ARTICLES, CHAPTERS, article_filename, chapter_filename, parse_sections

WORKER = Path(__file__).parent / "worker.py"
DEFAULT_OUT = Path(__file__).parent.parent / "data"


def _run_worker(doc_type: str, number: str, title: str, path: str, out_dir: Path) -> tuple:
    result = subprocess.run(
        [
            sys.executable, str(WORKER),
            "--type", doc_type,
            "--number", number,
            "--title", title,
            "--path", path,
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
    )
    ok = result.returncode == 0
    msg = (result.stdout.strip() or result.stderr.strip())[:120]
    label = f"{doc_type} {number}"
    return label, msg, ok


def _build_queue(out_dir: Path, only: str):
    queue = []

    if only != "chapters":
        for number, title, path in ARTICLES:
            fname = article_filename(number)
            if (out_dir / fname).exists():
                print(f"  [skip] {fname}")
            else:
                queue.append(("article", number, title, path))

    if only != "articles":
        for number, title, path in CHAPTERS:
            fname = chapter_filename(number)
            if (out_dir / fname).exists():
                print(f"  [skip] {fname}")
            else:
                queue.append(("chapter", number, title, path))

    return queue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6, metavar="N")
    ap.add_argument("--only", choices=["articles", "chapters"], default=None,
                    help="Scrape only articles or only chapters (default: both)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    only = args.only or "both"
    total_articles = len(ARTICLES) if only != "chapters" else 0
    total_chapters = len(CHAPTERS) if only != "articles" else 0
    print(f"NYC Health Code — {total_articles} articles, {total_chapters} chapters\n")

    queue = _build_queue(out_dir, only)

    if not queue:
        print("Nothing to download — all files already present.")
        _reparse(out_dir)
        return

    print(f"\nSpawning {args.workers} worker(s) for {len(queue)} file(s)…\n")

    completed = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_worker, *item, out_dir): item
            for item in queue
        }
        for fut in as_completed(futures):
            label, msg, ok = fut.result()
            tag = "OK  " if ok else "FAIL"
            print(f"  [{tag}] {label}: {msg}")
            if ok:
                completed += 1
            else:
                failed += 1

    print(f"\n{completed} succeeded, {failed} failed")

    _reparse(out_dir)


def _reparse(out_dir: Path):
    print(f"\nParsing sections in {out_dir}…")
    files = sorted(out_dir.glob("*.json"))
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["sections"] = parse_sections(data.get("text", ""))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {path.name}: {len(data['sections'])} sections")
    print(f"Done — {len(files)} file(s) in: {out_dir}")


if __name__ == "__main__":
    main()
