# Law Bot — Output Requirements

All requirements captured from chat history, prompts, and code. This is the authoritative reference for how every part of the response must behave.

---

## 1. Summary

### 1.1 Structure
- Begin with **one or two plain intro sentences** summarizing the answer. No §-citation in the intro.
- Follow with a **markdown bulleted list** (`- `). Never write prose paragraphs.
- Each bullet is one distinct rule, requirement, or definition.

### 1.2 Definitions First
- If any source defines a term relevant to the question (e.g. "X means…", "X is defined as…", "For the purposes of this section, X…"), that definition **must appear as the first bullet(s)**.
- Definitions must not be buried later in the list.

### 1.3 Citations — required on every bullet
- **Every bullet must end with a §-citation in parentheses — no exceptions.** A bullet without a citation is invalid.
- Format: `(§81.07)` or `(§81.07, §7-12)` for multiple sources.
- Copy the identifier **exactly** from the source title as provided to the model. Section numbers may use decimals (`§81.07`) or hyphens (`§7-12`) — both are valid.
- Cite **only** identifiers that appear as source titles. Do **not** cite:
  - Bracketed index numbers `[0]`, `[1]`, `[2]`
  - Section numbers mentioned only within body text (cross-references)
  - Subsection qualifiers like `(a)`, `(aa)`, `(1)` appended to a section number
- Exception: if the sources do not answer the question, write a single bullet saying so with no §-citation.

### 1.4 Post-processing (backend)
- `_filter_citations` strips any `(§XX)` group where none of the cited sections match a retrieved source. This is a safety net — the prompt is the primary enforcement.
- The summary is streamed to the frontend as chunks, then replaced with the filtered+rendered version on `done`.

---

## 2. Citation Cards

### 2.1 Splitting
- Citations are split into two groups based on whether the section number appears as `§XX` in the summary text:
  - **Citations** — sections cited inline in the summary bullets
  - **Additional Sources** — retrieved sections not cited in the summary; shown in a separate "Additional Sources" section (hidden if empty)

### 2.2 Card content
- Header: section number (`§XX.XX`), section title, code label (e.g. "NYC Health Code", "Rules of the City of New York", "NYC Admin Code", "NYS Sanitary Code")
- Body (loaded lazily on expand): full section text from `ui/data/{code}.json`; falls back to chunk text if the JSON file is unavailable

### 2.3 Passage highlighting
- Relevant passages (verbatim quotes from source text) are highlighted in yellow `<mark>` inside the expanded card body.
- Exact string match attempted first; whitespace-normalized fallback used if not found.
- Passages arrive via a separate `passages` SSE event (parallel to summary stream) and are applied when the event arrives — if a card is already expanded, it re-renders with highlights immediately.

---

## 3. Code Labels

Sections must be labeled with exactly these strings (case-sensitive) based on the source file type:

| Label | Source |
|---|---|
| `NYC Health Code` | `article_*.json` files in `scraping/nyc-health-code/data/` |
| `Rules of the City of New York` | `chapter_*.json` files in `scraping/nyc-health-code/data/` (`"type": "chapter"`) |
| `NYC Admin Code` | `scraping/nyc-admin-code/data/` |
| `NYS Sanitary Code` | `scraping/nys-sanitary-code/data/` |

The label is stored in the `code` field of Pinecone chunk metadata and must match the key in `ui/app.js` `CODE_FILES` exactly so the UI can load the correct section JSON.

---

## 4. Retrieval Parameters

- **Model**: `gemini-embedding-001`, 1024 dimensions (truncated + L2-normalized)
- **Query task type**: `RETRIEVAL_QUERY` (must not use `RETRIEVAL_DOCUMENT` for queries — inflates scores)
- **topK**: 30 chunks fetched from Pinecone
- **Score threshold**: 0.5 (chunks below this are discarded)
- **Deduplication**: up to **4 unique (code, section) pairs** kept, ranked by each section's best chunk score
- **Context sent to summary model**: first chunk of each section, truncated to 1000 characters
- **Context sent to passages model**: full combined text of all chunks per section

---

## 5. Relevant Passages

- Extracted by a **separate Gemini call** running in parallel with the summary stream.
- Must be **verbatim quotes** from the source text — no paraphrasing.
- Each quote must be **one or more complete sentences** — never cut off mid-word or mid-sentence.
- Quotes must come only from the source at the specified index — do not mix sources.
- Empty list if no passages are relevant.

---

## 6. SSE Event Sequence

The backend streams a sequence of Server-Sent Events:

| Order | Event type | Payload | Frontend action |
|---|---|---|---|
| 1 | `metadata` | `{citations: [...]}` | Render citation card shells immediately |
| 2…N | `chunk` | `{text: "..."}` | Append to plain-text summary display |
| N+1 | `done` | `{summary: "...", cited_sections: [...]}` | Replace with rendered markdown + §-links; split cards into Citations / Additional |
| N+2 | `passages` | `{passages: {index: [quotes]}}` | Apply highlights; re-render any already-expanded cards |
| — | `auth_error` | `{reason: "expired"\|"invalid"}` | Drop user back to auth gate with message |
| — | `error` | `{message: "..."}` | Show error banner |

---

## 7. §-Link Behavior in Summary

- Every `§XX.XX` or `§XX-XX` pattern in the rendered summary is converted to a clickable link anchored to its citation card.
- Clicking a §-link: collapses all other cards (accordion), expands the target card, scrolls it into view.
- §-references that do not match any retrieved section remain as plain text (not linked).

---

## 8. Generation Parameters

- **Model**: `gemini-2.5-flash-lite`
- **Temperature**: `0` (deterministic output; eliminates run-to-run variation in citation format)
- **Summary**: free-form text via `streamGenerateContent` (SSE)
- **Passages**: structured JSON via `generateContent` with `responseSchema` enforcement
- **Prompt source**: loaded from GCS bucket `law-bot-prompts` with 60-second in-memory cache; update with `gsutil cp` — no redeploy needed

---

## 9. What the Model Must NOT Do

- Add outside knowledge not present in the provided source texts
- Write prose paragraphs instead of bullets
- Omit §-citations from bullets
- Cite bracketed source indices `[0]`, `[1]`
- Cite subsection qualifiers as standalone sections (e.g. `§81.07(a)`)
- Cite section numbers that only appear as cross-references within source body text
- Write a citation that does not exactly match a source title
