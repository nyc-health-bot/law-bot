from chunking.chunking_util import make_chunks
import json

def get_chunks(admin_code_path, max_chars=2000):
    chunks = []
    for file_path in admin_code_path.iterdir():
        if file_path.suffix != '.json':
            continue
        data = json.loads(file_path.read_text(encoding='utf-8', errors='replace'))
        for section in data.get("sections", []):
            chunks.extend(make_chunks(
                title=section.get("title", "").strip(),
                body=section.get("text", "").strip(),
                metadata={
                    "code": "NYC Admin Code",
                    "chapter_number": data.get("number", ""),
                    "chapter_title": data.get("title", ""),
                    "section": section.get("section", ""),
                    "section_title": section.get("title", ""),
                    "source_url": data.get("source_url", ""),
                },
                id_parts=["nyc-admin", data.get("number", ""), section.get("section", "")],
                max_chars=max_chars,
            ))
    return chunks