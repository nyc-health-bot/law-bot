import json
from pathlib import Path

def fix_split_titles(data: dict) -> dict:
    for section in data.get("sections", []):
        title = section.get("title", "").strip()
        text = section.get("text", "").strip()

        if title and title[-1] not in ".,:;?!)":
            lines = text.split("\n", 1)
            first_line = lines[0].strip()
            if first_line and (first_line[0].islower() or (len(first_line.split()) <= 2 and first_line.endswith("."))):
                section["title"] = f"{title} {first_line}"
                section["text"] = lines[1].strip() if len(lines) > 1 else ""

    return data

# run over all files
path = Path(r"/scraping\nyc-health-code\data")
for file_path in path.glob("*.json"):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = fix_split_titles(data)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)