"""
Generates ui/data/{code}.json files mapping section number → full section text.
Run from the repo root: python3 generate_section_data.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "ui" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def clean_page_numbers(text: str) -> str:
    lines = text.split("\n")
    # Pass 1: remove page number lines (bare digits)
    lines = [l for l in lines if not re.match(r"^\s*\d+\s*$", l)]
    # Pass 2: remove blank lines that appear mid-sentence
    result = []
    for line in lines:
        if not line.strip():
            last = next((l for l in reversed(result) if l.strip()), "")
            if last and not re.search(r"[.!?:;]\s*$", last.rstrip()):
                continue  # blank line is a page-break artifact, not a paragraph break
        result.append(line)
    return "\n".join(result)


def full_text(title: str, body: str) -> str:
    return f"{title}\n\n{body}".strip()


# --- NYC Health Code ---
nyc_health = {}
for f in sorted((ROOT / "scraping/nyc-health-code/data").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    for section in data.get("sections", []):
        sec_num = section.get("section", "").strip()
        if not sec_num:
            continue
        body = clean_page_numbers(section.get("text", "").strip())
        nyc_health[sec_num] = full_text(section.get("title", "").strip(), body)

(OUT_DIR / "nyc-health-code.json").write_text(
    json.dumps(nyc_health, ensure_ascii=False, indent=None), encoding="utf-8"
)
print(f"NYC Health Code: {len(nyc_health)} sections")


# --- NYC Admin Code ---
nyc_admin = {}
for f in sorted((ROOT / "scraping/nyc-admin-code/data").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    for section in data.get("sections", []):
        sec_num = section.get("section", "").strip()
        if not sec_num:
            continue
        body = section.get("text", "").strip()
        nyc_admin[sec_num] = full_text(section.get("title", "").strip(), body)

(OUT_DIR / "nyc-admin-code.json").write_text(
    json.dumps(nyc_admin, ensure_ascii=False, indent=None), encoding="utf-8"
)
print(f"NYC Admin Code: {len(nyc_admin)} sections")


# --- NYS Sanitary Code ---
def _iter_nys_sections(data):
    for subpart in data.get("subparts", []):
        for section in subpart.get("sections", []):
            yield section
    for section in data.get("sections", []):
        yield section

nys_sanitary = {}
for f in sorted((ROOT / "scraping/nys-sanitary-code/data").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    for section in _iter_nys_sections(data):
        sec_num = section.get("section", "").strip()
        if not sec_num:
            continue
        body = section.get("body", "").strip()
        nys_sanitary[sec_num] = full_text(section.get("title", "").strip(), body)

(OUT_DIR / "nys-sanitary-code.json").write_text(
    json.dumps(nys_sanitary, ensure_ascii=False, indent=None), encoding="utf-8"
)
print(f"NYS Sanitary Code: {len(nys_sanitary)} sections")

print(f"\nWrote JSON files to {OUT_DIR}")
