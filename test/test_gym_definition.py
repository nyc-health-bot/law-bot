"""
Regression tests for the query: "How does the NYC Health Code define a gym"

Observed issues documented here as conditions:
  1. §17-188 gym definition not highlighted — root cause: brute-force 2000-char
     chunker split the word 'development' across two chunks, making passage_text
     contain 'de\\n\\nvelopment'.  Fixed by _join_chunk_bodies() in cloud_function.py.

Workflow:
  1. Run the query in the app and observe issues.
  2. Add a test for each issue in the CONDITIONS section below.
  3. Fix the underlying prompt or pipeline code.
  4. Run the full test suite to confirm the fix and check for regressions:
       python -m pytest test/ -v

Each condition is a separate test method. When a condition is fixed, the test
should pass permanently — do not remove passing tests.
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test._env import load_env
load_env()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api.cloud_function as cf

if not os.environ.get("GOOGLE_API_KEY"):
    raise unittest.SkipTest("GOOGLE_API_KEY not set — copy .env.example to .env and fill in real values")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "api" / "prompts"
UI_DATA_DIR  = Path(__file__).resolve().parent.parent / "ui" / "data"


def _local_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _ui_text(code_file: str, section: str) -> str:
    path = UI_DATA_DIR / code_file
    data = json.loads(path.read_text(encoding="utf-8"))
    text = data.get(section)
    if text is None:
        raise RuntimeError(f"§{section} not found in ui/data/{code_file}")
    return text


QUERY = "How does the NYC Health Code define a gym"


# ---------------------------------------------------------------------------
# Build synthetic §17-188 chunk matches that mirror what Pinecone returns.
# §17-188 is a long section (8800+ chars) that the chunker splits into 6 parts
# at 2000-char word boundaries.  We reconstruct those chunks from the scraped
# source so the tests are deterministic and require no Pinecone call.
# ---------------------------------------------------------------------------

def _build_17_188_matches():
    scraper_dir = Path(__file__).resolve().parent.parent / "data" / "scrapers" / "nyc-admin-code" / "data"
    for f in sorted(scraper_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for sec in data.get("sections", []):
            if sec.get("section") == "17-188":
                title  = sec.get("title", "").strip()
                body   = sec.get("text",  "").strip()
                url    = data.get("source_url", "")
                # Replicate chunking_util.split_text with the FIXED word-boundary logic
                parts  = _split_text_word_boundary(body)
                matches = []
                for i, part in enumerate(parts):
                    chunk_text = f"{title}\n\n{part}"
                    matches.append({
                        "score": 0.85 - i * 0.01,
                        "metadata": {
                            "code": "NYC Admin Code",
                            "section": "17-188",
                            "section_title": title,
                            "source_url": url,
                            "text": chunk_text,
                        },
                    })
                return matches
    raise RuntimeError("§17-188 not found in nyc-admin-code scraped data")


def _split_text_word_boundary(text: str, max_chars: int = 2000) -> list:
    """Replicate the fixed split_text logic from chunking_util.py."""
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"\n\n|(?<=\s)(?=[a-z]\.\s)", text)
    chunks, current = [], ""
    for part in parts:
        if len(current) + len(part) + 1 <= max_chars:
            current += (" " if current else "") + part
        else:
            if current:
                chunks.append(current.strip())
            if len(part) > max_chars:
                start = 0
                while start < len(part):
                    end = start + max_chars
                    if end >= len(part):
                        chunks.append(part[start:].strip())
                        break
                    while end > start and not part[end].isspace():
                        end -= 1
                    if end == start:
                        end = start + max_chars
                    chunks.append(part[start:end].strip())
                    start = end
                current = ""
            else:
                current = part
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


MATCHES_17_188 = _build_17_188_matches()


# ---------------------------------------------------------------------------
# Deterministic tests (no API key required)
# ---------------------------------------------------------------------------

class TestGymDefinitionDataFormat(unittest.TestCase):
    """Verify §17-188 chunk text is compatible with ui/data so highlighting works.

    These tests require no API key — they check data format only.
    If any fail, passage highlighting is impossible regardless of model output.
    """

    @classmethod
    def setUpClass(cls):
        cls.sources   = cf._build_sources(MATCHES_17_188)
        cls.full_text = _ui_text("nyc-admin-code.json", "17-188")
        cls.norm_full = re.sub(r"\s+", " ", cls.full_text).strip()

    def _norm(self, s):
        return re.sub(r"\s+", " ", s).strip()

    def test_passage_text_has_no_mid_word_split(self):
        """passage_text must not contain a word broken across a \\n\\n boundary
        (the bug: 'de\\n\\nvelopment').  _join_chunk_bodies() should heal this."""
        pt = self.sources[0]["passage_text"]
        # A mid-word split leaves a \\n\\n immediately surrounded by word chars
        mid_word = re.search(r"[a-zA-Z]\n\n[a-z]", pt)
        self.assertIsNone(
            mid_word,
            f"passage_text has a mid-word \\n\\n split at: "
            f"{repr(pt[mid_word.start()-10:mid_word.end()+10])}"
            if mid_word else ""
        )

    def test_gym_definition_sentence_intact_in_passage_text(self):
        """The complete gym/health-club definition sentence must appear (normalised)
        in passage_text so the model can quote it verbatim."""
        key_phrase = "development of physical fitness or well-being that have a membership"
        pt = self.sources[0]["passage_text"]
        self.assertIn(
            key_phrase, self._norm(pt),
            "Key phrase from gym definition is missing from passage_text — "
            "mid-word split may not have been healed"
        )

    def test_gym_definition_findable_in_ui_data(self):
        """A passage quoting the gym definition must be findable (whitespace-
        normalised) in the full ui/data section text — the same check JS
        findNormalized applies before highlighting."""
        key_phrase = "health clubs that are commercial establishments offering instruction"
        self.assertIn(
            self._norm(key_phrase).lower(), self.norm_full.lower(),
            "Gym definition phrase not found in ui/data — highlighting will fail"
        )

    def test_ui_data_has_17_188(self):
        self.assertTrue(self.full_text, "§17-188 missing from ui/data/nyc-admin-code.json")


# ---------------------------------------------------------------------------
# Integration tests (require GOOGLE_API_KEY)
# ---------------------------------------------------------------------------

class TestGymDefinitionIntegration(unittest.TestCase):
    """End-to-end checks: summary contains the definition, passages are
    returned and are findable in ui/data for highlighting.

    Requires GOOGLE_API_KEY — skipped otherwise.
    """

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("GOOGLE_API_KEY"):
            raise unittest.SkipTest("GOOGLE_API_KEY not set")
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            cls.out      = cf.structure_response(QUERY, MATCHES_17_188)
            cls.sources  = cf._build_sources(MATCHES_17_188)
            cls.passages = cf._get_passages(QUERY, cls.sources)
        cls.summary      = cls.out["summary"]
        cls.citations    = cls.out["citations"]
        cls.full_text    = _ui_text("nyc-admin-code.json", "17-188")
        cls.norm_full    = re.sub(r"\s+", " ", cls.full_text).strip()

    def _norm(self, s):
        return re.sub(r"\s+", " ", s).strip()

    # --- summary checks ---

    def test_summary_cites_17_188(self):
        self.assertIn("17-188", self.summary,
            "§17-188 was not cited in the summary")

    def test_condition_1_summary_contains_gym_definition(self):
        """Issue: gym definition from §17-188 must appear in the summary.
        The summary should define what a gym/health club is, not just cite the AED rules."""
        gym_terms = {"health club", "health studio", "gymnasium", "physical fitness",
                     "martial arts", "health spa"}
        definition_terms = {"means", "shall mean", "is defined as", "defined as",
                            "includes", "include"}
        bullets = [l.strip() for l in self.summary.splitlines()
                   if re.match(r"^\s*[-*]\s", l) and "17-188" in l]
        self.assertGreater(len(bullets), 0,
            "No §17-188 bullets in summary")
        has_definition = any(
            any(gt in b.lower() for gt in gym_terms) and
            any(dt in b.lower() for dt in definition_terms)
            for b in bullets
        )
        self.assertTrue(has_definition,
            f"No §17-188 bullet defines gym/health club terms:\n" +
            "\n".join(bullets))

    # --- passage highlighting checks ---

    def test_condition_2_passages_returned_for_17_188(self):
        """Issue: §17-188 passage highlighting failed because the 2000-char brute-force
        chunker split 'development' mid-word, making passage_text unusable.
        _join_chunk_bodies() heals the split — passages must now be non-empty."""
        self.assertIn(0, self.passages,
            "_get_passages returned no entry for index 0 (§17-188)")
        self.assertGreater(len(self.passages[0]), 0,
            "_get_passages returned empty relevant_passages for §17-188 — "
            "mid-word split may not have been healed")

    def test_condition_3_passages_findable_in_ui_data(self):
        """Every passage returned for §17-188 must be findable in the full
        ui/data section text after whitespace normalisation — the same check
        JS findNormalized applies before highlighting."""
        for p in self.passages.get(0, []):
            p_norm = self._norm(p).lower()
            self.assertIn(
                p_norm, self.norm_full.lower(),
                f"Passage not findable in ui/data after whitespace normalisation:\n{p!r}"
            )

    def test_condition_4_gym_definition_passage_present(self):
        """The returned passages must include text from the gym/health-club
        definition subsection, not just the AED/defibrillator subsections."""
        gym_kw = {"health club", "health studio", "gymnasium", "physical fitness",
                  "martial arts", "health spa", "weight control"}
        passages = self.passages.get(0, [])
        has_gym_passage = any(
            any(kw in p.lower() for kw in gym_kw)
            for p in passages
        )
        self.assertTrue(has_gym_passage,
            "No passage contains gym/health-club definition terms — "
            "model may be quoting only the AED subsections:\n" +
            "\n".join(repr(p[:100]) for p in passages))


def _get_matches():
    structured = cf.structure_question(QUERY)
    return cf._pinecone_query(structured)


if __name__ == "__main__":
    unittest.main(verbosity=2)
