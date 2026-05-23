"""
Generates ui/data/{code}.json files mapping section number → full section text.
Run from the repo root: python data/generate_section_data.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "ui" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

_SUBSEC = re.compile(r'^\s*\([a-zA-Z0-9]+\)')
_SENTENCE_END = re.compile(r'[.!?:;]\s*$')


def clean_page_numbers(text: str) -> str:
    lines = text.split("\n")
    # Pass 1: remove page number lines (bare digits)
    lines = [l for l in lines if not re.match(r"^\s*\d+\s*$", l)]
    # Pass 2: remove blank lines that appear mid-sentence
    result = []
    for line in lines:
        if not line.strip():
            last = next((l for l in reversed(result) if l.strip()), "")
            if last and not _SENTENCE_END.search(last.rstrip()):
                continue  # blank line is a page-break artifact, not a paragraph break
        result.append(line)
    return "\n".join(result)


def reflow_nyc_health(text: str) -> str:
    """Join PDF soft-wrap line breaks while preserving subsection-start newlines."""
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
        elif _SUBSEC.match(stripped):
            # Subsection marker — always its own line (keep original indentation)
            out.append(line)
        elif out and out[-1].strip() and not _SENTENCE_END.search(out[-1].rstrip()):
            # Previous line didn't end a sentence → soft wrap, join
            out[-1] = out[-1].rstrip() + " " + stripped
        else:
            out.append(line)
    return "\n".join(out)


def format_admin_body(body: str) -> str:
    """Break flat NYC Admin Code text at lettered subdivisions, numbered items, and roman-numeral sub-items."""
    # Lettered subdivisions (a. b. c. …) after sentence end
    body = re.sub(r'\. ([a-n])\. (?=[A-Z])', lambda m: '.\n' + m.group(1) + '. ', body)
    # Numbered items: after colon or period, digit, period, open-quote
    body = re.sub(r'([:.]) (\d+)\. "', lambda m: m.group(1) + '\n   ' + m.group(2) + '. "', body)
    # Roman-numeral sub-items
    _roman = r'[ivxlcdm]+'
    body = re.sub(r'; and \((' + _roman + r')\) ', r'; and\n      (\1) ', body)
    body = re.sub(r'; or \((' + _roman + r')\) ', r'; or\n      (\1) ', body)
    body = re.sub(r'; \((' + _roman + r')\) ', r';\n      (\1) ', body)
    body = re.sub(r': \((' + _roman + r')\) ', r':\n      (\1) ', body)
    return body.strip()


def format_nys_body(body: str, section: str, title: str) -> str:
    """Strip repeated section header and insert newlines at subsection markers."""
    # NYS bodies often open with "§num Title." — strip it to avoid duplication
    for prefix in (f"{section} {title}.", f"{section} {title}", section):
        if body.startswith(prefix):
            body = body[len(prefix):].lstrip(" .")
            break

    def _break(m):
        punct, content = m.group(1), m.group(2)
        if re.fullmatch(r"\d+", content):
            indent = "    "   # numbered items — 4 spaces
        elif len(content) >= 2 and re.fullmatch(r"[ivxlcdm]+", content):
            indent = "        "  # roman numerals — 8 spaces
        else:
            indent = ""          # single letter — top level
        return f"{punct}\n{indent}({content}) "

    # Break before (a)/(b)/... (1)/(2)/... (ii)/(iii)/... after sentence punctuation.
    # Optional "or"/"and" before the marker (e.g. "; or (5) persons...").
    # Guard: content must be a plain letter, integer, or roman numeral (no decimals/symbols).
    body = re.sub(
        r'([.:;])\s+(?:(?:or|and)\s+)?\(([a-z0-9]+)\)\s+',
        _break,
        body,
    )
    return body.strip()


def full_text(title: str, body: str) -> str:
    return f"{title}\n\n{body}".strip()


# --- NYC Health Code + Rules of the City of New York ---
nyc_health = {}
nyc_rules = {}
for f in sorted((ROOT / "data/scrapers/nyc-health-code/data").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    target = nyc_rules if data.get("type") == "chapter" else nyc_health
    for section in data.get("sections", []):
        sec_num = section.get("section", "").strip()
        if not sec_num:
            continue
        body = reflow_nyc_health(clean_page_numbers(section.get("text", "").strip()))
        target[sec_num] = full_text(section.get("title", "").strip(), body)

(OUT_DIR / "nyc-health-code.json").write_text(
    json.dumps(nyc_health, ensure_ascii=False, indent=None), encoding="utf-8"
)
print(f"NYC Health Code: {len(nyc_health)} sections")

(OUT_DIR / "nyc-rules.json").write_text(
    json.dumps(nyc_rules, ensure_ascii=False, indent=None), encoding="utf-8"
)
print(f"Rules of the City of New York: {len(nyc_rules)} sections")


# --- NYC Admin Code ---
nyc_admin = {}
for f in sorted((ROOT / "data/scrapers/nyc-admin-code/data").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    for section in data.get("sections", []):
        sec_num = section.get("section", "").strip()
        if not sec_num:
            continue
        body = format_admin_body(section.get("text", "").strip())
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
for f in sorted((ROOT / "data/scrapers/nys-sanitary-code/data").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    for section in _iter_nys_sections(data):
        sec_num = section.get("section", "").strip()
        if not sec_num:
            continue
        title = section.get("title", "").strip()
        body = format_nys_body(section.get("body", "").strip(), sec_num, title)
        nys_sanitary[sec_num] = full_text(title, body)

(OUT_DIR / "nys-sanitary-code.json").write_text(
    json.dumps(nys_sanitary, ensure_ascii=False, indent=None), encoding="utf-8"
)
print(f"NYS Sanitary Code: {len(nys_sanitary)} sections")

print(f"\nWrote JSON files to {OUT_DIR}")
