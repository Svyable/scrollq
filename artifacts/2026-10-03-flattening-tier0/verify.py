"""Fetch and verify the non-promoting flattening Tier-0 OBJ corpus.

Only the manifest and this verifier are stored in ScrollQ. Source mesh bytes are
downloaded from the public Vesuvius Challenge bucket and remain under
CC-BY-NC-4.0. The corpus is deliberately non-promoting: it can expose solver
bugs but cannot qualify a flattening backend for the Grand Prize path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from pathlib import Path
from typing import Any

from scrollq.obj_audit import audit_obj

HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    if value.get("diagnostic") != "flattening-tier0-fixtures":
        raise ValueError("unexpected manifest diagnostic")
    if value.get("promotion_eligible") is not False:
        raise ValueError("Tier-0 manifest must remain explicitly non-promoting")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest cases must be a non-empty list")
    return value


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                out.write(block)
        partial.replace(path)
    finally:
        if partial.exists():
            partial.unlink()


def verify_case(
    manifest: dict[str, Any],
    case: dict[str, Any],
    out_dir: Path,
    *,
    allow_download: bool,
) -> dict[str, Any]:
    bucket = str(manifest["source_bucket"]).rstrip("/")
    source_key = case["source_key"]
    url = f"{bucket}/{source_key}"
    target = out_dir / f"{case['id']}.obj"

    if not target.exists():
        if not allow_download:
            raise FileNotFoundError(f"{target} is missing and downloads are disabled")
        download(url, target)

    observed_bytes = target.stat().st_size
    observed_sha = sha256_file(target)
    byte_match = observed_bytes == int(case["bytes"])
    hash_match = observed_sha == case["sha256"]

    if not byte_match or not hash_match:
        raise ValueError(
            f"{case['id']}: source-byte mismatch "
            f"(bytes {observed_bytes}/{case['bytes']}, sha256 {observed_sha}/{case['sha256']})"
        )

    audit = audit_obj(target)
    expected = case["expected_audit"]
    observed = {
        "triangles": int(audit["mesh"]["triangles"]),
        "components": int(audit["topology"]["components"]),
        "boundary_loops": int(audit["topology"]["boundary_loops"]),
        "holes": int(audit["topology"]["holes"]),
        "uv_flips": int(audit["isometry"]["flipped_uv_triangles"]),
        "p95_symmetric_stretch": float(
            audit["isometry"]["symmetric_stretch_distortion"]["p95"]
        ),
    }

    exact_fields = ("triangles", "components", "boundary_loops", "holes", "uv_flips")
    mismatches = [
        name for name in exact_fields
        if observed[name] != int(expected[name])
    ]
    if not math.isclose(
        observed["p95_symmetric_stretch"],
        float(expected["p95_symmetric_stretch"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        mismatches.append("p95_symmetric_stretch")

    if mismatches:
        raise ValueError(
            f"{case['id']}: audit regression for {', '.join(mismatches)}; "
            f"observed={observed} expected={expected}"
        )

    return {
        "id": case["id"],
        "role": case["role"],
        "promotion_eligible": False,
        "source_url": url,
        "source_key": source_key,
        "path": str(target),
        "bytes": observed_bytes,
        "sha256": observed_sha,
        "audit": observed,
        "source_audit": case["source_audit"],
        "status": "pass",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out-dir", type=Path, default=Path("out/flattening-tier0"))
    ap.add_argument(
        "--case",
        action="append",
        default=[],
        help="case id to verify; repeat to select multiple (default: all)",
    )
    ap.add_argument(
        "--no-download",
        action="store_true",
        help="verify only already-downloaded OBJ files",
    )
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    cases = manifest["cases"]
    wanted = set(args.case)
    if wanted:
        known = {case["id"] for case in cases}
        missing = sorted(wanted - known)
        if missing:
            raise SystemExit(f"unknown case id(s): {', '.join(missing)}")
        cases = [case for case in cases if case["id"] in wanted]

    results = [
        verify_case(
            manifest,
            case,
            args.out_dir,
            allow_download=not args.no_download,
        )
        for case in cases
    ]

    report = {
        "schema_version": 1,
        "diagnostic": "flattening-tier0-verification",
        "promotion_eligible": False,
        "manifest_sha256": sha256_file(args.manifest),
        "dataset_license": manifest["dataset_license"],
        "selection_freeze": manifest["selection_freeze"],
        "cases": results,
        "status": "pass",
        "claim_boundary": (
            "PASS proves exact public source bytes reproduce the pre-existing local OBJ "
            "audit facts for the selected Tier-0 fixtures. It does not establish correct "
            "papyrus sheet identity, column-sized suitability, or production flattening "
            "promotion. Issue #114 Tier-1 evidence remains mandatory."
        ),
    }

    report_path = args.report or (args.out_dir / "verification.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"PASS flattening Tier-0: {len(results)} case(s), "
        f"manifest sha256={report['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
