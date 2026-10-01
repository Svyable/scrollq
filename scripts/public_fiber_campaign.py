#!/usr/bin/env python3
"""Run a small, reproducible ScrolIQ Fiber IQ campaign on public scroll data.

The selected files are native VC3D fiber annotations from the published
PHercParis4 spiral-input dataset.  The campaign intentionally stays small
enough for CI while spanning multiple annotator prefixes and dates.

Every input is downloaded from a named public object, SHA-256 hashed, audited
without a CT-volume binding, and reduced to a compact machine-readable summary.
A later step may pin EXPECTED_SHA256 after the first successful public run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from scrollq.fiber_audit import audit_vc3d_json

CAMPAIGN_SCHEMA_VERSION = 1
CAMPAIGN_DATE = "2026-10-01"
SOURCE_TREE = (
    "https://huggingface.co/buckets/scrollprize/datasets/tree/"
    "spiral/PHercParis4/fibers"
)
SOURCE_RESOLVE = (
    "https://huggingface.co/buckets/scrollprize/datasets/resolve/"
    "spiral/PHercParis4/fibers"
)

FILES = (
    "dj_20260717T165249423_000001.json",
    "dj_20260805T025256484_000003.json",
    "et_20260630T175334064_000039.json",
    "et_20260706T162710800_000044.json",
    "kb_20260630T183823858_000130.json",
    "kb_20260729T002251786_000203.json",
    "lt_20260702T055841011_000320.json",
    "lt_20260717T092251928_000547.json",
)

# Pinned from the first successful public run. Subsequent campaigns fail
# closed if a named upstream object changes in place.
EXPECTED_SHA256: dict[str, str] = {
    "dj_20260717T165249423_000001.json": "47fa7a26f1ae487510350301b1f651bbb1211236c104169736b98a5fc0500beb",
    "dj_20260805T025256484_000003.json": "9a53f6f57860ecffdeff1af77a09bc6c444ef7dc6f77c66db4f60fa24ef99ca7",
    "et_20260630T175334064_000039.json": "06dbc8e2ea4ebdf60516a7b14e98b033279123706ae35bf5115a936f9f6589c4",
    "et_20260706T162710800_000044.json": "fa5667d430ba81dc3763849218d557fdd194132742d3abb5784d73ff3811fd54",
    "kb_20260630T183823858_000130.json": "adbb5fb85edcafd2761a40410e20bbf42ccc7dc5be346ccbe25ac6fc9cb9a6c4",
    "kb_20260729T002251786_000203.json": "5fe40a9d014bccc9b81839447d31a72d9a0c5f1707e072e0e6d6fda98367509e",
    "lt_20260702T055841011_000320.json": "38a81931b98de0a49979f1883acb98bfe7a5632b6901a1089f4d0ef4bb1daa21",
    "lt_20260717T092251928_000547.json": "18a93879aff85f55aa96f1312e3a8235c8efd603a36a4de04b9c7ecf0ff45dc1",
}


def _download(name: str) -> bytes:
    request = urllib.request.Request(
        f"{SOURCE_RESOLVE}/{name}?download=true",
        headers={"User-Agent": "scrollq-public-fiber-campaign/1"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _compact(name: str, audit: dict[str, Any]) -> dict[str, Any]:
    findings = list(audit.get("findings") or [])
    kinds = Counter(str(item.get("kind", "unknown")) for item in findings)
    fiber = dict(audit.get("vc3d_fiber") or {})
    control_line = dict(audit.get("control_line") or {})
    counts = dict(audit.get("counts") or {})
    return {
        "file": name,
        "source_url": f"{SOURCE_RESOLVE}/{name}",
        "sha256": (audit.get("input") or {}).get("sha256"),
        "bytes": (audit.get("input") or {}).get("bytes"),
        "status": audit.get("status"),
        "fiber_version": fiber.get("version"),
        "line_points": fiber.get("line_points"),
        "control_points": fiber.get("control_points"),
        "segments": fiber.get("segments"),
        "native_trace_segments": fiber.get("native_trace_segments"),
        "fallback_segments": fiber.get("fallback_segments"),
        "fallback_fraction": fiber.get("fallback_fraction"),
        "gaps": counts.get("gaps"),
        "sharp_turns": counts.get("sharp_turns"),
        "control_line_offsets": counts.get("control_line_offsets"),
        "control_order_inversions": counts.get("control_order_inversions"),
        "finding_kinds": dict(sorted(kinds.items())),
        "control_line": control_line,
        "errors": list(audit.get("errors") or []),
    }


def run_campaign() -> dict[str, Any]:
    if set(EXPECTED_SHA256) != set(FILES):
        missing = sorted(set(FILES) - set(EXPECTED_SHA256))
        extra = sorted(set(EXPECTED_SHA256) - set(FILES))
        raise RuntimeError(
            f"public campaign hash pins do not match FILES (missing={missing}, extra={extra})"
        )

    rows: list[dict[str, Any]] = []
    download_errors = 0
    hash_mismatches = 0

    with tempfile.TemporaryDirectory(prefix="scrollq-public-fibers-") as tmp:
        tmpdir = Path(tmp)
        for name in FILES:
            try:
                payload = _download(name)
            except Exception as exc:
                download_errors += 1
                rows.append({
                    "file": name,
                    "source_url": f"{SOURCE_RESOLVE}/{name}",
                    "status": "download-fail",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            digest = hashlib.sha256(payload).hexdigest()
            expected = EXPECTED_SHA256.get(name)
            if expected is not None and digest != expected:
                hash_mismatches += 1
                rows.append({
                    "file": name,
                    "source_url": f"{SOURCE_RESOLVE}/{name}",
                    "status": "hash-mismatch",
                    "sha256": digest,
                    "expected_sha256": expected,
                    "bytes": len(payload),
                })
                continue

            path = tmpdir / name
            path.write_bytes(payload)
            audit = audit_vc3d_json(path)
            row = _compact(name, audit)
            # Paths under the runner's temporary directory are not provenance.
            # The public object URL plus exact digest are.
            row["input_path"] = name
            rows.append(row)

    statuses = Counter(str(row.get("status", "unknown")) for row in rows)
    kind_totals: Counter[str] = Counter()
    total_bytes = 0
    for row in rows:
        total_bytes += int(row.get("bytes") or 0)
        kind_totals.update(row.get("finding_kinds") or {})

    return {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign": "PHercParis4-public-vc3d-fiber-audit",
        "campaign_date": CAMPAIGN_DATE,
        "source": {
            "dataset": "scrollprize/datasets spiral-input PHercParis4/fibers",
            "tree_url": SOURCE_TREE,
            "selection": (
                "Eight named public VC3D JSON fibers spanning dj/et/kb/lt "
                "annotator prefixes and June-August 2026 timestamps."
            ),
            "volume_binding": (
                "none: this campaign validates public fiber artifacts but does "
                "not infer an exact CT volume root from the dataset name"
            ),
        },
        "parameters": {
            "gap_factor": 4.0,
            "turn_degrees": 60.0,
            "control_line_factor": 4.0,
        },
        "input_count": len(FILES),
        "download_errors": download_errors,
        "hash_mismatches": hash_mismatches,
        "total_input_bytes": total_bytes,
        "status_counts": dict(sorted(statuses.items())),
        "finding_kind_totals": dict(sorted(kind_totals.items())),
        "rows": rows,
        "limitations": [
            "This is a deterministic public subset, not an exhaustive audit of every PHercParis4 fiber.",
            "No exact CT volume binding is asserted, so these reports are not passport evidence.",
            "Geometry findings are review candidates; they do not prove a sheet switch or wrong physical fiber.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    summary = run_campaign()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, separators=(",", ":")))

    failed = (
        summary["download_errors"]
        or summary["hash_mismatches"]
        or summary["status_counts"].get("fail", 0)
        or summary["status_counts"].get("download-fail", 0)
        or summary["status_counts"].get("hash-mismatch", 0)
    )
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
