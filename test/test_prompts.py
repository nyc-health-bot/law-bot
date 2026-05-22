"""
Integration tests for prompt constraints in api/cloud_function.py.
Each test calls the real Gemini API and asserts that the model follows the
constraints stated in the prompt templates under api/prompts/.

Requires GOOGLE_API_KEY set in environment or a .env file at repo root.

Run from repo root:
    python test/test_prompts.py
    python -m pytest test/test_prompts.py -v
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
    """Load a prompt from the local api/prompts/ directory instead of GCS."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


# Two real-looking sources: one Definitions section, one substantive rule.
SAMPLE_MATCHES = [
    {
        "metadata": {
            "code": "NYC Health Code",
            "section": "81.03",
            "section_title": "Definitions",
            "source_url": "https://rules.cityofnewyork.us/rule/nyc-health-code-article-81/#81.03",
            "text": (
                "NYC Health Code §81.03\n\n"
                "Food establishment: means any place where food is stored, prepared, "
                "manufactured, packaged, transported, or sold for human consumption."
            ),
        }
    },
    {
        "metadata": {
            "code": "NYC Health Code",
            "section": "81.07",
            "section_title": "Food protection",
            "source_url": "https://rules.cityofnewyork.us/rule/nyc-health-code-article-81/#81.07",
            "text": (
                "NYC Health Code §81.07\n\n"
                "All food shall be protected from contamination during storage, preparation, "
                "transportation, and display. Potentially hazardous food shall be maintained "
                "at 45°F (7°C) or below or at 140°F (60°C) or above."
            ),
        }
    },
]
SAMPLE_SECTIONS = {"81.03", "81.07"}
SAMPLE_QUERY = "What temperature must potentially hazardous food be stored at in a NYC food establishment?"


# ---------------------------------------------------------------------------
# structure_question.txt
# Constraint: "Output ONLY the keywords, no explanation, no sentences, no formatting."
# ---------------------------------------------------------------------------

class TestStructureQuestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            cls.result = cf.structure_question(SAMPLE_QUERY)

    def test_returns_nonempty_string(self):
        self.assertIsInstance(self.result, str)
        self.assertTrue(self.result.strip(), "structure_question returned an empty string")

    def test_no_explanation_prefix(self):
        """Must not start with 'Keywords:', 'Answer:', 'Here are', etc."""
        lower = self.result.strip().lower()
        for phrase in ("keywords:", "answer:", "here are", "the following", "output:"):
            self.assertFalse(lower.startswith(phrase),
                f"Output starts with an explanation prefix {phrase!r}: {self.result!r}")

    def test_no_markdown_formatting(self):
        """Must not contain bullet points or Markdown headers."""
        self.assertNotRegex(self.result, r"(?m)^[-*#]",
            "Output contains Markdown bullets or headers — prompt says no formatting")

    def test_no_prose_sentences(self):
        """Lines should be short keyword phrases, not complete explanatory sentences."""
        for line in self.result.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            words = line.split()
            # A complete explanatory sentence: >10 words, starts uppercase, ends with period,
            # and does NOT contain a legal code abbreviation (those are legitimately longer)
            is_prose = (
                len(words) > 10
                and line[0].isupper()
                and line.endswith(".")
                and not re.search(r"\b(NYC|NYS|§)\b", line)
            )
            self.assertFalse(is_prose,
                f"Output line looks like a prose sentence: {line!r}")


# ---------------------------------------------------------------------------
# structure_response.txt
# Constraints tested:
#   - Summary is a markdown bulleted list (each rule starts with "- ")
#   - At most one non-bullet intro line; no prose paragraphs
#   - No bracketed index citations [0], [1], [2]
#   - All §-citations match provided source section numbers exactly
#   - No subsection qualifiers like §81.07(a) inside parenthetical citations
#   - Citation count equals number of unique (code, section) pairs
#   - Each citation object has all required keys
#   - cited_in_summary flag is accurate
#   - relevant_passages are complete sentences (not cut off mid-word/mid-sentence)
# ---------------------------------------------------------------------------

class TestStructureResponse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            cls.out = cf.structure_response(SAMPLE_QUERY, SAMPLE_MATCHES)
        cls.summary = cls.out["summary"]
        cls.citations = cls.out["citations"]

    def test_has_required_top_level_keys(self):
        self.assertIn("summary", self.out)
        self.assertIn("citations", self.out)

    def test_summary_is_nonempty_string(self):
        self.assertIsInstance(self.summary, str)
        self.assertTrue(self.summary.strip())

    def test_summary_contains_bullet_lines(self):
        """At least one line must start with '- '."""
        bullet_lines = [l for l in self.summary.splitlines() if l.strip().startswith("- ")]
        self.assertGreater(len(bullet_lines), 0,
            "Summary has no bullet lines — prompt requires a markdown bulleted list")

    def test_no_prose_paragraphs(self):
        """Every non-empty line must be a bullet ('- ') or a single allowed intro sentence."""
        non_empty = [l.strip() for l in self.summary.splitlines() if l.strip()]
        non_bullets = [l for l in non_empty if not l.startswith("- ")]
        # Prompt allows at most one intro sentence before the list
        self.assertLessEqual(len(non_bullets), 1,
            f"Multiple non-bullet lines found (prose paragraphs?): {non_bullets}")

    def test_no_bracketed_index_citations(self):
        """Must not cite [0], [1], [2] — prompt explicitly forbids this."""
        self.assertNotRegex(self.summary, r"\[\d+\]",
            "Summary contains bracketed index citations like [0] — prompt forbids this")

    def test_section_citations_only_from_provided_sources(self):
        """Every §XX.XX in the summary must be one of the retrieved source sections."""
        cited = {s.rstrip('.,;:') for s in re.findall(r"§([\w.\-]+)", self.summary)}
        unknown = cited - SAMPLE_SECTIONS
        self.assertEqual(unknown, set(),
            f"Summary cites unknown sections §{unknown} not in provided sources (hallucinated)")

    def test_no_subsection_qualifiers_in_citations(self):
        """§-citations must not have (a), (aa), (1) etc. appended — prompt forbids this."""
        self.assertNotRegex(self.summary, r"§[\w.\-]+\([a-z0-9]+\)",
            "Summary has subsection qualifiers like §81.07(a) — prompt forbids this")

    def test_citation_count_matches_source_count(self):
        """One citation object per unique (code, section) pair in the input."""
        self.assertEqual(len(self.citations), 2,
            f"Expected 2 citations (one per source), got {len(self.citations)}")

    def test_citation_objects_have_required_keys(self):
        required = {"anchor", "section", "code", "full_title", "section_title",
                    "url", "text", "relevant_passages", "cited_in_summary"}
        for i, c in enumerate(self.citations):
            missing = required - c.keys()
            self.assertEqual(missing, set(), f"Citation {i} is missing keys: {missing}")

    def test_cited_in_summary_is_accurate(self):
        """cited_in_summary must be True iff §section appears in the summary text."""
        cited_in_text = set(re.findall(r"§([\w.\-]+)", self.summary))
        for c in self.citations:
            expected = c["section"] in cited_in_text
            self.assertEqual(c["cited_in_summary"], expected,
                f"cited_in_summary wrong for §{c['section']} "
                f"(summary cites: {cited_in_text})")

    def test_relevant_passages_are_complete_sentences(self):
        """No passage should be cut off mid-word or mid-sentence."""
        for c in self.citations:
            for passage in c["relevant_passages"]:
                self.assertTrue(passage.strip(),
                    f"Empty passage in citation for §{c['section']}")
                self.assertRegex(passage.strip(), r"[.!?][\"')]?\s*$",
                    f"Passage appears cut off (missing end punctuation) in §{c['section']}: {passage!r}")


# ---------------------------------------------------------------------------
# structure_passages.txt
# Constraints tested:
#   - Returns exactly num_sources entries
#   - Each entry has an integer index and a list of passages
#   - All indices 0..n-1 are present
#   - Passages are complete sentences (not cut off)
#   - Passages are verbatim substrings of the corresponding source text
# ---------------------------------------------------------------------------

class TestGetPassages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            cls.sources = cf._build_sources(SAMPLE_MATCHES)
            cls.result = cf._get_passages(SAMPLE_QUERY, cls.sources)

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_all_source_indices_present(self):
        """Must return one entry per source (indices 0..n-1)."""
        for i in range(len(self.sources)):
            self.assertIn(i, self.result,
                f"Missing index {i} in passages result — prompt requires exactly {len(self.sources)} objects")

    def test_no_extra_indices(self):
        """Must not return more entries than sources."""
        self.assertEqual(len(self.result), len(self.sources),
            f"Got {len(self.result)} passage entries but expected {len(self.sources)}")

    def test_passages_are_lists(self):
        for idx, passages in self.result.items():
            self.assertIsInstance(passages, list,
                f"relevant_passages at index {idx} is not a list")

    def test_passages_are_complete_sentences(self):
        """Each passage must end with sentence-terminal punctuation."""
        for idx, passages in self.result.items():
            for p in passages:
                self.assertTrue(p.strip(),
                    f"Empty passage at source index {idx}")
                self.assertRegex(p.strip(), r"[.!?][\"')]?\s*$",
                    f"Passage at index {idx} appears cut off: {p!r}")

    def test_passages_are_verbatim_from_correct_source(self):
        """Each passage must appear verbatim (whitespace-normalized) in its own source."""
        for idx, passages in self.result.items():
            src_norm = re.sub(r"\s+", " ", self.sources[idx]["text"]).strip().lower()
            for p in passages:
                p_norm = re.sub(r"\s+", " ", p).strip().lower()
                self.assertIn(p_norm, src_norm,
                    f"Passage at index {idx} not found verbatim in source {idx}.\n"
                    f"Passage: {p!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
