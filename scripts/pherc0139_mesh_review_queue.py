#!/usr/bin/env python3
"""Generate a pinned real-data VC3D review queue for one public PHerc0139 mesh."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import urllib.request
from pathlib import Path

from scrollq.tifxyz_audit import audit_tifxyz, review_queue_pointcollections

BASE = (
    "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/"
    "PHerc0139/segments/20260306000001-w051_2026030600/mesh/"
    "20260306000001-on-20250728140407-9.362um.tifxyz"
)
VOLUME_ROOT = (
    "community-uploads/forrest/volcomp/PHerc0139/volumes/"
    "20250728140407-9.362um-1.2m-113keV-masked.zarr"
)
FILES = {
    "meta.json": {
        "bytes": 419,
        "sha256": "c0f12d62261968b901df9aa672a65f70133ccf1339dda9ad0cb0cc3b3a158163",
    },
    "x.tif": {
        "bytes": 727814,
        "sha256": "dff240d4c984da3223020562a83ee96d34da9f02787b3b2409adc0b3a5d12215",
    },
    "y.tif": {
        "bytes": 727814,
        "sha256": "a73d4c247505e123a9dfe923c6f7fe53ee9ca7ab9ce7bddecb5405f1014c5c6c",
    },
    "z.tif": {
        "bytes": 727814,
        "sha256": "233bc07b57ed6447e19482785905ebdf41031bf979ca859390de79a2f569237e",
    },
}
USER_AGENT = "ScrolIQ-public-review-queue/1 (+https://github.com/Svyable/scrollq)"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url: str, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise RuntimeError(f"could not fetch {url}: {last}") from last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="scroliq-pherc0139-") as tmp:
        surface = Path(tmp) / "surface.tifxyz"
        surface.mkdir()
        for name, expected in FILES.items():
            raw = fetch(f"{BASE}/{name}")
            if len(raw) != expected["bytes"]:
                raise RuntimeError(
                    f"{name}: bytes {len(raw)} != expected {expected['bytes']}"
                )
            actual = sha256_bytes(raw)
            if actual != expected["sha256"]:
                raise RuntimeError(
                    f"{name}: sha256 {actual} != expected {expected['sha256']}"
                )
            (surface / name).write_bytes(raw)

        report = audit_tifxyz(
            surface,
            volume_root=VOLUME_ROOT,
            review_limit_per_kind=20,
        )
        # The audit ran on a random temp copy; record the pinned public source
        # instead, so the outputs (and their hashes) are reproducible.
        report["tifxyz_path"] = BASE
        queue = report["review_queue"]
        totals = queue["total_candidates_by_kind"]
        if totals != {"edge-jump": 15, "normal-reversal": 173}:
            raise RuntimeError(f"review candidate counts drifted: {totals}")

        points = review_queue_pointcollections(report)
        audit_path = out / "mesh-audit.json"
        points_path = out / "review-points.json"
        audit_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        points_path.write_text(json.dumps(points, indent=2) + "\n", encoding="utf-8")

    collections = points["collections"]
    point_count = sum(len(row["points"]) for row in collections.values())
    summary = {
        "schema_version": 1,
        "campaign": "PHerc0139-mesh-iq-vc3d-review-queue",
        "surface": {
            "scroll": "PHerc0139",
            "segment": "20260306000001-w051_2026030600",
            "volume_id": "20250728140407",
            "volume_root": VOLUME_ROOT,
            "source_url": BASE,
            "files": FILES,
        },
        "audit": {
            "status": report["status"],
            "finding_kinds": [item["kind"] for item in report["findings"]],
            "total_candidates_by_kind": queue["total_candidates_by_kind"],
            "emitted_by_kind": queue["emitted_by_kind"],
            "review_limit_per_kind": queue["limit_per_kind"],
        },
        "vc3d": {
            "schema": points["vc_pointcollections_json_version"],
            "collections": len(collections),
            "points": point_count,
            "review_points_sha256": sha256_file(points_path),
        },
        "claim_boundary": [
            "Review points localize local geometry cues; they are not defect verdicts.",
            "The queue does not establish physical sheet identity or freedom from nonlocal self-intersections.",
            "Use the independently bound Windcheck dossier and official VC3D self-cross validation for nonlocal topology evidence.",
        ],
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "VC3D review queue: "
        f"{totals['edge-jump']} edge jumps, "
        f"{totals['normal-reversal']} normal reversals; "
        f"{point_count} ranked points emitted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
