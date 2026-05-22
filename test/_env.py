"""Shared .env loader for tests. Handles both KEY=value and KEY: "value" formats."""
import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
        elif ": " in line:
            key, _, value = line.partition(": ")
        else:
            continue
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
