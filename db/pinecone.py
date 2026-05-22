import requests
import os
from pathlib import Path
from dotenv import load_dotenv
import numpy as np
from util import get, post, embed_fn

# load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")
PINECONE_HOST = os.getenv("PINECONE_HOST")
PINECONE_KEY = os.getenv("PINECONE_API_KEY")



def get_index_stats():
    resp = get(
        url = f"{PINECONE_HOST}/describe_index_stats",
        headers={"Api-Key": os.getenv("PINECONE_API_KEY")},
    )
    print(resp.json())


def clear_index():
    resp = post(
        url=f"{PINECONE_HOST}/vectors/delete",
        headers={"Api-Key": os.getenv("PINECONE_API_KEY"), "Content-Type": "application/json"},
        json={"deleteAll": True},
    )
    resp.raise_for_status()
    print("Index cleared.")


def upload_chunks(chunks: list[dict], batch_size: int = 100) -> None:
    url = f"{PINECONE_HOST}/vectors/upsert"
    headers = {
        "Api-Key": os.getenv('PINECONE_API_KEY'),
        "Content-Type": "application/json",
    }

    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]

        vectors = embed_fn([c["text"] for c in batch])

        payload = {
            "vectors": [
                {"id": c["id"], "values": vec, "metadata": c["metadata"]}
                for c, vec in zip(batch, vectors)
            ]
        }

        resp = post(url=url, headers=headers, json=payload)
        if not resp.ok:
            print(f"Pinecone error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        total += len(batch)
        print(f"Upserted {total}/{len(chunks)}")

    print("Done.")


def query(query_text: str, max_sections: int = 6) -> list[dict]:
    """
    Embeds the query, fetches topK=30 chunks, then returns all chunks belonging
    to the top max_sections unique (code, section) pairs by best chunk score.
    """
    query_vector = embed_fn([query_text], task_type='RETRIEVAL_QUERY')[0]

    pc_resp = post(
        url=f"{PINECONE_HOST}/query",
        headers={"Api-Key": PINECONE_KEY, "Content-Type": "application/json"},
        json={"vector": query_vector, "topK": 30, "includeMetadata": True},
    )
    matches = [m for m in pc_resp.json().get('matches', []) if m.get('score', 0) > 0.5]

    # Rank unique sections by their best chunk score
    section_best = {}
    for m in matches:
        meta = m['metadata']
        key = (meta.get('code', ''), meta.get('section', ''))
        score = m.get('score', 0)
        if key not in section_best or score > section_best[key]:
            section_best[key] = score

    top_sections = set(
        sorted(section_best, key=lambda k: section_best[k], reverse=True)[:max_sections]
    )

    return [m for m in matches if (m['metadata'].get('code', ''), m['metadata'].get('section', '')) in top_sections]