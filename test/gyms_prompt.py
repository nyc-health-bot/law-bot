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
        defines the regulated establishments (e.g. 'means any place...').
        When a retrieved source contains a definition relevant to the query, the first
        bullet must be that definition."""
        # Match true legal definitions: a capitalized term (optionally quoted) followed
        # by 'means' or 'shall mean' at the start of a sentence — not mid-sentence uses.
        definition_re = re.compile(
            r'(?:^|[.!?]\s+)'          # start of text or after sentence-ending punctuation
            r'(?:"[^"]+"|[A-Z]\w*(?:\s+\w+){0,4})'  # term: quoted or 1–5 capitalized words
            r'\s+(?:means|shall mean)\s+\w',          # followed immediately by 'means'
            re.MULTILINE
        )
        source_has_definition = any(
            "definition" in s.get("section_title", "").lower() or
            bool(definition_re.search(s["text"]))
            for s in self.citations
        )
        if not source_has_definition:
            self.skipTest("No definition found in retrieved sources for this run")

        bullet_lines = [l.strip() for l in self.summary.splitlines() if l.strip().startswith("- ")]
        self.assertGreater(len(bullet_lines), 0, "Summary has no bullet lines")

        first_bullet = bullet_lines[0].lower()
        self.assertTrue(
            bool(definition_re.search(bullet_lines[0])) or "means " in first_bullet or "shall mean " in first_bullet,
            f"First bullet is not a definition even though sources contain one:\n{bullet_lines[0]}"
        )


    def test_condition_4_irrelevant_sources_excluded(self):
        """Issue: refrigerator disposal regulations appeared in summary for gym query.
        Sources clearly unrelated to gyms (e.g. appliance disposal) must not be summarized."""
        irrelevant_terms = ["refrigerator"]
        for term in irrelevant_terms:
            self.assertNotIn(
                term, self.summary.lower(),
                f"Summary mentions '{term}' — not relevant to gym regulations"
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
