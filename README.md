# NYC Health Law Bot

A semantic search tool for the NYC Health Code, NYC Admin Code, and NYS Sanitary Code. Ask a plain-English question; the app rewrites it into legal keywords, retrieves the most relevant sections from a Pinecone vector index, and uses Gemini to return a bulleted summary with inline §-citations and highlighted source passages.

**Live app:** https://mporter-dohmh.github.io/law-bot

---

## Architecture

```
Browser (ui/)  →  Google Cloud Function (api/cloud_function.py)  →  Gemini + Pinecone
```

### Query pipeline

1. **Query structuring** — Gemini (`gemini-2.5-flash-lite`) rewrites the user's question into legal search keywords
2. **Vector retrieval** — Keywords are embedded with `gemini-embedding-001` and used to query Pinecone; the top 10 unique sections (by score) are returned
3. **Response generation** — Gemini summarizes the retrieved sections as a bulleted list with inline §-citations, streamed back to the browser via SSE

---

## Project structure

```
law-bot/
├── ui/                        # Single-page frontend (HTML/JS/CSS)
├── api/
│   ├── cloud_function.py      # Cloud Function entry point — single api source
│   ├── prompts/               # Prompt templates loaded at runtime
│   ├── tests/
│   └── deploy/                # GCP deployment scripts and config
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
│   └── test_pipeline.py          # Quick end-to-end pipeline test
└── docs/
    └── output-format.md       # Detailed spec for response format and UI behavior
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
pip install requests numpy python-dotenv google-generativeai

# Copy the env template and fill in your keys
cp .env.example .env

# Run a test query
python test/test_pipeline.py
```

### Re-indexing

Run these after modifying scrapers, chunking logic, or the raw data files:

```bash
python3 -m db.chunking.main       # clears Pinecone index and re-uploads all chunks
python3 data/generate_section_data.py  # regenerates ui/data/*.json section lookup files
```

### Deployment (Google Cloud Functions)

```bash
cd api/deploy
bash deploy.sh   # generates env.yaml from repo-root .env, then deploys
```

The deploy script targets the `nyc-health-law-bot` GCP project, region `us-east1`. Update `deploy.sh` if you're deploying to a different project.

---

## Data sources

| Code | Scraper | Chunker |
|---|---|---|
| NYC Health Code | `data/scrapers/nyc-health-code/` | `db/chunking/nyc_health_code.py` |
| NYC Admin Code | `data/scrapers/nyc-admin-code/` | `db/chunking/nyc_admin.py` |
| NYS Sanitary Code | `data/scrapers/nys-sanitary-code/` | `db/chunking/nys_sanitary.py` |

---

## Environment variables

Copy `.env.example` to `.env` and fill in real values. `deploy.sh` generates `api/deploy/env.yaml` from it automatically. Required variables:

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_HOST` | Pinecone index URL |
| `ALLOWED_ORIGIN` | Frontend origin allowed by CORS |
| `TOKEN_SECRET` | Signing secret for auth tokens (`openssl rand -hex 32`) |
| `PROMPT_BUCKET` | GCS bucket name for prompt templates |

For local dev, put these in a `.env` file at the repo root (see `.env.example`).
