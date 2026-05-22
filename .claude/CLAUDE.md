# law-bot

A semantic search tool for NYC Health Code, NYC Admin Code, and NYS Sanitary Code. Users type a plain-English question; the api rewrites it into legal keywords, retrieves relevant sections from Pinecone, and uses Gemini to produce a bulleted summary with inline §-citations and highlighted source text.

## Architecture

```
UI (ui/)  →  Cloud Function (api/cloud_function.py)  →  Gemini + Pinecone
```

**Query pipeline (in order):**
1. `structure_question()` — Gemini rewrites user query into legal keywords (gemini-2.5-flash-lite)
2. `pinecone.query()` / `_pinecone_query()` — embeds keywords with `gemini-embedding-001` (`RETRIEVAL_QUERY` task), fetches topK=30 chunks, deduplicates to top 10 unique (code, section) pairs by best chunk score, threshold 0.5
3. `structure_response()` — Gemini generates bulleted markdown summary with inline §-citations and per-source `relevant_passages` (gemini-2.5-flash-lite)

**Single source of truth for the api:**
- `api/cloud_function.py` — self-contained Cloud Function; all dependencies inlined; deployed to GCP and used for local testing via `test/test_pipeline.py`

## Key Files

| File | Purpose |
|---|---|
| `api/cloud_function.py` | Cloud Function entry point (`handle_request`). The single api source — edit this for all changes. |
| `db/http.py` | HTTP `get`/`post` helpers with retry (429/503) and proxy support; `embed_fn()` for Gemini embeddings. Used by `db/pinecone.py`. |
| `db/pinecone.py` | `upload_chunks()`, `query()`, `clear_index()`. |
| `db/chunking/main.py` | Run as `python3 -m db.chunking.main` from repo root to re-index all codes. |
| `data/generate_section_data.py` | Run as `python3 data/generate_section_data.py` from repo root. Generates `ui/data/*.json` (section number → full formatted text). Must re-run after scraper or formatter changes. |
| `ui/index.html` | Frontend. Single page app. |
| `ui/app.js` | All frontend logic: fetch, render, accordion cards, passage highlighting, §-link anchoring. |
| `ui/style.css` | Styles. `[hidden] { display: none !important; }` is load-bearing — without it CSS flex/block overrides the HTML hidden attribute. |
| `ui/data/*.json` | Static JSON files mapping section number → full section text. Fetched lazily by the UI when a citation card is expanded. Not committed if large — regenerate with `generate_section_data.py`. |

## Deployment

```bash
cd api/deploy
bash deploy.sh
```

`env.yaml` contains real secrets — it is gitignored. Copy `env.yaml.example` to set up. After any change to `cloud_function.py`, re-run the deploy.

**Cloud Function:** `https://us-east1-nyc-health-law-bot.cloudfunctions.net/law-bot`  
**GitHub Pages:** `https://mporter-dohmh.github.io/law-bot`  
**CORS:** restricted to `https://mporter-dohmh.github.io` via `ALLOWED_ORIGIN` env var.

## Data Sources

Three codes are indexed in Pinecone:

| Code | Scraper | Chunker | Section data key |
|---|---|---|---|
| NYC Health Code | `data/scrapers/nyc-health-code/` | `db/chunking/nyc_health_code.py` | `NYC Health Code` |
| NYC Admin Code | `data/scrapers/nyc-admin-code/` | `db/chunking/nyc_admin.py` | `NYC Admin Code` |
| NYS Sanitary Code | `data/scrapers/nys-sanitary-code/` | `db/chunking/nys_sanitary.py` | `NYS Sanitary Code` |

NYS Sanitary Code Part 14 files (`part_14_*.json`) use a different structure: top-level `sections[]` instead of `subparts[].sections[]`. Both `nys_sanitary.py` and `generate_section_data.py` handle this with `_iter_sections()`.

## Pinecone Index

- Model: `gemini-embedding-001`, 1024 dimensions (truncated + normalized)
- Upload task type: `RETRIEVAL_DOCUMENT`
- Query task type: `RETRIEVAL_QUERY` — must match; using `RETRIEVAL_DOCUMENT` for queries inflates scores artificially
- topK: 30 chunks fetched, deduplicated to 10 unique sections before sending to Gemini
- Score threshold: 0.5
- Chunk size: ~2000 chars max; chunks include `code`, `section`, `section_title`, `source_url`, `text` in metadata

## Prompts

Both `structure_question` and `structure_response` use `gemini-2.5-flash-lite` with temperature 0.1.

`structure_response` returns structured JSON (`responseMimeType: application/json`) with:
- `summary`: markdown bulleted list, each bullet ending with `(§XX.XX)` inline citations
- `citations`: array of `{index, relevant_passages}` — verbatim quotes from each source

**Prompt constraints that matter:**
- "ALWAYS format as a markdown bulleted list — never write prose paragraphs" — enforces bullet format
- "Use ONLY the §XX.XX identifiers from the source titles... do not cite the bracketed index numbers [0], [1], [2]" — prevents Gemini from citing source indices as section numbers
- "do not cite section numbers mentioned only within the body text" — prevents hallucinated cross-references
- "each quote must be one or more complete sentences, never cut off mid-word or mid-sentence" — keeps passage highlighting accurate

## Response Shape

```json
{
  "answer": {
    "summary": "markdown string with - bullets and (§XX.XX) inline cites",
    "citations": [
      {
        "anchor": "citation-0",
        "section": "81.07",
        "code": "NYC Health Code",
        "full_title": "NYC Health Code §81.07",
        "section_title": "Food protection",
        "url": "https://...",
        "text": "full chunk text (fallback if JSON not available)",
        "relevant_passages": ["verbatim quote..."],
        "cited_in_summary": true
      }
    ]
  }
}
```

`cited_in_summary` is true when the section number appears as `§XX.XX` in the summary. The UI splits citations into "Citations" (cited) and "Additional Sources" (not cited).

## UI Behavior

- Full section text is loaded lazily from `ui/data/{code}.json` when a card is expanded; falls back to `citation.text` (chunk) on error
- Relevant passages are highlighted using exact string match, then whitespace-normalized fallback (`findNormalized`)
- §-references in the summary are linked to their citation card anchor; clicking collapses all other cards (accordion)
- `cited_in_summary: false` citations appear in a separate "Additional Sources" section

## Common Operations

**Re-index after scraper changes:**
```bash
python3 -m db.chunking.main   # clears index and re-uploads everything
python3 data/generate_section_data.py  # regenerate ui/data/*.json
```

**Test the local pipeline:**
```bash
python test/test_pipeline.py
```

**Or inline:**
```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from api.cloud_function import structure_question, structure_response, get_values
user_q = 'your question here'
result = structure_response(user_q, get_values(structure_question(user_q)))
print(result['summary'])
"
```

**Check what Pinecone returns for a query:**
```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from api.cloud_function import structure_question, get_values
for m in get_values(structure_question('your question')):
    print(m['score'], m['metadata']['code'], m['metadata']['section'])
"
```
