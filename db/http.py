import requests
import os
import time

EMBED_MODEL = "models/gemini-embedding-001"


def truncate_vector(vector, target_dim=1024):
    import numpy as np
    truncated = np.array(vector[:target_dim])
    norm = np.linalg.norm(truncated)
    return (truncated / norm).tolist()


def embed_fn(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT", batch_size: int = 100, target_dim: int = 1024) -> list[list[float]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/{EMBED_MODEL}:batchEmbedContents"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": os.getenv("GOOGLE_API_KEY"),
    }

    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
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
                resp = requests.post(url=url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if "embeddings" in data:
                    for item in data["embeddings"]:
                        all_embeddings.append(truncate_vector(item["values"], target_dim))
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


def normalize_text(s: str) -> str:
    if s is None:
        return s
    import unicodedata, re, html

    s = html.unescape(s)
    s = s.replace('﻿', '').replace(' ', ' ')
    s = s.replace('Â', '')
    s = s.replace('\xc2', '')
    s = s.replace('§', '§')
    s = s.replace('\\u00a7', '§')
    s = re.sub(r'[\r\x00\x0b\x0c]', '', s)
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.replace('\\u00a0', ' ')
    s = s.replace('\\xc2', '')
    s = re.sub(r'\s*\(\s*§', ' (§', s)
    s = re.sub(r'§\s*\)', '§)', s)
    return s
