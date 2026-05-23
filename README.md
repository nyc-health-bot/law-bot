# NYC Health Law Bot

A semantic search tool for the NYC Health Code, NYC Admin Code, NYS Sanitary Code, and NYC Rules. Ask a plain-English question; the app rewrites it into legal keywords, retrieves the most relevant sections from a Pinecone vector index, and uses Gemini to return a bulleted summary with inline §-citations and highlighted source passages.

**Live app:** https://mporter-dohmh.github.io/law-bot

---

## Architecture

```
Browser (ui/)  →  Google Cloud Function (api/cloud_function.py)  →  Gemini + Pinecone
```

### Query pipeline

1. **Query structuring** — Gemini (`gemini-2.5-flash`) rewrites the user's question into legal search keywords
2. **Vector retrieval** — Keywords are embedded with `gemini-embedding-001` (`RETRIEVAL_QUERY` task type) and used to query Pinecone; top 30 chunks are fetched, deduplicated to the top 10 unique sections by score (threshold 0.5)
3. **Response generation** — Gemini generates a bulleted markdown summary with inline §-citations, streamed back to the browser via SSE
4. **Passage extraction** — After streaming, Gemini selects verbatim quotes from each source for passage highlighting in the UI

---

## Project structure

```
law-bot/
├── ui/
│   ├── index.html             # Single-page app
│   ├── app.js                 # All frontend logic: fetch, render, streaming, highlighting
│   ├── style.css
│   └── data/                  # Static JSON section-text lookup files (gitignored if large)
│       ├── nyc-health-code.json
│       ├── nyc-admin-code.json
│       ├── nyc-rules.json
│       └── nys-sanitary-code.json
├── api/
│   ├── cloud_function.py      # Cloud Function entry point — single API source
│   ├── prompts/               # Prompt templates (deployed separately to GCS)
│   │   ├── structure_question.txt
│   │   ├── structure_summary.txt
│   │   ├── structure_response.txt
│   │   └── structure_passages.txt
│   └── deploy/                # GCP deployment scripts and config
│       ├── deploy.sh          # Deploy Cloud Function
│       └── deploy_prompts.sh  # Deploy prompts to GCS
├── db/
│   ├── pinecone.py            # Pinecone client (query, upload, clear)
│   ├── http.py                # HTTP helpers and Gemini embedding client
│   └── chunking/              # ETL pipeline: scraped JSON → Pinecone chunks
├── data/
│   ├── generate_section_data.py  # Generates ui/data/*.json section lookup files
│   └── scrapers/                 # Web scrapers for each legal code
│       ├── nyc-health-code/
│       ├── nyc-admin-code/
│       └── nys-sanitary-code/
├── test/
│   ├── test_pipeline.py          # Quick end-to-end pipeline smoke test
│   ├── test_prompts.py           # Structural correctness tests (JSON shape, citations, passages)
│   ├── test_mouse_citations.py   # Regression: mouse query streaming-path citations
│   ├── test_gym_regulations.py   # Regression: gym query bullet format and relevance filtering
│   └── test_gym_definition.py    # Regression: §17-188 gym definition and passage highlighting
└── docs/
    └── output-format.md       # Spec for response format and UI behavior
```

---

## Setup

### Prerequisites

- Python 3.11+
- A [Gemini API key](https://aistudio.google.com/)
- A [Pinecone](https://pinecone.io) account with a 1024-dimension cosine-similarity index

### Local development

```bash
# Install dependencies
pip install -r api/deploy/requirements.txt

# Copy the env template and fill in your keys
cp .env.example .env

# Run a test query
python test/test_pipeline.py
```

### Running tests

```bash
python -m pytest test/ -v
```

Tests require `GOOGLE_API_KEY` in `.env`. Most tests call the live Gemini and Pinecone APIs; they are not mocked.

### Re-indexing

Run these after modifying scrapers, chunking logic, or the raw data files:

```bash
python3 -m db.chunking.main            # clears Pinecone index and re-uploads all chunks
python3 data/generate_section_data.py  # regenerates ui/data/*.json section lookup files
```

### Deployment

**Cloud Function** (required after any change to `cloud_function.py`):

```bash
cd api/deploy
bash deploy.sh
```

**Prompts** (no Cloud Function redeploy needed — live within 60 seconds):

```bash
cd api/deploy
bash deploy_prompts.sh
```

The deploy scripts target the `nyc-health-law-bot` GCP project, region `us-east1`.

---

## Data sources

| Code | Scraper | Chunker | UI data key |
|---|---|---|---|
| NYC Health Code | `data/scrapers/nyc-health-code/` | `db/chunking/nyc_health_code.py` | `NYC Health Code` |
| NYC Admin Code | `data/scrapers/nyc-admin-code/` | `db/chunking/nyc_admin.py` | `NYC Admin Code` |
| NYS Sanitary Code | `data/scrapers/nys-sanitary-code/` | `db/chunking/nys_sanitary.py` | `NYS Sanitary Code` |
| Rules of the City of New York | `data/scrapers/nyc-admin-code/` | `db/chunking/nyc_admin.py` | `Rules of the City of New York` |

---

## Environment variables

Copy `.env.example` to `.env` and fill in real values. `deploy.sh` generates `api/deploy/env.yaml` from it automatically.

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_HOST` | Pinecone index URL |
| `ALLOWED_ORIGIN` | Frontend origin allowed by CORS (e.g. `https://mporter-dohmh.github.io`) |
| `TOKEN_SECRET` | Signing secret for auth tokens (`openssl rand -hex 32`) |
| `PROMPT_BUCKET` | GCS bucket name where prompt templates are stored |
| `SMTP_HOST` | SMTP server for sending auth email links |
| `SMTP_PORT` | SMTP port |
| `SMTP_USER` | SMTP username |
| `SMTP_PASS` | SMTP password |
| `FROM_EMAIL` | Sender address for auth emails |
