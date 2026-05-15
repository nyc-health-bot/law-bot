# nyc_health_code.py
from chunking.chunking_util import make_chunks
import json
import re

def _clean_body(text: str) -> str:
    lines = text.split('\n')
    # Pass 1: remove page number lines (bare digits)
    lines = [l for l in lines if not re.match(r'^\s*\d+\s*$', l)]
    # Pass 2: remove blank lines that appear mid-sentence
    result = []
    for line in lines:
        if not line.strip():
            last = next((l for l in reversed(result) if l.strip()), '')
            if last and not re.search(r'[.!?:;]\s*$', last.rstrip()):
                continue  # blank line is a page-break artifact, not a paragraph break
        result.append(line)
    return '\n'.join(result)

def get_chunks(health_code_path, max_chars=2000):
    chunks = []
    for file_path in health_code_path.iterdir():
        if file_path.suffix != '.json':
            continue
        data = json.loads(file_path.read_text(encoding='utf-8', errors='replace'))
        for section in data.get("sections", []):
            chunks.extend(make_chunks(
                title=section.get("title", "").strip(),
                body=_clean_body(section.get("text", "").strip()),
                metadata={
                    "code": "NYC Health Code",
                    "article_number": data.get("number", ""),
                    "article_title": data.get("title", ""),
                    "section": section.get("section", ""),
                    "section_title": section.get("title", ""),
                    "source_url": data.get("source_url", ""),
                },
                id_parts=["nyc-health", data.get("number", ""), section.get("section", "")],
                max_chars=max_chars,
            ))
    return chunks