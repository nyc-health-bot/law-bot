"""
Regression tests for the query: "what are environmental regulations for gyms"

Workflow:
  1. Run the query in the app and observe issues.
  2. Add a test for each issue in the CONDITIONS section below.
  3. Fix the underlying prompt or pipeline code.
  4. Run the full test suite to confirm the fix and check for regressions:
       python -m pytest test/ -v
     or:
       python -m unittest discover test/ -v

Each condition is a separate test method. When a condition is fixed, the test
should pass permanently — do not remove passing tests.
"""
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

def _local_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")

QUERY = "what are regulations for gyms"


class TestGymsPrompt(unittest.TestCase):
    """
    Each test method documents one observed condition (issue) with the gym query.
    Add new test methods as new issues are reported.
    """

    @classmethod
    def setUpClass(cls):
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            matches = _get_matches()
            cls.out = cf.structure_response(QUERY, matches)
        cls.summary = cls.out["summary"]
        cls.citations = cls.out["citations"]
        cls.source_sections = {c["section"] for c in cls.citations}
        if not cls.citations:
            raise RuntimeError(f"structure_response returned no citations — likely a Gemini error:\n{cls.summary}")

    # ------------------------------------------------------------------
    # Baseline structural checks (always apply — never remove these)
    # ------------------------------------------------------------------

    def test_baseline_has_summary(self):
        self.assertIsInstance(self.summary, str)
        self.assertTrue(self.summary.strip(), "Summary is empty")

    def test_baseline_has_citations(self):
        self.assertIsInstance(self.citations, list)
        self.assertGreater(len(self.citations), 0, "No citations returned")

    def test_baseline_summary_has_bullets(self):
        bullet_lines = [l for l in self.summary.splitlines() if l.strip().startswith("- ")]
        self.assertGreater(len(bullet_lines), 0, "Summary has no bullet lines")

    def test_baseline_no_hallucinated_citations(self):
        cited = {s.rstrip('.,;:') for s in re.findall(r"§([\w.\-]+)", self.summary)}
        unknown = cited - self.source_sections
        self.assertEqual(unknown, set(),
            f"Summary cites §{unknown} which are not in the retrieved sources")

    def test_baseline_no_index_citations(self):
        self.assertNotRegex(self.summary, r"\[\d+\]",
            "Summary contains bracketed index citations like [0]")

    # ------------------------------------------------------------------
    # CONDITIONS — add one test method per observed issue
    # ------------------------------------------------------------------

    def test_condition_1_multi_requirement_provisions_split_into_separate_bullets(self):
        """Issue: §17-188 AED scope definition, equipment requirement, and notice requirement
        were combined into a single paragraph-length bullet. Each distinct requirement must
        be its own bullet; multiple bullets may share the same §-citation."""
        for line in self.summary.splitlines():
            if not line.strip().startswith("- "):
                continue
            # Strip trailing §-citation group before counting sentences
            text = re.sub(r'\s*\((?:§[\w.\-]+(?:,\s*)?)+\)\s*$', '', line.strip())
            # Count sentence boundaries: punctuation followed by a space and capital letter
            boundaries = len(re.findall(r'[.!?]\s+[A-Z]', text))
            sentence_count = boundaries + 1
            self.assertLessEqual(
                sentence_count, 3,
                f"Bullet has {sentence_count} sentences — split into multiple bullets (max 3 sentences each):\n{line.strip()}"
            )

    def test_condition_1b_aed_section_produces_multiple_bullets(self):
        """Issue: all §17-188 requirements (scope, equipment, notice) appeared in one bullet.
        When §17-188 is retrieved it must produce at least 2 separate bullets."""
        if "17-188" not in self.source_sections:
            self.skipTest("§17-188 not in retrieved sources for this run")
        bullets = [
            l.strip() for l in self.summary.splitlines()
            if l.strip().startswith("- ") and "17-188" in l
        ]
        self.assertGreaterEqual(
            len(bullets), 2,
            f"§17-188 should produce multiple bullets (scope, equipment, notice) but got {len(bullets)}:\n"
            + "\n".join(bullets)
        )

    def test_condition_2_aed_section_cited_when_retrieved(self):
        """Issue: §17-188 (AED/defibrillator requirements) was retrieved but no longer
        appeared anywhere in the summary after the one-sentence-per-bullet prompt change."""
        if "17-188" not in self.source_sections:
            self.skipTest("§17-188 not in retrieved sources for this run")
        self.assertIn(
            "17-188", self.summary,
            "§17-188 was retrieved but is not cited anywhere in the summary"
        )

    def test_condition_3_definitions_appear_first(self):
        """Issue: summary no longer started with a definition bullet even when a source
        defines the regulated establishments (e.g. 'health studio means any place...').
        When a retrieved source contains a gym-relevant definition, the first bullet must
        be that definition. Generic administrative definitions (e.g. 'Adequate means...')
        do not count — only definitions of gym/fitness/regulated-entity terms trigger this."""
        definition_re = re.compile(
            r'(?:^|[.!?]\s+)'
            r'(?:"[^"]+"|[A-Z]\w*(?:\s+\w+){0,4})'
            r'\s+(?:means|shall mean)\s+\w',
            re.MULTILINE
        )
        gym_terms = {"gym", "health studio", "health club", "health spa", "gymnasium",
                     "fitness", "pool", "swimming", "bathing", "exercise", "locker",
                     "athletic", "martial arts", "physical fitness"}
        # Only trigger when a source defines a gym/fitness-relevant term, not generic
        # administrative definitions like "Adequate means..." or "Approved means..."
        source_has_gym_definition = any(
            (
                "definition" in s.get("section_title", "").lower() or
                bool(definition_re.search(s["text"]))
            ) and any(term in s["text"].lower() for term in gym_terms)
            for s in self.citations
        )
        if not source_has_gym_definition:
            self.skipTest("No gym-relevant definition in retrieved sources for this run")

        bullet_lines = [l.strip() for l in self.summary.splitlines() if l.strip().startswith("- ")]
        self.assertGreater(len(bullet_lines), 0, "Summary has no bullet lines")

        first_bullet = bullet_lines[0].lower()
        has_def_first = (
            bool(definition_re.search(bullet_lines[0])) or
            "means " in first_bullet or
            "shall mean " in first_bullet
        )
        also_gym_relevant = any(term in first_bullet for term in gym_terms)
        self.assertTrue(
            has_def_first and also_gym_relevant,
            f"First bullet is not a gym-relevant definition even though sources contain one:\n{bullet_lines[0]}"
        )


    def test_condition_4_irrelevant_sources_excluded(self):
        """Issue: refrigerator disposal regulations appeared in summary for gym query.
        Observed: '- Every person who discards a refrigerator must remove the refrigerator door,
        locking device, or hinges before placing the refrigerator on the street for collection. (§131.13)'
        Root cause: §131.13 is a mixed-content chunk — subsection (b) is about ventilation
        (relevant to gyms) so the chunk scores into the top-30, but subsection (c) is about
        refrigerator disposal (not relevant). The model must skip the refrigerator subsection
        even when summarizing the ventilation subsection from the same source."""
        fridge_match = {
            "score": 0.70,
            "metadata": {
                "code": "NYC Health Code",
                "section": "131.13",
                "section_title": "Control of unsafe conditions",
                "source_url": "https://rules.cityofnewyork.us/rule/nyc-health-code-article-131/#131.13",
                "text": (
                    "NYC Health Code §131.13\n\n"
                    "Control of unsafe conditions\n\n"
                    "(a) Contaminants. When activities conducted within a building result in the production of "
                    "contaminants that the Department determines are harmful to public health, the Department "
                    "may order the owner or person in control of the building to take such measures that the "
                    "Department determines are necessary to eliminate or reduce such conditions so that they are "
                    "no longer harmful to the public health.\n"
                    "(b) Ventilation. When required by the Department mechanical ventilating systems, devices "
                    "for the control of dust, gases, vapors and fumes, abatement devices, or other means of "
                    "reducing conditions dangerous to health shall be installed and maintained in a building or "
                    "surrounding premises by persons in control of such building or premises.\n"
                    "(c) Discarding refrigerators. Every person who discards a refrigerator shall remove the "
                    "refrigerator door, locking device or hinges before placing the refrigerator on the street "
                    "for collection by DOS or other waste removal service."
                ),
            },
        }
        gym_match = {
            "score": 0.75,
            "metadata": {
                "code": "NYC Health Code",
                "section": "165.01",
                "section_title": "Swimming pools — general requirements",
                "source_url": "https://rules.cityofnewyork.us/rule/nyc-health-code-article-165/#165.01",
                "text": (
                    "NYC Health Code §165.01\n\n"
                    "No person shall operate a public swimming pool without a permit issued by the Department."
                ),
            },
        }
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            result = cf.structure_response(QUERY, [gym_match, fridge_match])
        # §131.13 may legitimately appear (cited for its ventilation/contaminant subsections)
        # but the refrigerator disposal content must never appear
        self.assertNotIn(
            "refrigerator", result["summary"].lower(),
            "Model included refrigerator disposal in gym summary — RELEVANCE rule not followed"
        )

    def test_condition_5_gym_definition_cited_when_retrieved(self):
        """Issue: no definition of 'gym'/'health studio'/'gymnasium' appeared even when a
        retrieved source contains the definition. When sources define what constitutes a gym
        or fitness establishment, that definition must appear in the summary."""
        gym_terms = {"health studio", "health club", "gymnasium", "physical fitness",
                     "fitness center", "exercise equipment", "martial arts"}
        definition_re = re.compile(
            r'(?:^|[.!?]\s+)'
            r'(?:"[^"]+"|[A-Z][^.!?]{0,60})'
            r'\s+(?:means|shall mean|is defined as)\s+',
            re.MULTILINE,
        )
        source_defines_gym = any(
            bool(definition_re.search(c["text"])) and
            any(term in c["text"].lower() for term in gym_terms)
            for c in self.citations
        )
        if not source_defines_gym:
            self.skipTest("No retrieved source defines a gym/fitness establishment — skip")
        bullet_lines = [l.strip() for l in self.summary.splitlines() if l.strip().startswith("- ")]
        has_gym_definition = any(
            any(term in l.lower() for term in gym_terms) and
            ("means" in l.lower() or "shall mean" in l.lower() or "is defined as" in l.lower())
            for l in bullet_lines
        )
        self.assertTrue(
            has_gym_definition,
            "A source defines a gym/fitness establishment but the definition is missing from the summary"
        )


def _get_matches():
    """
    Return Pinecone matches for the gym query by calling the real pipeline.
    Results are fetched once and reused across all tests in this module.
    """
    structured = cf.structure_question(QUERY)
    return cf._pinecone_query(structured)


# ---------------------------------------------------------------------------
# §165.63 passage highlighting
# ---------------------------------------------------------------------------

def _sauna_chunk_text():
    """Return the chunk text for §165.63 as the chunker would produce it."""
    import json as _json
    article_path = Path(__file__).resolve().parent.parent / "data" / "scrapers" / "nyc-health-code" / "data" / "article_165.json"
    data = _json.loads(article_path.read_text(encoding="utf-8"))
    for sec in data.get("sections", []):
        if sec.get("section") == "165.63":
            body = sec.get("text", "").strip()
            # Replicate _clean_body: remove bare digit lines; drop blank lines mid-sentence
            lines = body.split("\n")
            lines = [l for l in lines if not re.match(r"^\s*\d+\s*$", l)]
            result = []
            for line in lines:
                if not line.strip():
                    last = next((l for l in reversed(result) if l.strip()), "")
                    if last and not re.search(r"[.!?:;]\s*$", last.rstrip()):
                        continue
                result.append(line)
            cleaned = "\n".join(result)
            return f"Sauna and Steam Rooms\n\n{cleaned}"
    raise RuntimeError("§165.63 not found in article_165.json")


def _ui_data_text(section: str) -> str:
    ui_path = Path(__file__).resolve().parent.parent / "ui" / "data" / "nyc-health-code.json"
    import json as _json
    data = _json.loads(ui_path.read_text(encoding="utf-8"))
    text = data.get(section)
    if text is None:
        raise RuntimeError(f"§{section} not found in ui/data/nyc-health-code.json")
    return text


SAUNA_MATCH = {
    "score": 0.79,
    "metadata": {
        "code": "NYC Health Code",
        "section": "165.63",
        "section_title": "Sauna and Steam Rooms",
        "source_url": "https://rules.cityofnewyork.us/rule/nyc-health-code-article-165/#165.63",
        "text": _sauna_chunk_text(),
    },
}


class TestSaunaPassagesDataFormat(unittest.TestCase):
    """Deterministic checks that §165.63 chunk text is compatible with ui/data.

    These tests require no API key — they verify the data format only.
    If any of these fail the highlighting can never work regardless of what the
    model returns.
    """

    @classmethod
    def setUpClass(cls):
        cls.chunk_text = SAUNA_MATCH["metadata"]["text"]
        # passage_text = chunk_text after stripping first paragraph (section title)
        cls.passage_text = cls.chunk_text.split("\n\n", 1)[1] if "\n\n" in cls.chunk_text else cls.chunk_text
        cls.full_text = _ui_data_text("165.63")
        cls.norm_full = re.sub(r"\s+", " ", cls.full_text).strip()

    def _norm(self, s):
        return re.sub(r"\s+", " ", s).strip()

    def test_passage_text_sentences_findable_in_ui_data(self):
        """Every complete sentence from passage_text must be findable in ui/data after
        whitespace normalisation — the same transform JS findNormalized applies."""
        # Split passage_text into sentences at subsection boundaries
        sentence_re = re.compile(r"(?<=\.)\s+(?=\()")
        sentences = [s.strip() for s in sentence_re.split(self.passage_text) if s.strip()]
        missing = []
        for s in sentences:
            if len(s) < 20:
                continue  # skip very short fragments
            if self._norm(s).lower() not in self.norm_full.lower():
                missing.append(s)
        self.assertEqual(
            missing, [],
            "These chunk sentences cannot be found in ui/data after whitespace normalisation "
            "(highlighting will fail for them):\n" + "\n".join(repr(s[:120]) for s in missing)
        )

    def test_ui_data_has_sauna_section(self):
        """ui/data/nyc-health-code.json must have a '165.63' key."""
        self.assertTrue(self.full_text, "§165.63 is empty or missing in ui/data")

    def test_passage_text_starts_with_body_not_title(self):
        """passage_text must NOT start with 'Sauna and Steam Rooms' — the title
        should have been stripped so the model quotes body text only."""
        self.assertFalse(
            self.passage_text.startswith("Sauna"),
            f"passage_text unexpectedly starts with section title: {self.passage_text[:80]!r}"
        )


class TestSaunaPassagesIntegration(unittest.TestCase):
    """Integration test: _get_passages for §165.63 returns passages that are
    findable in the full ui/data section text.

    Requires GOOGLE_API_KEY — skipped otherwise.
    """

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("GOOGLE_API_KEY"):
            raise unittest.SkipTest("GOOGLE_API_KEY not set — skipping integration test")
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            cls.sources = cf._build_sources([SAUNA_MATCH])
            cls.passages = cf._get_passages("what are regulations for gyms", cls.sources)
        cls.full_text = _ui_data_text("165.63")
        cls.norm_full = re.sub(r"\s+", " ", cls.full_text).strip()

    def _norm(self, s):
        return re.sub(r"\s+", " ", s).strip()

    def test_returns_passages_for_sauna_source(self):
        """_get_passages must return at least one passage for §165.63."""
        self.assertIn(0, self.passages, "_get_passages returned no entry for index 0 (§165.63)")
        self.assertGreater(
            len(self.passages[0]), 0,
            "_get_passages returned empty relevant_passages for §165.63"
        )

    def test_passages_findable_in_ui_data(self):
        """Every returned passage must be findable in ui/data after whitespace
        normalisation — the same transform JS findNormalized applies."""
        for p in self.passages.get(0, []):
            p_norm = self._norm(p).lower()
            self.assertIn(
                p_norm, self.norm_full.lower(),
                f"Passage not findable in ui/data after whitespace normalisation:\n{p!r}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
