# Cloud Function Workflow

`api/cloud_function.py` is the single entry point for all backend logic. It is deployed as a Google Cloud Function (2nd gen) and handles two request types from the browser.

---

## Request routing

Every request is an HTTP POST to the function URL. The function reads the JSON body and routes by `body.type`:

```
POST /law-bot
  ├── body.type == "feedback"  →  Append a rating row to the feedback sheet
  └── (no type / body.prompt) →  Search: run the query pipeline (SSE stream)
```

CORS preflight (`OPTIONS`) is handled first and returns 204 with no body.

---

## Search query (SSE stream)

**Triggered when:** user submits a question in the search form.

This is the main pipeline. The response is a **Server-Sent Events (SSE) stream** — the function sends multiple `data: {...}\n\n` events over a single HTTP connection as work completes.

### Full pipeline

```
Browser                          Cloud Function                 External APIs
  │                                    │
  │── POST {prompt:"..."} ─────────────►
  │                                    │  log: prompt: <text>
  │                                    │
  │                                    │  ① structure_question()
  │                                    │    Gemini rewrites query ──────────────► Gemini Flash
  │                                    │◄── legal keywords ─────────────────────
  │                                    │
  │                                    │  ② _cached_pinecone_query()
  │                                    │    embed keywords ─────────────────────► Gemini Embeddings
  │                                    │◄── 1024-dim vector ────────────────────
  │                                    │    query Pinecone (topK=30) ───────────► Pinecone
  │                                    │◄── matches ────────────────────────────
  │                                    │    filter score > 0.5
  │                                    │    deduplicate → top 4 unique sections
  │                                    │    _build_sources() assembles source objects
  │                                    │
  │◄── SSE: metadata ──────────────────│  ③ stream metadata event
  │    {citations: [...]}              │     (citation cards rendered in browser)
  │                                    │
  │                                    │  ④ CONCURRENT:
  │                                    │     ┌─ _gemini_stream() ──────────────► Gemini Flash
  │                                    │     │  structure_summary.txt prompt
  │◄── SSE: chunk (repeated) ──────────│     │  streams markdown bullets
  │◄── SSE: chunk ─────────────────────│     │
  │◄── SSE: chunk ─────────────────────│     │
  │                                    │     └─ _get_passages() ──────────────► Gemini Flash
  │                                    │        structure_passages.txt prompt
  │                                    │        verbatim quotes per source
  │                                    │
  │                                    │  ⑤ _filter_citations()
  │                                    │     strip §-refs not in retrieved sources
  │                                    │     extract cited_sections list
  │◄── SSE: done ──────────────────────│
  │    {summary, cited_sections}       │
  │                                    │
  │◄── SSE: passages ──────────────────│  ⑥ passages future resolved
  │    {passages: {idx: [quotes]}}     │
```

### SSE event types (in order)

| Event | When sent | Payload |
|---|---|---|
| `metadata` | Immediately after Pinecone returns | `{citations: [{anchor, section, code, full_title, section_title, url, text}]}` |
| `chunk` | As Gemini streams each text fragment | `{text: "..."}` |
| `done` | After full summary is assembled | `{summary: "markdown string", cited_sections: ["81.07", ...]}` |
| `passages` | After passage extraction completes | `{passages: {"0": ["verbatim quote..."], "1": [...]}}` |
| `error` | On any unhandled exception | `{message: "..."}` |

### Step-by-step detail

**① `structure_question()`** — uses `structure_question.txt` prompt, Gemini Flash, temperature 0.1. Rewrites the plain-English question into legal keywords (e.g. "mouse in storage room" → "rodent infestation pest control §151"). Not called in the SSE path — the raw `body.prompt` is passed directly to `_cached_pinecone_query()`.

> Note: `structure_question()` exists as a standalone function used in tests. In the live SSE path, `_cached_pinecone_query(user_input)` is called with the raw user input directly; Gemini keyword rewriting is only used in the test pipeline.

**② `_cached_pinecone_query()`** — checks an in-memory LRU cache (TTL 5 min, max 50 entries) before hitting Pinecone. On a cache miss:
- Embeds the query with `gemini-embedding-001`, task type `RETRIEVAL_QUERY`, 1024 dimensions
- Queries Pinecone with `topK=30`
- Filters to matches with score > 0.5
- Deduplicates to top 4 unique `(code, section)` pairs by best chunk score

**`_build_sources()`** — merges all chunks belonging to the same section into one source object:
- `text` — all chunks joined with `\n\n` (full text for fallback display)
- `summary_text` — first 2500 chars of joined text (sent to Gemini for summarization)
- `passage_text` — chunks joined via `_join_chunk_bodies()`, which detects and heals word-boundary splits left by the chunker

**③ `metadata` event** — sent before any Gemini calls begin. Browser renders citation card shells immediately so the user sees structure while waiting for the summary.

**④ Concurrent generation** — a `ThreadPoolExecutor` runs `_get_passages()` in a background thread while the main thread streams the summary. This hides the passage extraction latency (typically 5–15 seconds) behind the summary stream.

- **Summary stream** (`_gemini_stream()`): uses `structure_summary.txt`, temperature 0, streaming SSE. Each text chunk is forwarded to the browser immediately as a `chunk` event. The browser renders raw text progressively; `finalizeSummary()` in `app.js` re-renders it as parsed markdown once the `done` event arrives.

- **Passage extraction** (`_get_passages()`): uses `structure_passages.txt`, JSON mode with schema enforcement, temperature 0.1. Returns `{index: [verbatim_quotes]}` for each source.

**⑤ `_filter_citations()`** — post-processes the assembled summary to remove any `§XX.XX` references that don't correspond to a retrieved source (prevents hallucinated cross-references). Two passes: parenthetical groups `(§81.07, §7-12)` and bare inline references.

**⑥ `passages` event** — sent after the background thread resolves. Browser applies highlights to any already-expanded citation card bodies.

---

## Prompt loading

Prompts are stored in a GCS bucket and loaded at runtime with a 60-second TTL cache. This means prompts can be updated without redeploying the Cloud Function:

```bash
cd api/deploy
bash deploy_prompts.sh   # gsutil cp all prompts to GCS — live within 60 seconds
```

| Prompt file | Used by | Mode |
|---|---|---|
| `structure_question.txt` | `structure_question()` | Free text |
| `structure_summary.txt` | `_gemini_stream()` in SSE path | Streaming free text |
| `structure_response.txt` | `structure_response()` in test path | JSON mode |
| `structure_passages.txt` | `_get_passages()` | JSON mode |

---

## Error handling

| Condition | Behavior |
|---|---|
| Pinecone timeout | SSE `error` event with user-friendly message |
| No matches above 0.5 threshold | SSE `metadata` (empty) + `done` ("couldn't find any relevant sections") + `passages` (empty) |
| Gemini stream error mid-summary | SSE `error` event; stream closes |
| Passage extraction failure | Logged silently; `passages` event sent with empty dict |

---

## Logging

All events are written to Cloud Logging via `print()`:

| Log line | Meaning |
|---|---|
| `prompt: <text>` | User submitted a query |
| `feedback: rating=N session=xxxxxxxx` | User submitted a rating |
| `Pinecone returned N matches above threshold` | Retrieval result count |

Query logs via gcloud:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND (textPayload:\"prompt:\" OR textPayload:\"feedback:\")" \
  --project=nyc-health-law-bot \
  --freshness=24h \
  --format="table(timestamp,textPayload)"
```

