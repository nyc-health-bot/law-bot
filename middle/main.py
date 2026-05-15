import json
import os
import re
from dotenv import load_dotenv
from util import post, embed_fn
from pinecone import query


load_dotenv()
# --- CONFIGURATION (Load once) ---
GEMINI_KEY = os.environ.get("GOOGLE_API_KEY")
PINECONE_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_HOST = os.environ.get("PINECONE_HOST")  # URL from Pinecone dashboard


def structure_question(raw_user_query):
    """
    Transforms plain English into a technical 'Legal Query' for better vector search.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{
            "parts": [{
                "text": (
                    f"Rewrite the following question as a short list of technical and legal keywords "
                    f"that would appear in the NYC Health Code or NYS Sanitary Code. "
                    f"Output ONLY the keywords, no explanation, no sentences, no formatting.\n\n"
                    f"Question: '{raw_user_query}'"
                )
            }]
        }],
        "generationConfig": {"temperature": 0.1}  # Keep it deterministic
    }

    resp = post(url=url, json=payload)
    # Extract the transformed text from the Gemini response
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

    gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{
            "parts": [{
                "text": (
                    f"You are an expert NYC Health Inspector. "
                    f"Use ONLY the source texts provided — do not add any outside knowledge.\n\n"
                    f"Question: {user_query}\n\n"
                    f"Sources:\n{context_str}\n\n"
                    f"Return a JSON object with two keys:\n"
                    f"1. \"summary\": the answer to the question formatted as a markdown bulleted list (each item starting with \"- \"). "
                    f"If a single sentence helps introduce the bullets, include it before the list. "
                    f"Each bullet should be a distinct rule or requirement. "
                    f"When citing a specific rule or requirement, include its section identifier inline in parentheses at the end of the bullet — "
                    f"for example: \"- Surfaces must be smooth and free from cracks (§81.07, §19.05).\" "
                    f"Use the section identifiers from the source titles (e.g. §81.07). "
                    f"If the sources do not answer the question, say so explicitly.\n"
                    f"2. \"citations\": an array with exactly {len(sources)} objects, one per source in order. "
                    f"Each object must have \"index\" (integer) and \"relevant_passages\" "
                    f"(a list of verbatim quotes copied ONLY from the TEXT of the source with that exact index — "
                    f"do not quote text from any other source — "
                    f"include any text from this source that you quoted directly in the summary — "
                    f"each quote must be one or more complete sentences, never cut off mid-word or mid-sentence — empty list if none are relevant)."
                )
            }]
        }],
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

    gen_resp = post(url=gen_url, json=payload)
    raw = gen_resp.json()['candidates'][0]['content']['parts'][0]['text']
    gemini_out = json.loads(raw)

    passage_map = {item['index']: item.get('relevant_passages', []) for item in gemini_out['citations']}

    summary = gemini_out['summary']
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

        # Phase 1: Rewrite the question for the search engine
        technical_query = structure_question(user_input)

        # Phase 2: Retrieve actual code data
        matches = get_values(technical_query)

        # Phase 3: Generate formatted response
        final_answer = structure_response(user_input, matches)

        return {"answer": final_answer}, 200, {'Access-Control-Allow-Origin': '*'}
    except Exception as e:
        return {"error": str(e)}, 500, {'Access-Control-Allow-Origin': '*'}

