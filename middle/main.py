import json
import os
import re
import time
import requests
from dotenv import load_dotenv
from util import post, embed_fn
from pinecone import query


load_dotenv()
# --- CONFIGURATION (Load once) ---
GEMINI_KEY = os.environ.get("GOOGLE_API_KEY")
PINECONE_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_HOST = os.environ.get("PINECONE_HOST")  # URL from Pinecone dashboard

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _get_prompt(name: str) -> str:
    with open(os.path.join(_PROMPTS_DIR, name), encoding="utf-8") as f:
        return f.read()


def _filter_citations(summary: str, valid_sections: set) -> str:
    """Strip §-citations from summary that have no corresponding retrieved source."""
    def clean(m):
        kept = [s for s in re.findall(r'§([\d.\-]+)', m.group(0)) if s in valid_sections]
        return '(' + ', '.join(f'§{s}' for s in kept) + ')' if kept else ''
    return re.sub(r'\((?:§[\d.\-]+(?:,\s*)?)+\)', clean, summary).strip()


def _gemini_post(url, payload):
    for attempt in range(5):
        resp = post(url=url, json=payload)
        if resp.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("Gemini request failed after 5 retries")


def structure_question(raw_user_query):
    """
    Transforms plain English into a technical 'Legal Query' for better vector search.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}"
    prompt = _get_prompt("structure_question.txt").format(raw_user_query=raw_user_query)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    resp = _gemini_post(url=url, payload=payload)
    return resp.json()['candidates'][0]['content']['parts'][0]['text']


def get_values(technical_query):
    return query(technical_query)


def structure_response(user_query, pinecone_matches):
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
        meta = m['metadata']
        key = (meta.get('code', ''), meta.get('section', ''))
        if key not in seen:
            seen[key] = {
                "full_title": f"{key[0]} §{key[1]}".strip(" §"),
                "code": key[0],
                "section_title": meta.get('section_title', ''),
                "url": meta.get('source_url', ''),
                "texts": []
            }
        seen[key]["texts"].append(meta.get('text', ''))

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
            "text": combined_text
        })
        section_numbers.append(key[1])
        context_bits.append(f"[{i}] {entry['full_title']}\nURL: {entry['url']}\nTEXT: {combined_text}")

    context_str = "\n\n---\n\n".join(context_bits)

    gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}"
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
                                    "items": {"type": "string"}
                                }
                            },
                            "required": ["index", "relevant_passages"]
                        }
                    }
                },
                "required": ["summary", "citations"]
            }
        }
    }

    gen_resp = _gemini_post(url=gen_url, payload=payload)
    raw = gen_resp.json()['candidates'][0]['content']['parts'][0]['text']
    gemini_out = json.loads(raw)

    passage_map = {item['index']: item.get('relevant_passages', []) for item in gemini_out['citations']}

    summary = _filter_citations(gemini_out['summary'], set(section_numbers))
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


# --- MAIN HANDLER ---
def handle_request(request):
    # Standard CORS Preflight
    if request.method == 'OPTIONS':
        return ('', 204, {
            'Access-Control-Allow-Origin': 'https://your-username.github.io',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type'
        })

    try:
        user_input = request.get_json().get('prompt')

        matches = get_values(user_input)

        # Phase 3: Generate formatted response
        final_answer = structure_response(user_input, matches)

        return {"answer": final_answer}, 200, {'Access-Control-Allow-Origin': '*'}
    except requests.exceptions.Timeout:
        return {"error": "The request timed out — the AI service is taking too long to respond. Please try again in a moment."}, 504, {'Access-Control-Allow-Origin': '*'}
    except Exception as e:
        return {"error": str(e)}, 500, {'Access-Control-Allow-Origin': '*'}

