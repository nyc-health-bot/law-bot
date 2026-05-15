"""Shared utilities for NYC Administrative Code Title 17 scraping."""

import html as html_module
import re
import time
import urllib.request

BASE = "https://nycadmincode.readthedocs.io"
TITLE_URL = BASE + "/t17/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
DELAY = 1.5

# (number, title, url)
CHAPTERS = [
    ("1",  "DEPARTMENT OF HEALTH AND MENTAL HYGIENE",
            BASE + "/t17/c01/index.html"),
    ("2",  "MEDICAL EXAMINER",
            BASE + "/t17/c02/index.html"),
    ("3",  "LICENSES AND PERMITS",
            BASE + "/t17/c03/index.html"),
    ("4",  "STANDARDS GOVERNING THE PERFORMANCE OF STERILIZATIONS",
            BASE + "/t17/c04/index.html"),
    ("5",  "SMOKE-FREE AIR ACT",
            BASE + "/t17/c05/index.html"),
    ("6",  "DRUG TESTING OF SCHOOL SYSTEM CONVEYANCE DRIVERS",
            BASE + "/t17/c06/index.html"),
    ("7",  "REGULATION OF TOBACCO PRODUCTS",
            BASE + "/t17/c07/index.html"),
    ("8",  "ANIMAL SHELTERS AND STERILIZATION ACT",
            BASE + "/t17/c08/index.html"),
    ("9",  "LEAD-BASED PAINT IN DAY CARE FACILITIES",
            BASE + "/t17/c09/index.html"),
    ("10", "PRESCRIPTION DRUG DISCOUNT CARD ACT",
            BASE + "/t17/c10/index.html"),
    ("11", "NEIGHBOR NOTIFICATION OF PESTICIDE APPLICATION",
            BASE + "/t17/c11/index.html"),
    ("12", "PESTICIDE USE BY CITY AGENCIES",
            BASE + "/t17/c12/index.html"),
    ("13", "AVAILABILITY OF INFORMATION REGARDING DAY CARE SERVICES",
            BASE + "/t17/c13/index.html"),
    ("14", "LIMITS ON VOLATILE ORGANIC COMPOUND EMISSIONS IN CARPET AND CARPET CUSHION",
            BASE + "/t17/c14/index.html"),
    ("15", "FOOD SERVICE ESTABLISHMENTS",
            BASE + "/t17/c15/index.html"),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _strip_tags(fragment: str) -> str:
    """Strip HTML tags and decode entities; collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _pre_text(chunk: str) -> str:
    """Extract and clean all <pre> block content from a section chunk."""
    blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", chunk, re.DOTALL)
    if not blocks:
        return ""
    combined = " ".join(_strip_tags(b) for b in blocks)
    return re.sub(r"\s+", " ", combined).strip()


def _parse_sections(html_text: str) -> list:
    """Extract sections from a page that directly contains section divs."""
    html_text = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.DOTALL)
    html_text = re.sub(r"<style[^>]*>.*?</style>", " ", html_text, flags=re.DOTALL)

    main_m = re.search(r'role=["\']main["\']', html_text)
    content = html_text[main_m.start():] if main_m else html_text

    sec_id_re = re.compile(r'id=["\']section-(17-[\w.-]+)["\']', re.IGNORECASE)
    matches = list(sec_id_re.finditer(content))

    sections = []
    for i, m in enumerate(matches):
        raw_id = m.group(1)

        tag_start = content.rfind("<", 0, m.start())
        if i + 1 < len(matches):
            next_tag_start = content.rfind("<", 0, matches[i + 1].start())
        else:
            next_tag_start = len(content)

        chunk = content[tag_start:next_tag_start]

        # Section number from h2
        h2_m = re.search(r"<h2[^>]*>(.*?)</h2>", chunk, re.DOTALL)
        section_num = raw_id
        if h2_m:
            h2_text = re.sub(r"<[^>]+>", "", h2_m.group(1))
            h2_text = html_module.unescape(h2_text).strip()
            sec_m = re.match(r"Section\s+(17-[\d]+(?:\.[\d]+)*)", h2_text, re.IGNORECASE)
            if sec_m:
                section_num = sec_m.group(1)

        # Law text is in <pre> blocks
        raw_text = _pre_text(chunk)
        if not raw_text:
            continue

        title = ""
        body = raw_text

        # Format: §  17-501 Short title. Body of section...
        # Some sections have an asterisk annotation: * §  17-301 Title. Body...
        title_m = re.match(
            r"\s*(?:\*\s*)?§\s*[\d]+(?:[-.][\d]+)*\s+([^.]+)\.\s+(.*)",
            raw_text,
            re.DOTALL,
        )
        if title_m:
            title = title_m.group(1).strip()
            body = title_m.group(2).strip()
        else:
            prefix_m = re.match(r"\s*(?:\*\s*)?§\s*[\d]+(?:[-.][\d]+)*\s+", raw_text)
            if prefix_m:
                body = raw_text[prefix_m.end():].strip()

        sections.append({"section": section_num, "title": title, "text": body})

    return sections


def _find_subchapter_urls(html_text: str, chapter_base_url: str) -> list[str]:
    """Return absolute URLs for subchapter pages linked from a chapter index."""
    base_dir = chapter_base_url.rsplit("/", 1)[0]
    raw_links = re.findall(r'href="(sch\d+/[^"]+)"', html_text)
    seen: set[str] = set()
    result = []
    for rel in raw_links:
        full = base_dir + "/" + rel
        if full not in seen:
            seen.add(full)
            result.append(full)
    return result


def parse_chapter(html_text: str, source_url: str, chapter_num: str, chapter_title: str) -> dict:
    """Parse a chapter HTML page (which may have inline sections or subchapters)."""
    sections = _parse_sections(html_text)

    # If this chapter has no direct sections, collect from subchapter pages
    if not sections:
        sub_urls = _find_subchapter_urls(html_text, source_url)
        for sub_url in sub_urls:
            print(f"    [subchapter] {sub_url}")
            try:
                sub_html = fetch(sub_url)
                time.sleep(DELAY)
                sections.extend(_parse_sections(sub_html))
            except Exception as e:
                print(f"      ERROR: {e}")

    # Deduplicate by section number — keep the entry with the longest text
    seen: dict[str, dict] = {}
    for s in sections:
        k = s["section"]
        if k not in seen or len(s["text"]) > len(seen[k]["text"]):
            seen[k] = s

    def _sort_key(s: dict) -> tuple:
        parts = re.split(r"[-.]", s["section"])
        return tuple(int(p) if p.isdigit() else p for p in parts)

    sorted_sections = sorted(seen.values(), key=_sort_key)

    return {
        "type": "chapter",
        "number": chapter_num,
        "title": chapter_title,
        "source_url": source_url,
        "sections": sorted_sections,
    }


def scrape_chapter(number: str, title: str, url: str) -> dict:
    print(f"  [fetch] Chapter {number}: {url}")
    html_text = fetch(url)
    time.sleep(DELAY)
    result = parse_chapter(html_text, url, number, title)
    print(f"    -> {len(result['sections'])} sections")
    return result


def chapter_filename(number: str) -> str:
    return f"chapter_{int(number):02d}.json"
