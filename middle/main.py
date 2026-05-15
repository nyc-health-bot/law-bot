import os
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
    Constructs the final prompt with context and constraints for the LLM.
    """
    # Build a readable context block from varying metadata schemas
    context_bits = []
    for m in pinecone_matches:
        meta = m['metadata']
        # Unified citation format
        citation = f"{meta.get('code')} §{meta.get('section')}"
        url = meta.get('source_url', 'No link provided')
        text = meta.get('text', '[Content missing]')

        context_bits.append(f"SOURCE: {citation}\nURL: {url}\nTEXT: {text}")

    context_str = "\n\n---\n\n".join(context_bits)

    # Final call to Gemini to answer the question
    gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{
            "parts": [{
                "text": (f"System: You are an expert NYC Health Inspector. Answer based ONLY on the provided codes. "
                         f"Use direct quotes and provide specific links. If not found, say you don't know.\n\n"
                         f"Context:\n{context_str}\n\n"
                         f"User Question: {user_query}")
            }]
        }]
    }

    gen_resp = post(url=gen_url, json=payload)
    return gen_resp.json()['candidates'][0]['content']['parts'][0]['text']


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

