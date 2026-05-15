from chunking.chunking_util import make_chunks
import json

def _iter_sections(data):
    """Yield (subpart_title, section) for both file structures."""
    for subpart in data.get("subparts", []):
        for section in subpart.get("sections", []):
            yield subpart.get("title", ""), section
    for section in data.get("sections", []):
        yield "", section

def get_chunks(sanitary_code_path, max_chars=2000):
    chunks = []
    for file_path in sanitary_code_path.iterdir():
        if file_path.suffix != '.json':
            continue
        data = json.loads(file_path.read_text(encoding='utf-8', errors='replace'))
        for subpart_title, section in _iter_sections(data):
            chunks.extend(make_chunks(
                title=section.get("title", "").strip(),
                body=section.get("body", "").strip(),
                metadata={
                    "code": "NYS Sanitary Code",
                    "part_title": data.get("title", ""),
                    "part_url": data.get("url", ""),
                    "subpart_title": subpart_title,
                    "section": section.get("section", ""),
                    "section_title": section.get("title", ""),
                    "label": section.get("label", ""),
                    "source_url": section.get("source_url", ""),
                },
                id_parts=["nys-sanitary", data.get("title", ""), section.get("section", "")],
                max_chars=max_chars,
            ))
    return chunks
