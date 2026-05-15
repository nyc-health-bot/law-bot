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


def query(query_text:str) -> list[str]:
    """
    1. Embeds the query using Gemini.
    2. Queries Pinecone for relevant chunks.
    """
    # 1. Get Embedding
    query_vector = embed_fn([query_text])[0]

    # 2. Search Pinecone
    query_url = f"{PINECONE_HOST}/query"
    pc_resp = post(url=query_url,
                            headers={"Api-Key": PINECONE_KEY, "Content-Type": "application/json"},
                            json={
                                "vector": query_vector,
                                "topK": 10,
                                "includeMetadata": True
                            }
                            )
    responses = pc_resp.json().get('matches', [])
    valid_responses = [r for r in responses if r.get('score') > .75]
    if not valid_responses:
        return ["I couldn't find any relevant sections in the NYC Health Code or NYS Sanitary Code for that question."]
    return valid_responses