"""Quick end-to-end pipeline test. Run from repo root: python test/test_pipeline.py"""
import sys
from pathlib import Path

from test._env import load_env
load_env()
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api.cloud_function as pipeline

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "api" / "prompts"

def _local_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


if __name__ == "__main__":
    query = "Can a restaurant owner appeal a health inspection grade in NYC?"

    with patch.object(pipeline, "_get_prompt", side_effect=_local_prompt):
        print("Structuring query...")
        structured_question = pipeline.structure_question(query)
        print(f"  → {structured_question}")

        print("Fetching matches from Pinecone...")
        matches = pipeline._pinecone_query(structured_question)
        print(f"  → {len(matches)} matches")

        print("Generating response...")
        response = pipeline.structure_response(query, matches)
        print(response["summary"])
