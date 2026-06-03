# Cloud Function Workflow

`api/cloud_function.py` is the single entry point for all backend logic. It is deployed as a Google Cloud Function (2nd gen) and handles three distinct request types from the browser.

> **Auth status: currently disabled.** Magic link authentication is bypassed in both `app.js` (skips login gate, passes token `"disabled"`) and `cloud_function.py` (`verify-token` always returns valid, token validation in the search path is skipped). Prompt logs will show `anonymous` as the user. See [Re-enabling auth](#re-enabling-auth) below.

---

## Request routing

Every request is an HTTP POST to the function URL. The function reads the JSON body and routes by `body.type`:

```
POST /law-bot
  ├── body.type == "send-link"    →  Auth: send magic link email
  ├── body.type == "verify-token" →  Auth: validate a token (currently always returns valid)
  └── (no type / body.prompt)    →  Search: run the query pipeline (SSE stream)
```

CORS preflight (`OPTIONS`) is handled first and returns 204 with no body.

---

## Request type 1 — `send-link`

**Triggered when:** user submits the login form with their email address.

```
Browser                          Cloud Function                  Gmail SMTP
  │                                    │                              │
  │── POST {type:"send-link",          │                              │
  │         email:"x@health.nyc.gov"} ─►                             │
  │                                    │  validate @health.nyc.gov    │
  │                                    │  _generate_token(email)      │
  │                                    │    HMAC-SHA256 signature      │
  │                                    │    24-hour expiry             │
  │                                    │── sendmail ──────────────────►
  │◄── {ok: true} ─────────────────────│                              │
```

**Token format:** `base64url(email|expires_unix_timestamp).hmac_sha256_hex`

**Logged:** `send-link sent: x@health.nyc.gov` or `send-link error (x@health.nyc.gov): <reason>`

**Validation:**
- Email must end in `@health.nyc.gov` — all others receive a 403

---

## Request type 2 — `verify-token`

**Triggered when:** user opens the app with `?token=...` in the URL (i.e., clicks a magic link).

```
Browser                          Cloud Function
  │                                    │
  │── POST {type:"verify-token",       │
  │         token:"<token>"} ──────────►
  │                                    │  _validate_token(token)
  │                                    │    decode base64 payload
  │                                    │    recompute HMAC, compare
  │                                    │    check expiry timestamp
  │◄── {valid:true, email:"..."}  ─────│
  │    or {valid:false, reason:"..."}  │
```

**Outcomes:**
- `{valid: true, email: "x@health.nyc.gov"}` — token accepted, browser shows search UI
- `{valid: false, reason: "expired"}` — 24-hour window passed, user must request a new link
- `{valid: false, reason: "invalid"}` — bad signature or malformed token

**Logged:** `verify-token: x@health.nyc.gov` or `verify-token failed: expired`

---

## Request type 3 — Search query (SSE stream)

**Triggered when:** user submits a question in the search form.

This is the main pipeline. The response is a **Server-Sent Events (SSE) stream** — the function sends multiple `data: {...}\n\n` events over a single HTTP connection as work completes.

### Full pipeline

```
Browser                          Cloud Function                 External APIs
  │                                    │
  │── POST {prompt:"...",              │
  │         token:"..."} ──────────────►
  │                                    │  validate token
  │                                    │  log: prompt (email): <text>
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
| `auth_error` | On invalid/expired token | `{reason: "expired" \| "invalid"}` |

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
| Invalid/expired token | SSE `auth_error` event; browser redirects to login gate |

---

## Logging

All events are written to Cloud Logging via `print()`:

| Log line | Meaning |
|---|---|
| `send-link sent: x@health.nyc.gov` | Magic link email sent successfully |
| `send-link error (x@health.nyc.gov): <err>` | SMTP failure |
| `verify-token: x@health.nyc.gov` | Token validated (user logged in) |
| `verify-token failed: expired` | Token expired |
| `prompt (x@health.nyc.gov): <text>` | User submitted a query (shows `anonymous` while auth is disabled) |
| `Pinecone returned N matches above threshold` | Retrieval result count |

Query logs via gcloud:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND (textPayload:\"send-link\" OR textPayload:\"verify-token\" OR textPayload:\"prompt (\")" \
  --project=nyc-health-law-bot \
  --freshness=24h \
  --format="table(timestamp,textPayload)"
```

---

## Re-enabling auth

Auth was disabled to allow open access during onboarding. To re-enable:

**1. `app.js`** — restore the full `initAuth()` function:

```js
// Replace this:
(async function initAuth() {
  showSearch('disabled');
})();

// With this:
(async function initAuth() {
  const token = new URLSearchParams(window.location.search).get('token');
  if (!token) { showAuthGate(); return; }
  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'verify-token', token }),
    });
    const data = await resp.json();
    if (data.valid) {
      showSearch(token);
    } else if (data.reason === 'expired') {
      showAuthGate('Your access link has expired. Enter your email to request a new one.');
    } else {
      showAuthGate('Invalid access link. Enter your email to request a new one.');
    }
  } catch {
    showAuthGate('Could not verify your access link. Enter your email to request a new one.');
  }
})();
```

**2. `cloud_function.py`** — restore real token validation in two places:

```python
# verify-token handler — replace:
return (json.dumps({"valid": True, "email": "anonymous"}), 200, json_headers)
# with:
result = _validate_token(body.get("token", ""))
if result["valid"]:
    print(f"verify-token: {result['email']}")
else:
    print(f"verify-token failed: {result['reason']}")
return (json.dumps(result), 200, json_headers)

# Search path — replace:
token_result = {"valid": True, "email": "anonymous"}
# with:
token_result = _validate_token(body.get("token", ""))
if not token_result["valid"]:
    def _auth_err():
        yield _sse({"type": "auth_error", "reason": token_result["reason"]})
    return Response(_auth_err(), headers=sse_headers)
```

After both changes, deploy: `cd api/deploy && bash deploy.sh` (backend) and push `ui/app.js` to GitHub Pages (frontend).
