"""Shared scraping primitives for the NYS Sanitary Code scrapers."""

import html as html_module
import re
import time
import urllib.request

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
DELAY = 1.0


def fetch(url: str) -> str:
    url = html_module.unescape(url)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_toc_links(html: str) -> list[dict]:
    items = []
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
    col_start = html.find('id="co_contentColumn"')
    if col_start < 0:
        return {"section": "", "title": "", "body": ""}

    chunk = html[col_start : col_start + 120_000]
    chunk = re.sub(r"<script[^>]*>.*?</script>", " ", chunk, flags=re.DOTALL)
    chunk = re.sub(r"<style[^>]*>.*?</style>", " ", chunk, flags=re.DOTALL)

    text = re.sub(r"<[^>]+>", " ", chunk)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    pair_m = re.search(
        r"\d+ CRR-NY [\d\.\-]+ \d+ CRR-NY ([\d\.\-]+)\s+(.*)", text, re.DOTALL
    )
    if pair_m:
        body = pair_m.group(2).strip()
        body = re.sub(
            r"\s*\d+ CRR-NY [\d\.\-]+\s+Current through.*$", "", body, flags=re.DOTALL
        ).strip()
    else:
        body = text

    sec_m = re.match(r"([\d\.\-]+)\s+([^.\n]+\.?)", body)
    section = pair_m.group(1) if pair_m else (sec_m.group(1) if sec_m else "")
    title = sec_m.group(2).strip().rstrip(".") if sec_m else ""

    return {"section": section, "title": title, "body": body}


def scrape_section(url: str, label: str) -> dict:
    print(f"        [section] {label}")
    try:
        html = fetch(url)
        time.sleep(DELAY)
        doc = extract_document_text(html)
    except Exception as e:
        print(f"          ERROR: {e}")
        time.sleep(DELAY)
        doc = {"section": "", "title": label, "body": f"[fetch error: {e}]"}
    doc["source_url"] = url
    doc["label"] = label
    return doc


def scrape_subpart(item: dict) -> dict:
    text, url = item["text"], item["url"]
    print(f"      [subpart] {text}")
    html = fetch(url)
    time.sleep(DELAY)

    children = extract_toc_links(html)

    if not children:
        doc = extract_document_text(html)
        doc["source_url"] = url
        doc["label"] = text
        return {"title": text, "url": url, "sections": [doc]}

    sections = []
    for child in children:
        if "/Document/" in child["url"]:
            sections.append(scrape_section(child["url"], child["text"]))
        else:
            sub = scrape_subpart(child)
            sections.extend(sub.get("sections", []))

    return {"title": text, "url": url, "sections": sections}


def scrape_part(item: dict) -> dict:
    text, url = item["text"], item["url"]
    print(f"    [part] {text}")
    html = fetch(url)
    time.sleep(DELAY)

    children = extract_toc_links(html)
    subparts = []
    for child in children:
        if "/Document/" in child["url"]:
            subparts.append(
                {
                    "title": child["text"],
                    "url": child["url"],
                    "sections": [scrape_section(child["url"], child["text"])],
                }
            )
        else:
            subparts.append(scrape_subpart(child))

    return {"title": text, "url": url, "subparts": subparts}
