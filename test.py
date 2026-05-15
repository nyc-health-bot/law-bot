import os
from dotenv import load_dotenv

load_dotenv()
from pinecone import query_pinecone  # or whatever your pinecone.py exposes
from util import embed_fn, post

query = "live animals prohibited food service establishment"

vector = embed_fn([query], task_type="RETRIEVAL_QUERY")[0]

pc_resp = post(
    url=f"{os.getenv('PINECONE_HOST')}/query",
    headers={"Api-Key": os.getenv("PINECONE_API_KEY"), "Content-Type": "application/json"},
    json={"vector": vector, "topK": 5, "includeMetadata": True}
)

for m in pc_resp.json().get("matches", []):
    print(f"{m['score']:.4f} | {m['metadata'].get('code')} §{m['metadata'].get('section')} | {m['metadata'].get('section_title')}")
    print(f"       {m['metadata'].get('char_count')} chars | {m['metadata'].get('text', '')[:80]}")
    print()