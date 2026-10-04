#!/usr/bin/env python3
"""Census the public VC3D fibers of one scroll and range-check them against
every public CT volume of that scroll (November N4b, pulled into October).

Generalizes ``fiber_corpus_campaign.py`` (PHercParis4) to any scroll under the
Hugging Face ``scrollprize/datasets`` bucket ``spiral/<scroll>/fibers``.

There are no previously pinned fibers for a new scroll, so the positive
controls are different:

* the listing must be non-empty and every listed object must download and
  parse (a clean census of nothing is ``unverified``, AGENTS.md lesson 9);
* detector control: a synthetic break (one step stretched to 10x the median)
  planted into a copy of every audited fiber must be reported as a gap by
  ``audit_vc3d_json``; any miss makes the census ``unverified``.

The volume range check is the same rule as ``paris4_fiber_binding.py``: a
volume is ruled out when its level-0 shape cannot contain every point.
Compatibility never establishes a binding.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fiber_corpus_campaign import _compact, _next_link, json_names_from_hf_api  # noqa: E402
from paris4_fiber_binding import compatible, level0_shape  # noqa: E402
from scrollq.fiber_audit import audit_vc3d_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "artifacts/2026-10-01-bucket-index/metadata.min.json.gz"
HF_API = "https://huggingface.co/api/buckets/scrollprize/datasets/tree/spiral/{scroll}/fibers"
HF_RESOLVE = "https://huggingface.co/buckets/scrollprize/datasets/resolve/spiral/{scroll}/fibers"
UA = {"User-Agent": "scrollq-fiber-scroll-census/1"}


def _get(url: str) -> tuple[bytes, dict[str, str]]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read(), {k.lower(): v for k, v in r.headers.items()}


def list_fibers(scroll: str) -> list[str]:
    pages, url = [], HF_API.format(scroll=scroll) + "?recursive=false"
    while url:
        body, headers = _get(url)
        pages.append(json.loads(body))
        url = _next_link(headers)
    prefix = f"spiral/{scroll}/fibers/"
    names = json_names_from_hf_api(pages)
    # Keep only direct children of the fibers/ directory.
    direct = set()
    for page in pages:
        for e in page if isinstance(page, list) else page.get("entries", []):
            p = str(e.get("path", ""))
            if p.startswith(prefix) and "/" not in p[len(prefix):] and p.endswith(".json"):
                direct.add(p[len(prefix):])
    return sorted(n for n in names if n in direct)


def plant_break(obj: dict[str, Any], factor: float = 10.0) -> tuple[dict[str, Any], int] | None:
    """Stretch the middle non-zero step to ``factor`` x the median step."""
    line = np.asarray(obj["line_points"], float)
    if len(line) < 4:
        return None
    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    pos = steps[steps > 0]
    if not pos.size:
        return None
    med = float(np.median(pos))
    j = len(steps) // 2
    while j < len(steps) and steps[j] == 0:
        j += 1
    if j >= len(steps):
        return None
    direction = (line[j + 1] - line[j]) / steps[j]
    shift = direction * (factor * med - steps[j])
    out = copy.deepcopy(obj)
    new = line.copy()
    new[j + 1:] += shift
    out["line_points"] = new.tolist()
    return out, j


def scroll_volumes(scroll: str) -> list[str]:
    text = gzip.open(INDEX, "rt").read()
    return sorted(set(re.findall(rf"{re.escape(scroll)}/volumes/[^\"/]+\.zarr", text)))


def audit_one(scroll: str, name: str, tmp: Path) -> dict[str, Any]:
    url = f"{HF_RESOLVE.format(scroll=scroll)}/{name}"
    try:
        payload, _ = _get(url + "?download=true")
    except Exception as exc:
        return {"file": name, "source_url": url, "status": "download-fail", "error": str(exc)}
    path = tmp / name
    path.write_bytes(payload)
    try:
        obj = json.loads(payload)
        audit = audit_vc3d_json(path)
    except Exception as exc:
        return {"file": name, "source_url": url, "status": "audit-error",
                "sha256": hashlib.sha256(payload).hexdigest(), "error": str(exc)}
    row = _compact(name, audit)
    row["source_url"] = url
    pts = np.asarray(obj.get("line_points", []) + [c["position"] for c in obj.get("control_points", [])
                                                     if isinstance(c, dict) and "position" in c], float)
    row["bbox_min"] = pts.min(axis=0).tolist() if len(pts) else None
    row["bbox_max"] = pts.max(axis=0).tolist() if len(pts) else None
    planted = plant_break(obj)
    if planted is None:
        row["detector_control"] = "not-applicable"
    else:
        pobj, j = planted
        ppath = tmp / f"planted-{name}"
        ppath.write_text(json.dumps(pobj))
        paudit = audit_vc3d_json(ppath)
        hit = any(f.get("kind") == "gap" and f.get("segment") == j for f in paudit.get("findings", []))
        row["detector_control"] = "detected" if hit else "missed"
    return row


def run(scroll: str, workers: int) -> dict[str, Any]:
    try:
        names = list_fibers(scroll)
        listing_error = None
    except Exception as exc:
        names, listing_error = [], f"{type(exc).__name__}: {exc}"
    with tempfile.TemporaryDirectory() as tmp:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(lambda n: audit_one(scroll, n, Path(tmp)), names))
    statuses = Counter(r["status"] for r in rows)
    audited = [r for r in rows if r["status"] in ("pass", "caution", "fail")]
    controls = Counter(r.get("detector_control") for r in audited)
    failures = sum(statuses.get(k, 0) for k in ("download-fail", "audit-error"))
    if not rows or controls.get("missed") or not controls.get("detected"):
        verdict = "unverified"
    elif failures:
        verdict = "incomplete"
    else:
        verdict = "complete"

    def tot(k):
        return sum(int(r.get(k) or 0) for r in audited)

    with_box = [r for r in audited if r.get("bbox_min")]
    lo = np.min([r["bbox_min"] for r in with_box], axis=0).tolist() if with_box else None
    hi = np.max([r["bbox_max"] for r in with_box], axis=0).tolist() if with_box else None
    vols = []
    for v in scroll_volumes(scroll):
        shape = level0_shape(v)
        vols.append({"volume": v, "level0_shape_zyx": shape,
                     "compatible": None if shape is None or lo is None or failures else compatible(lo, hi, shape)})
    ok = [v["volume"] for v in vols if v["compatible"]]
    unknown = [v["volume"] for v in vols if v["compatible"] is None]
    binding = ("ONE COMPATIBLE" if len(ok) == 1 and not unknown else
               "NONE COMPATIBLE" if not ok and not unknown else "AMBIGUOUS")
    return {
        "schema_version": 1,
        "campaign": f"{scroll}-public-vc3d-fiber-census",
        "scroll": scroll,
        "verdict": verdict,
        "listing_error": listing_error,
        "listed": len(names),
        "audited": len(audited),
        "status_counts": dict(sorted(statuses.items())),
        "detector_control": dict(controls),
        "annotator_prefix_counts": dict(sorted(Counter(n.split("_", 1)[0] for n in names).items())),
        "totals": {k: tot(k) for k in ("bytes", "line_points", "control_points", "segments",
                                        "native_trace_segments", "fallback_segments", "gaps",
                                        "sharp_turns", "control_line_offsets", "control_order_inversions")},
        "gaps_in_fibers_without_fallback": sum(int(r.get("gaps") or 0) for r in audited if not r.get("fallback_segments")),
        "manifest_sha256": hashlib.sha256("".join(
            f"{r['file']}\t{r.get('sha256')}\n" for r in sorted(rows, key=lambda r: r["file"])).encode()).hexdigest(),
        "bbox_xyz_min": lo,
        "bbox_xyz_max": hi,
        "volume_range_check": {"verdict": binding, "compatible": ok, "shape_unreadable": unknown,
                               "volumes": vols,
                               "limitation": "Range compatibility rules volumes out; it never establishes a binding."},
        "rows": sorted(rows, key=lambda r: r["file"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scroll", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    result = run(a.scroll, a.workers)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    return 0 if result["verdict"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
