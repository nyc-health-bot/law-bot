import json
import os
import re
import time

import numpy as np
import requests

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GOOGLE_API_KEY")
PINECONE_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_HOST = os.environ.get("PINECONE_HOST")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
PROMPT_BUCKET = os.environ.get("PROMPT_BUCKET")

# --- PROMPT CACHE (TTL 60s — update prompts via gsutil cp, no redeploy needed) ---
_prompt_cache: dict[str, tuple[str, float]] = {}
_PROMPT_TTL = 60


def _fetch_prompt(name: str) -> str:
    token_resp = requests.get(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
        timeout=5,
    )
    token = token_resp.json()["access_token"]
    resp = requests.get(
        f"https://storage.googleapis.com/storage/v1/b/{PROMPT_BUCKET}/o/{name}?alt=media",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.text


def _get_prompt(name: str) -> str:
    now = time.time()
    if name in _prompt_cache and now - _prompt_cache[name][1] < _PROMPT_TTL:
        return _prompt_cache[name][0]
    text = _fetch_prompt(name)
    _prompt_cache[name] = (text, now)
    return text

EMBED_MODEL = "models/gemini-embedding-001"
EMBED_DIM = 1024


# --- EMBEDDING ---

def _truncate_vector(vector):
    truncated = np.array(vector[:EMBED_DIM])
    norm = np.linalg.norm(truncated)
    return (truncated / norm).tolist()


def _embed(texts: list[str], task_type: str = "RETRIEVAL_QUERY") -> list[list[float]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/{EMBED_MODEL}:batchEmbedContents"
    payload = {
        "requests": [
            {
                "model": EMBED_MODEL,
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
            }
            for t in texts
        ]
    }
    resp = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY}, json=payload, timeout=30)
    resp.raise_for_status()
    return [_truncate_vector(item["values"]) for item in resp.json()["embeddings"]]


# --- PINECONE ---

def _pinecone_query(query_text: str, max_sections: int = 10) -> list[dict]:
    vector = _embed([query_text])[0]
    resp = requests.post(
        f"{PINECONE_HOST}/query",
        headers={"Api-Key": PINECONE_KEY, "Content-Type": "application/json"},
        json={"vector": vector, "topK": 30, "includeMetadata": True},
    )
    resp.raise_for_status()
    matches = [m for m in resp.json().get("matches", []) if m.get("score", 0) > 0.5]
    print(f"Pinecone returned {len(matches)} matches above threshold")

    # Rank unique sections by their best chunk score, cap at max_sections
    section_best = {}
    for m in matches:
        meta = m["metadata"]
        key = (meta.get("code", ""), meta.get("section", ""))
        score = m.get("score", 0)
        if key not in section_best or score > section_best[key]:
            section_best[key] = score

    top_sections = set(
        sorted(section_best, key=lambda k: section_best[k], reverse=True)[:max_sections]
    )
    return [m for m in matches if (m["metadata"].get("code", ""), m["metadata"].get("section", "")) in top_sections]


# --- GEMINI HELPERS ---

def _gemini_generate(payload: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}"
    for attempt in range(5):
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Gemini request failed after 5 retries")


def _filter_citations(summary: str, valid_sections: set) -> str:
    """Strip §-citations from summary that have no corresponding retrieved source."""
    def clean(m):
        kept = [s for s in re.findall(r'§([\d.\-]+)', m.group(0)) if s in valid_sections]
        return '(' + ', '.join(f'§{s}' for s in kept) + ')' if kept else ''
    return re.sub(r'\((?:§[\d.\-]+(?:,\s*)?)+\)', clean, summary).strip()


# --- PIPELINE ---

def structure_question(raw_user_query: str) -> str:
    prompt = _get_prompt("structure_question.txt").format(raw_user_query=raw_user_query)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    out = _gemini_generate(payload)
    return out["candidates"][0]["content"]["parts"][0]["text"]


def structure_response(user_query: str, pinecone_matches: list[dict]) -> dict:
    """
    Returns {"summary": str, "citations": [{anchor, section, full_title, section_title, url, text, relevant_passages, cited_in_summary}, ...]}
    Matches with the same code+section are merged into one citation.
    anchor is a unique HTML id (e.g. "citation-0") for same-page linking.
    section is the bare section number (e.g. "81.07") so the UI can map §-references in the summary to anchors.
    cited_in_summary is True if the section is referenced inline in the summary (§XX.XX pattern).
    """
    # Group matches by (code, section), preserving first-seen order
    seen = {}
    for m in pinecone_matches:
        meta = m["metadata"]
        key = (meta.get("code", ""), meta.get("section", ""))
        if key not in seen:
            seen[key] = {
                "full_title": f"{key[0]} §{key[1]}".strip(" §"),
                "code": key[0],
                "section_title": meta.get("section_title", ""),
                "url": meta.get("source_url", ""),
                "texts": [],
            }
        seen[key]["texts"].append(meta.get("text", ""))

    sources = []
    section_numbers = []
    context_bits = []
    for i, (key, entry) in enumerate(seen.items()):
        combined_text = "\n\n".join(entry["texts"])
        sources.append({
            "full_title": entry["full_title"],
            "code": entry["code"],
            "section_title": entry["section_title"],
            "url": entry["url"],
            "text": combined_text,
        })
        section_numbers.append(key[1])
        context_bits.append(f"[{i}] {entry['full_title']}\nURL: {entry['url']}\nTEXT: {combined_text}")

    context_str = "\n\n---\n\n".join(context_bits)

    prompt = _get_prompt("structure_response.txt").format(
        user_query=user_query,
        context_str=context_str,
        num_sources=len(sources),
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "relevant_passages": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["index", "relevant_passages"],
                        },
                    },
                },
                "required": ["summary", "citations"],
            },
        },
    }

    out = _gemini_generate(payload)
    gemini_out = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])

    passage_map = {item["index"]: item.get("relevant_passages", []) for item in gemini_out["citations"]}
    summary = _filter_citations(gemini_out["summary"], set(section_numbers))
    cited_sections = set(re.findall(r'§([\d.\-]+)', summary))

    citations = [
        {
            "anchor": f"citation-{i}",
            "section": section_numbers[i],
            "code": sources[i]["code"],
            "full_title": sources[i]["full_title"],
            "section_title": sources[i]["section_title"],
            "url": sources[i]["url"],
            "text": sources[i]["text"],
            "relevant_passages": passage_map.get(i, []),
            "cited_in_summary": section_numbers[i] in cited_sections,
        }
        for i in range(len(sources))
    ]

    return {"summary": summary, "citations": citations}


# --- CLOUD FUNCTION ENTRY POINT ---

def handle_request(request):
    cors_headers = {"Access-Control-Allow-Origin": ALLOWED_ORIGIN}

    if request.method == "OPTIONS":
        return ("", 204, {
            **cors_headers,
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    try:
        user_input = request.get_json().get("prompt")

        technical_query = structure_question(user_input)
        matches = _pinecone_query(technical_query)

        if not matches:
            return (
                json.dumps({"answer": {"summary": "I couldn't find any relevant sections for that question.", "citations": []}}),
                200,
                {**cors_headers, "Content-Type": "application/json"},
            )

        answer = structure_response(user_input, matches)
        return (
            json.dumps({"answer": answer}),
            200,
            {**cors_headers, "Content-Type": "application/json"},
        )

    except Exception as e:
        return (
            json.dumps({"error": str(e)}),
            500,
            {**cors_headers, "Content-Type": "application/json"},
        )
