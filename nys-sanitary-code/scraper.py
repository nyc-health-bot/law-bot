"""
NYS Sanitary Code scraper — govt.westlaw.com
Produces a JSON file structured for later PDF/token conversion.

Usage:
    python scraper.py                  # full scrape
    python scraper.py --test           # Part 1 only
    python scraper.py --parts 1 2 5   # specific parts
"""

import json
import re
import sys
import time
import urllib.request
import urllib.parse
import html as html_module
from pathlib import Path

BASE = "https://govt.westlaw.com"
CHAPTER_URL = (
    BASE + "/nycrr/Browse/Home/NewYork/UnofficialNewYorkCodesRulesandRegulations"
    "?guid=Id86117a0b65511ddb903a4af59fec65a"
    "&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
DELAY = 1.0  # seconds between requests


def fetch(url: str) -> str:
    url = html_module.unescape(url)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_toc_links(html: str) -> list[dict]:
    """Return [{text, url}] from the co_genericWhiteBox list."""
    items = []
    # Find the main list
    box = re.search(r'<ul class="co_genericWhiteBox">(.*?)</ul>', html, re.DOTALL)
    if not box:
        return items
    for m in re.finditer(
        r'<a[^>]+href="(/nycrr/[^"]+)"[^>]*>([^<]+)</a>', box.group(1)
    ):
        href, text = m.group(1), m.group(2).strip()
        items.append({"text": text, "url": BASE + html_module.unescape(href)})
    return items


def extract_document_text(html: str) -> dict:
    """Extract section number, title, and body text from a Document page."""
    col_start = html.find('id="co_contentColumn"')
    if col_start < 0:
        return {"section": "", "title": "", "body": ""}

    chunk = html[col_start : col_start + 120_000]
    chunk = re.sub(r"<script[^>]*>.*?</script>", " ", chunk, flags=re.DOTALL)
    chunk = re.sub(r"<style[^>]*>.*?</style>", " ", chunk, flags=re.DOTALL)

    text = re.sub(r"<[^>]+>", " ", chunk)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    # The boilerplate header repeats the citation twice in a row: "CRR-NY X.X CRR-NY X.X"
    # Actual content follows that consecutive pair.
    pair_m = re.search(
        r"\d+ CRR-NY [\d\.\-]+ \d+ CRR-NY ([\d\.\-]+)\s+(.*)", text, re.DOTALL
    )
    if pair_m:
        body = pair_m.group(2).strip()
        # Strip trailing footer starting with "10 CRR-NY..."
        body = re.sub(r"\s*\d+ CRR-NY [\d\.\-]+\s+Current through.*$", "", body, flags=re.DOTALL).strip()
    else:
        body = text

    # Extract section number and title from body start: e.g. "1.1 Definitions."
    sec_m = re.match(r"([\d\.\-]+)\s+([^.\n]+\.?)", body)
    section = pair_m.group(1) if pair_m else (sec_m.group(1) if sec_m else "")
    title = sec_m.group(2).strip().rstrip(".") if sec_m else ""

    return {"section": section, "title": title, "body": body}


def scrape_section(url: str, label: str) -> dict:
    print(f"      [section] {label}")
    try:
        html = fetch(url)
        time.sleep(DELAY)
        doc = extract_document_text(html)
    except Exception as e:
        print(f"        ERROR: {e}")
        time.sleep(DELAY)
        doc = {"section": "", "title": label, "body": f"[fetch error: {e}]"}
    doc["source_url"] = url
    doc["label"] = label
    return doc


def scrape_subpart(item: dict) -> dict:
    text, url = item["text"], item["url"]
    print(f"    [subpart] {text}")
    html = fetch(url)
    time.sleep(DELAY)

    children = extract_toc_links(html)

    # If no child TOC links it may itself be a document
    if not children:
        doc = extract_document_text(html)
        doc["source_url"] = url
        doc["label"] = text
        return {"title": text, "url": url, "sections": [doc]}

    sections = []
    for child in children:
        # Document links go to /nycrr/Document/...
        if "/Document/" in child["url"]:
            sections.append(scrape_section(child["url"], child["text"]))
        else:
            # Nested subpart — recurse one level
            sub = scrape_subpart(child)
            sections.extend(sub.get("sections", []))

    return {"title": text, "url": url, "sections": sections}


def scrape_part(item: dict) -> dict:
    text, url = item["text"], item["url"]
    print(f"  [part] {text}")
    html = fetch(url)
    time.sleep(DELAY)

    children = extract_toc_links(html)
    subparts = []
    for child in children:
        if "/Document/" in child["url"]:
            # Part notes / direct document
            subparts.append(
                {"title": child["text"], "url": child["url"], "sections": [
                    scrape_section(child["url"], child["text"])
                ]}
            )
        else:
            subparts.append(scrape_subpart(child))

    return {"title": text, "url": url, "subparts": subparts}


def main():
    test_mode = "--test" in sys.argv
    part_filter: set[int] = set()
    if "--parts" in sys.argv:
        idx = sys.argv.index("--parts")
        part_filter = {int(x) for x in sys.argv[idx + 1 :] if x.isdigit()}

    print("[chapter] Fetching chapter TOC…")
    html = fetch(CHAPTER_URL)
    parts_list = extract_toc_links(html)
    print(f"  Found {len(parts_list)} parts")

    if test_mode:
        parts_list = parts_list[:1]  # Part 1 only
        print("  TEST MODE: scraping Part 1 only")
    elif part_filter:
        parts_list = [
            p for p in parts_list
            if any(f"Part {n} " in p["text"] or f"Part {n}." in p["text"]
                   for n in part_filter)
        ]

    result = {
        "title": "NYS Sanitary Code — Title 10, Chapter I",
        "source": CHAPTER_URL,
        "parts": [],
    }

    for item in parts_list:
        if "(Repealed)" in item["text"]:
            result["parts"].append(
                {"title": item["text"], "url": item["url"], "subparts": [], "repealed": True}
            )
            continue
        result["parts"].append(scrape_part(item))

    suffix = "_test" if test_mode else ""
    out = Path(f"nys_sanitary_code{suffix}.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()