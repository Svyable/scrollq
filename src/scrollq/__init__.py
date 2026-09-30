"""ScrolIQ diagnostics; the Python package retains the scrollq name."""

from .metrics import chunk_metrics
from .score import score_volume\nfrom .passport import alignment_manifest, build_passport

__all__ = ["alignment_manifest", "build_passport", "chunk_metrics", "score_volume"]
__version__ = "0.1.0"
