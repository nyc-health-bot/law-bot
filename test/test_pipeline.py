"""Quick end-to-end pipeline test. Run from repo root: python test/test_pipeline.py"""
from dotenv import load_dotenv
load_dotenv()

import api.cloud_function as pipeline

query = "Can a restaurant owner appeal a health inspection grade in NYC?"

print("Structuring query...")
structured_question = pipeline.structure_question(query)
print(f"  → {structured_question}")

print("Fetching matches from Pinecone...")
matches = pipeline.get_values(structured_question)
print(f"  → {len(matches)} matches")

print("Generating response...")
response = pipeline.structure_response(query, matches)
print(response["summary"])
