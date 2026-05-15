from chunking.chunking_util import make_chunks
import json

def get_chunks(sanitary_code_path, max_chars=2000):
    chunks = []
    for file_path in sanitary_code_path.iterdir():
        if file_path.suffix != '.json':
            continue
        data = json.loads(file_path.read_text(encoding='utf-8', errors='replace'))
        for subpart in data.get("subparts", []):
            for section in subpart.get("sections", []):
                chunks.extend(make_chunks(
                    title=section.get("title", "").strip(),
                    body=section.get("body", "").strip(),  # note: 'body' not 'text'
                    metadata={
                        "code": "NYS Sanitary Code",
                        "part_title": data.get("title", ""),
                        "part_url": data.get("url", ""),
                        "subpart_title": subpart.get("title", ""),
                        "section": section.get("section", ""),
                        "section_title": section.get("title", ""),
                        "label": section.get("label", ""),
                        "source_url": section.get("source_url", ""),
                    },
                    id_parts=["nys-sanitary", data.get("title", ""), section.get("section", "")],
                    max_chars=max_chars,
                ))
    return chunks