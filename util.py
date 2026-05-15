import requests
import os
import time
from dotenv import load_dotenv
import numpy as np

load_dotenv()
PROXIES = {'http': os.getenv('PROXY'), 'https': os.getenv('PROXY')}
EMBED_MODEL = "models/gemini-embedding-001"
IN_CODESPACE = bool(os.getenv('CODESPACE_NAME'))


def post(**kwargs):
    if not IN_CODESPACE:
        kwargs.update({'proxies': PROXIES, 'verify': False})
    return requests.post(**kwargs)


def get(**kwargs):
    if not IN_CODESPACE:
        kwargs.update({'proxies': PROXIES, 'verify': False})
    return requests.get(**kwargs)


def truncate_vector(vector, target_dim=1024):
    truncated = np.array(vector[:target_dim])
    norm = np.linalg.norm(truncated)
    return (truncated / norm).tolist()


def embed_fn(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT", batch_size: int = 100, target_dim: int=1024) -> list[list[float]]:
    """
    Calls Google's batchEmbedContents REST endpoint.

    Args:
        texts: List of strings to embed.
        task_type: "RETRIEVAL_DOCUMENT" (indexing) or "RETRIEVAL_QUERY" (querying).
        batch_size: Number of texts per request (API limit is 100).
        target_dim: the number of dimensions for each vector
    """
    # The model is specified in the URL path here
    url = f"https://generativelanguage.googleapis.com/v1beta/{EMBED_MODEL}:batchEmbedContents"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": os.getenv('GOOGLE_API_KEY')
    }

    all_embeddings = []

    # Process in chunks to respect API limits
    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]

        # When model is in URL, it is NOT required in the payload requests
        payload = {
            "requests": [
                {
                    "model": EMBED_MODEL,
                    "content": {"parts": [{"text": t}]},
                    "taskType": task_type,
                }
                for t in batch
            ]
        }

        for attempt in range(5):
            try:
                resp = post(url=url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if "embeddings" in data:
                    for item in data['embeddings']:
                        truncated = truncate_vector(item['values'])
                        all_embeddings.append(truncated)
                else:
                    raise ValueError(f"API response did not contain 'embeddings': {data}")
                break
            except requests.exceptions.RequestException as e:
                if e.response is not None and e.response.status_code == 429:
                    wait = 2 ** attempt
                    print(f"Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"Request failed: {e}")
                    if e.response is not None:
                        print(f"Response body: {e.response.text}")
                    raise
        else:
            raise RuntimeError("Embedding request failed after 5 retries (rate limit)")

    return all_embeddings
