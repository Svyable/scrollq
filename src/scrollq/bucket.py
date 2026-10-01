"""Shared constants and helpers for the Vesuvius open-data bucket metadata.

A leaf module: it imports nothing else from ``scrollq`` so that tools that read
the bucket (chunk audit, prize manifests, protocol pairs) stay independent of
each other and can be reviewed or reverted separately.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

BUCKET_URL = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
BUCKET_S3 = "s3://vesuvius-challenge-open-data"
DEFAULT_INDEX = f"{BUCKET_URL}/metadata.min.json"


def load_json_maybe_gz(location: str):
    """Load JSON from a path or URL, transparently gunzipping.

    Returns ``(parsed, sha256_hex_of_decoded_bytes)``.
    """
    if re.match(r"https?://", location):
        import requests
        r = requests.get(location, timeout=60)
        r.raise_for_status()
        raw = r.content
    else:
        raw = Path(location).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def stable_seed(*parts) -> int:
    """Deterministic 32-bit seed from arbitrary parts (platform independent)."""
    h = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**32)
