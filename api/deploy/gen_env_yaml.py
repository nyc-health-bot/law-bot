#!/usr/bin/env python3
"""Generate env.yaml for GCP deployment from the repo-root .env file.

Reads: ../../.env  (two levels up from api/deploy/)
Writes: env.yaml   (in the same directory as this script)

Skips blank lines and comments. Strips surrounding quotes from values.
"""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else here.parent.parent / ".env"
out_path = here / "env.yaml"

if not env_path.exists():
    print(f"ERROR: {env_path} not found. Copy .env.example to .env and fill in real values.")
    sys.exit(1)

lines = []
for raw in env_path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if "=" in line:
        key, _, value = line.partition("=")
    elif ": " in line:
        key, _, value = line.partition(": ")
    else:
        continue
    value = value.strip().strip('"').strip("'")
    lines.append(f'{key.strip()}: "{value}"')

# Write with Unix line endings (gcloud requires LF)
out_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
print(f"Generated {out_path} ({len(lines)} variables)")
