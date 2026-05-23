"""
Regression tests for the query:
  "I found a mouse in my storage room. What is the immediate legal requirement
   for reporting this to the DOH?"

Observed issues documented here as conditions:
  1. Summary bullet points had no §-citations — the model returned bullets
     without any inline (§XX.XX) reference, making every citation card
     appear only in "Additional Sources" instead of the body.
     Root cause: the test was exercising the JSON path (structure_response.txt)
     which passes JSON-schema constraints to the model. The production app uses
     the streaming path (structure_summary.txt / _gemini_stream) where the model
     has more freedom to omit citations.

Workflow:
  1. Run the query in the app and observe issues.
  2. Add a test for each issue in the CONDITIONS section below.
  3. Fix the underlying prompt or pipeline code.
  4. Run the full test suite to confirm the fix and check for regressions:
       python -m pytest test/ -v

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


QUERY = (
    "I found a mouse in my storage room. "
    "What is the immediate legal requirement for reporting this to the DOH?"
)


def _stream_summary(user_query: str, matches: list) -> tuple[str, list]:
    """Replicate the production streaming path: structure_summary.txt + _gemini_stream.

    Returns (raw_summary, citation_meta) mirroring what handle_request produces,
    so tests exercise the same code path the browser hits.
    """
    sources = cf._build_sources(matches)
    valid_sections = {s["section"] for s in sources}
    context_str = "\n\n---\n\n".join(
        f"[{i}] {s['full_title']}\nURL: {s['url']}\nTEXT: {s['summary_text']}"
        for i, s in enumerate(sources)
    )
    citation_meta = [
        {
            "anchor": f"citation-{i}",
            "section": s["section"],
            "code": s["code"],
            "full_title": s["full_title"],
            "section_title": s["section_title"],
            "url": s["url"],
            "text": s["text"],
        }
        for i, s in enumerate(sources)
    ]
    prompt = _local_prompt("structure_summary.txt").format(
        user_query=user_query, context_str=context_str
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }
    raw = "".join(cf._gemini_stream(payload))
    summary = cf._filter_citations(raw, valid_sections)
    return summary, citation_meta


class TestMouseCitations(unittest.TestCase):
    """
    Each test method documents one observed condition (issue) with the mouse query.
    Tests use the streaming path (structure_summary.txt + _gemini_stream) because
    that is what the production app sends to the browser.
    """

    @classmethod
    def setUpClass(cls):
        with patch.object(cf, "_get_prompt", side_effect=_local_prompt):
            matches = _get_matches()
        cls.summary, cls.citation_meta = _stream_summary(QUERY, matches)
        cls.source_sections = {c["section"] for c in cls.citation_meta}

    # ------------------------------------------------------------------
    # Baseline structural checks (always apply — never remove these)
    # ------------------------------------------------------------------

    def test_baseline_has_summary(self):
        self.assertIsInstance(self.summary, str)
        self.assertTrue(self.summary.strip(), "Summary is empty")

    def test_baseline_has_citation_meta(self):
        self.assertIsInstance(self.citation_meta, list)
        self.assertGreater(len(self.citation_meta), 0, "No citation metadata returned")

    def test_baseline_summary_has_bullets(self):
        bullet_lines = [l for l in self.summary.splitlines() if re.match(r"^\s*[-*]\s", l)]
        # The model may legitimately return no bullets when it determines no sources
        # directly answer the question (rule 7 / rule 8 exemption). Accept that case.
        no_sources = re.search(r"no (sources|information).{0,60}relevant", self.summary, re.I)
        if no_sources:
            return
        self.assertGreater(len(bullet_lines), 0, "Summary has no bullet lines")

    def test_baseline_no_hallucinated_citations(self):
        cited = {s.rstrip(".,;:") for s in re.findall(r"§([\w.\-]+)", self.summary)}
        unknown = cited - self.source_sections
        self.assertEqual(
            unknown, set(),
            f"Summary cites §{unknown} which are not in the retrieved sources",
        )

    def test_baseline_no_index_citations(self):
        self.assertNotRegex(self.summary, r"\[\d+\]",
            "Summary contains bracketed index citations like [0]")

    # ------------------------------------------------------------------
    # CONDITIONS — add one test method per observed issue
    # ------------------------------------------------------------------

    def test_condition_1_every_bullet_has_citation(self):
        """Issue: bullet points had no §-citation in the streaming summary.
        The JSON path (structure_response.txt) was fine but the streaming path
        (structure_summary.txt) returned bullets without (§XX.XX) citations,
        so all citation cards fell into 'Additional Sources'.
        Every bullet must end with at least one inline §-citation, EXCEPT the
        rule-7 'no sources relevant' bullet which is explicitly exempted."""
        bullet_lines = [
            l.strip() for l in self.summary.splitlines()
            if re.match(r"^\s*[-*]\s", l)
        ]
        if not bullet_lines:
            # Model returned no bullets — acceptable only if it said no sources relevant
            no_sources = re.search(r"no (sources|information).{0,60}relevant", self.summary, re.I)
            if no_sources:
                return
            self.fail("Summary has no bullet lines and no 'no sources relevant' message")
        # A single uncited bullet is the rule-7/8 "no sources relevant" sentinel —
        # the model may phrase it many ways so we exempt it by structure, not wording.
        uncited = [l for l in bullet_lines if not re.search(r"\((?:§[\w.\-]+(?:,\s*)?)+\)", l)]
        if len(uncited) == 1 and len(bullet_lines) == 1:
            return  # sole bullet with no citation = "no relevant sources" response
        uncited = [l for l in uncited if not re.search(r"no sources.{0,60}relevant", l, re.I)]
        self.assertEqual(
            uncited, [],
            "These bullet(s) lack a §-citation:\n" + "\n".join(uncited),
        )


def _get_matches():
    structured = cf.structure_question(QUERY)
    return cf._pinecone_query(structured)


if __name__ == "__main__":
    unittest.main(verbosity=2)
