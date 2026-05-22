import base64
import concurrent.futures
import hashlib
import hmac
import json
import os
import re
import smtplib
import ssl
import time
from datetime import datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests
from flask import Response

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GOOGLE_API_KEY")
PINECONE_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_HOST = os.environ.get("PINECONE_HOST")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
APP_URL = os.environ.get("APP_URL", "https://mporter-dohmh.github.io/law-bot")

_NY_TZ = ZoneInfo("America/New_York")
PROMPT_BUCKET = os.environ.get("PROMPT_BUCKET")

# --- AUTH ---

def _generate_token(email: str) -> tuple[str, int]:
    expires = int(time.time()) + 86400
    payload = f"{email}|{expires}"
    sig = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    return f"{b64}.{sig}", expires


def _validate_token(token: str) -> dict:
    try:
        b64, sig = token.rsplit(".", 1)
        padding = (4 - len(b64) % 4) % 4
        payload = base64.urlsafe_b64decode(b64 + "=" * padding).decode()
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {"valid": False, "reason": "invalid"}
        email, expires_str = payload.rsplit("|", 1)
        if int(time.time()) > int(expires_str):
            return {"valid": False, "reason": "expired"}
        return {"valid": True, "email": email}
    except Exception:
        return {"valid": False, "reason": "invalid"}


def _send_magic_link(email: str, token: str, expires: int) -> None:
    expires_dt = datetime.fromtimestamp(expires, tz=_NY_TZ)
    expires_str = expires_dt.strftime("%-I:%M %p ET on %B %-d, %Y")
    link = f"{APP_URL}?token={token}"
    body = (
        f"You requested access to the NYC DOHMH Law Bot.\n\n"
        f"Click the link below to access the tool:\n{link}\n\n"
        f"This link will expire at {expires_str}.\n\n"
        f"Do not share this link — it is intended for your use only.\n\n"
        f"If you did not request this link, please ignore this email."
    )
    msg = MIMEText(body)
    msg["Subject"] = "NYC Health Law Bot Access Link"
    msg["From"] = GMAIL_USER
    msg["To"] = email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [email], msg.as_string())


# --- PROMPT CACHE (TTL 60s — update prompts via gsutil cp, no redeploy needed) ---
_prompt_cache: dict[str, tuple[str, float]] = {}
_PROMPT_TTL = 60

# --- PINECONE RESULT CACHE (per warm instance, TTL 5 min) ---
_query_cache: dict[str, tuple[list, float]] = {}
_QUERY_CACHE_TTL = 300
_QUERY_CACHE_MAX = 50


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
    return resp.content.decode('utf-8')


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
    import numpy as np
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

def _pinecone_query(query_text: str, max_sections: int = 4) -> list[dict]:
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


def _cached_pinecone_query(query_text: str) -> list[dict]:
    import hashlib
    key = hashlib.md5(query_text.lower().strip().encode()).hexdigest()
    now = time.time()
    if key in _query_cache and now - _query_cache[key][1] < _QUERY_CACHE_TTL:
        return _query_cache[key][0]
    result = _pinecone_query(query_text)
    if len(_query_cache) >= _QUERY_CACHE_MAX:
        oldest = min(_query_cache, key=lambda k: _query_cache[k][1])
        del _query_cache[oldest]
    _query_cache[key] = (result, now)
    return result


# --- GEMINI HELPERS ---

def _gemini_generate(payload: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}"
    for attempt in range(5):
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        if not resp.ok:
            raise requests.HTTPError(
                f"{resp.status_code} {resp.reason}: {resp.text}", response=resp
            )
        return resp.json()
    raise RuntimeError("Gemini request failed after 5 retries")


def _extract_section(raw: str) -> str:
    """Strip trailing punctuation from a matched section number e.g. '165.47.' → '165.47'."""
    return raw.rstrip('.,;:')


def _filter_citations(summary: str, valid_sections: set) -> str:
    """Strip §-citations from summary that have no corresponding retrieved source.
    Handles both parenthetical citations (§XX.XX) and inline bare §XX.XX references."""
    # Pass 1 — clean parenthetical citation groups like (§81.07) or (§81.07, §17-188)
    def clean_group(m):
        kept = [_extract_section(s) for s in re.findall(r'§([\w.\-]+)', m.group(0))
                if _extract_section(s) in valid_sections]
        return '(' + ', '.join(f'§{s}' for s in kept) + ')' if kept else ''
    result = re.sub(r'\((?:§[\w.\-]+(?:,\s*)?)+\)', clean_group, summary)

    # Pass 2 — remove inline bare §-citations not in valid_sections (body-text cross-refs)
    def clean_inline(m):
        section = _extract_section(m.group(1))
        return f'§{section}' if section in valid_sections else ''
    result = re.sub(r'§([\w.\-]+)', clean_inline, result)

    return result.strip()


def _split_long_bullets(summary: str) -> str:
    """Split any bullet with >3 sentences into multiple bullets, each keeping the same §-citation."""
    citation_re = re.compile(r'\s*(\((?:§[\w.\-]+(?:,\s*)?)+\))\s*$')
    sentence_split_re = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')
    result = []
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            result.append(line)
            continue
        m = citation_re.search(stripped)
        citation = m.group(1) if m else ""
        body = citation_re.sub('', stripped[2:]).strip()
        sentences = sentence_split_re.split(body)
        if len(sentences) <= 3:
            result.append(line)
            continue
        for i in range(0, len(sentences), 3):
            chunk = " ".join(sentences[i:i + 3])
            result.append(f"- {chunk} {citation}".strip() if citation else f"- {chunk}")
    return "\n".join(result)


def _build_sources(matches: list[dict]) -> list[dict]:
    seen = {}
    for m in matches:
        meta = m["metadata"]
        key = (meta.get("code", ""), meta.get("section", ""))
        if key not in seen:
            seen[key] = {
                "full_title": f"{key[0]} §{key[1]}".strip(" §"),
                "code": key[0],
                "section": key[1],
                "section_title": meta.get("section_title", ""),
                "url": meta.get("source_url", ""),
                "texts": [],
            }
        seen[key]["texts"].append(meta.get("text", ""))
    return [
        {**{k: v for k, v in entry.items() if k != "texts"},
         "text": "\n\n".join(entry["texts"]),
         "summary_text": "\n\n".join(entry["texts"])[:2500],
         "passage_text": "\n\n".join(
             t.split("\n\n", 1)[1] if "\n\n" in t else t
             for t in entry["texts"]
         )}
        for entry in seen.values()
    ]


def _gemini_generate_streamed(payload: dict) -> dict:
    """Calls Gemini via streaming SSE and assembles the full response dict.
    Use instead of _gemini_generate when the prompt is large and read timeout is a risk.
    timeout tuple: (connect_seconds, read_seconds) — read applies per chunk."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:streamGenerateContent?key={GEMINI_KEY}&alt=sse"
    for attempt in range(5):
        resp = requests.post(url, json=payload, timeout=(30, 180), stream=True)
        if resp.status_code in (429, 503):
            resp.close()
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        parts = []
        finish_reason = None
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                try:
                    data = json.loads(line[6:])
                    candidate = data["candidates"][0]
                    text = candidate["content"]["parts"][0].get("text", "")
                    if text:
                        parts.append(text)
                    if candidate.get("finishReason"):
                        finish_reason = candidate["finishReason"]
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
        return {"candidates": [{"content": {"parts": [{"text": "".join(parts)}]}, "finishReason": finish_reason}]}
    raise RuntimeError("Gemini streaming request failed after 5 retries")


def _gemini_stream(payload: dict):
    """Yields text chunks from Gemini streaming API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:streamGenerateContent?key={GEMINI_KEY}&alt=sse"
    for attempt in range(3):
        resp = requests.post(url, json=payload, timeout=60, stream=True)
        if resp.status_code in (429, 503):
            resp.close()
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                try:
                    data = json.loads(line[6:])
                    text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                    if text:
                        yield text
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
        return
    raise RuntimeError("Gemini streaming request failed after 3 retries")


def _get_passages(user_query: str, sources: list[dict]) -> dict:
    """Returns {index: [passages]} for each source."""
    context_str = "\n\n---\n\n".join(
        f"[{i}] {s['full_title']}\nURL: {s['url']}\nTEXT: {s['passage_text']}"
        for i, s in enumerate(sources)
    )
    prompt = _get_prompt("structure_passages.txt").format(
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
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "relevant_passages": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["index", "relevant_passages"],
                },
            },
        },
    }
    out = _gemini_generate(payload)
    items = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
    return {item["index"]: item.get("relevant_passages", []) for item in items}


# --- PIPELINE ---

def structure_question(raw_user_query: str) -> str:
    prompt = _get_prompt("structure_question.txt").format(raw_user_query=raw_user_query)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    out = _gemini_generate(payload)
    return out["candidates"][0]["content"]["parts"][0]["text"]


def normalize_text(s: str) -> str:
    if s is None:
        return s
    import unicodedata
    import html as _html
    s = _html.unescape(s)
    s = s.replace('﻿', '').replace(' ', ' ')
    s = s.replace('Â', '').replace('\xc2', '')
    s = s.replace('§', '§').replace('\\u00a7', '§')
    s = re.sub(r'[\r\x00\x0b\x0c]', '', s)
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.replace('\\u00a0', ' ').replace('\\xc2', '')
    s = re.sub(r'\s*\(\s*§', ' (§', s)
    s = re.sub(r'§\s*\)', '§)', s)
    return s


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

    # Call Gemini via streaming to avoid read-timeout on large prompts
    start = time.time()
    try:
        out = _gemini_generate_streamed(payload)
    except Exception as e:
        return {"summary": f"- I couldn't generate a response due to an upstream error: {str(e)}", "citations": []}
    duration = time.time() - start

    gemini_out = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])

    gemini_out['summary'] = normalize_text(gemini_out.get('summary', ''))
    # Model sometimes omits \n between bullets — insert before any "- " following a citation group
    gemini_out['summary'] = re.sub(r'\)\s+-\s+', ')\n- ', gemini_out['summary'])
    gemini_out['summary'] = _split_long_bullets(gemini_out['summary'])
    if duration > 3.0:
        note = f"Note: response generation took {duration:.1f}s."
        gemini_out['summary'] = note + "\n" + gemini_out['summary']

    passage_map = {item["index"]: item.get("relevant_passages", []) for item in gemini_out["citations"]}
    summary = _filter_citations(gemini_out["summary"], set(section_numbers))
    cited_sections = {_extract_section(s) for s in re.findall(r'§([\w.\-]+)', summary)}

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

    json_headers = {"Content-Type": "application/json", **cors_headers}
    body = request.get_json(silent=True) or {}
    req_type = body.get("type")

    if req_type == "send-link":
        email = body.get("email", "").strip().lower()
        if not email.endswith("@health.nyc.gov"):
            return (
                json.dumps({"error": "Access is restricted to NYC Dept of Health employees. Only @health.nyc.gov addresses are permitted."}),
                403, json_headers,
            )
        try:
            token, expires = _generate_token(email)
            _send_magic_link(email, token, expires)
            return (json.dumps({"ok": True}), 200, json_headers)
        except Exception as e:
            print(f"send-link error: {e}")
            return (json.dumps({"error": "Failed to send email. Please try again."}), 500, json_headers)

    if req_type == "verify-token":
        result = _validate_token(body.get("token", ""))
        return (json.dumps(result), 200, json_headers)

    sse_headers = {
        **cors_headers,
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }

    def _sse(obj):
        return f"data: {json.dumps(obj)}\n\n"

    # Validate auth token before doing any work
    token_result = _validate_token(body.get("token", ""))
    if not token_result["valid"]:
        def _auth_err():
            yield _sse({"type": "auth_error", "reason": token_result["reason"]})
        return Response(_auth_err(), headers=sse_headers)

    # Run Pinecone lookup before opening the stream so errors return cleanly
    try:
        user_input = body.get("prompt", "")
        matches = _cached_pinecone_query(user_input)
    except requests.exceptions.Timeout:
        def _timeout():
            yield _sse({"type": "error", "message": "The request timed out — the AI service is taking too long to respond. Please try again in a moment."})
        return Response(_timeout(), headers=sse_headers)
    except Exception as e:
        def _err():
            yield _sse({"type": "error", "message": str(e)})
        return Response(_err(), headers=sse_headers)

    if not matches:
        def _no_results():
            yield _sse({"type": "metadata", "citations": []})
            yield _sse({"type": "done", "summary": "- I couldn't find any relevant sections for that question.", "cited_sections": []})
            yield _sse({"type": "passages", "passages": {}})
        return Response(_no_results(), headers=sse_headers)

    sources = _build_sources(matches)
    valid_sections = {s["section"] for s in sources}
    context_str = "\n\n---\n\n".join(
        f"[{i}] {s['full_title']}\nURL: {s['url']}\nTEXT: {s['summary_text']}"
        for i, s in enumerate(sources)
    )
    citation_meta = [
        {
            "anchor": f"citation-{i}",
            "section": s["section"],
            "code": s["code"],
            "full_title": s["full_title"],
            "section_title": s["section_title"],
            "url": s["url"],
            "text": s["text"],
        }
        for i, s in enumerate(sources)
    ]
    summary_payload = {
        "contents": [{"parts": [{"text": _get_prompt("structure_summary.txt").format(
            user_query=user_input, context_str=context_str)}]}],
        "generationConfig": {"temperature": 0},
    }

    def generate():
        yield _sse({"type": "metadata", "citations": citation_meta})

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            passages_future = executor.submit(_get_passages, user_input, sources)

            raw_summary = ""
            try:
                for chunk in _gemini_stream(summary_payload):
                    raw_summary += chunk
                    yield _sse({"type": "chunk", "text": chunk})
            except Exception as e:
                yield _sse({"type": "error", "message": str(e)})
                return

            filtered = _filter_citations(raw_summary, valid_sections)
            cited_sections = [_extract_section(s) for s in re.findall(r'§([\w.\-]+)', filtered)]
            yield _sse({"type": "done", "summary": filtered, "cited_sections": cited_sections})

            try:
                passages = passages_future.result(timeout=30)
            except Exception:
                passages = {}
            yield _sse({"type": "passages", "passages": passages})

    return Response(generate(), headers=sse_headers)
