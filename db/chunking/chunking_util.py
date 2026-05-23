import re
import hashlib


def make_chunk_id(*parts: str) -> str:
    """Deterministic ID from any combination of identifying strings."""
    raw = "-".join(str(p) for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def split_text(text: str, max_chars: int) -> list[str]:
    """
    Split text progressively:
      1. Double newlines (paragraph breaks)
      2. Lettered subsections: 'a.', 'b.', etc.
      3. Brute-force at max_chars if still too long
    """
    if len(text) <= max_chars:
        return [text]

    parts = re.split(r"\n\n|(?<=\s)(?=[a-z]\.\s)", text)
    chunks, current = [], ""

    for part in parts:
        if len(current) + len(part) + 1 <= max_chars:
            current += (" " if current else "") + part
        else:
            if current:
                chunks.append(current.strip())
            if len(part) > max_chars:
                start = 0
                while start < len(part):
                    end = start + max_chars
                    if end >= len(part):
                        chunks.append(part[start:].strip())
                        break
                    # Back up to the last word boundary so we never split mid-word
                    while end > start and not part[end].isspace():
                        end -= 1
                    if end == start:
                        end = start + max_chars  # no space found; force-split
                    chunks.append(part[start:end].strip())
                    start = end
                current = ""
            else:
                current = part

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c]


def make_chunks(
    title: str,
    body: str,
    metadata: dict,
    id_parts: list[str],
    max_chars: int = 2000,
    min_chars: int = 100,
) -> list[dict]:
    """
    General chunking function for any legal code section.

    Args:
        title:     Section title, prepended to every chunk.
        body:      Section body text to split.
        metadata:  Base metadata dict — chunk-specific fields are merged in.
        id_parts:  List of strings used to build a deterministic chunk ID.
        max_chars: Max characters per chunk.
        min_chars: Skip sections shorter than this.

    Returns:
        List of chunk dicts ready for Pinecone upsert.
    """
    if not title or not body:
        return []

    full_text = f"{title}\n\n{body}"
    if len(full_text) < min_chars:
        return []

    parts = split_text(body, max_chars)  # split body only, title prepended to each part
    chunks = []

    for i, part in enumerate(parts):
        chunk_text = f"{title}\n\n{part}"
        chunks.append({
            "id": make_chunk_id(*id_parts, str(i)),
            "text": chunk_text,
            "metadata": {
                **metadata,
                "part_index": i,
                "char_count": len(chunk_text),
                "text": chunk_text,
            },
        })

    return chunks