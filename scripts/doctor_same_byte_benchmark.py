#!/usr/bin/env python3
"""Run ScrolIQ Mesh IQ on TIFXYZ Doctor's pinned real-data benchmark bytes.

This is an interoperability/cross-validation benchmark, not a geometry-quality
leaderboard. TIFXYZ Doctor's roles are provenance labels, not ground truth.
Only directly comparable topology facts are scored for concordance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from scrollq.tifxyz_audit import audit_tifxyz

DOCTOR_COMMIT = "5ca0444fb31863c8e02466316bf9e560cf567876"
DOCTOR_ROOT = (
    "https://raw.githubusercontent.com/aviad12g/tifxyz-doctor/"
    + DOCTOR_COMMIT
    + "/benchmarks/"
)
MANIFEST_URL = DOCTOR_ROOT + "realdata-smoke.json"
RESULTS_URL = DOCTOR_ROOT + "realdata-results-v0.1.0.json"
USER_AGENT = "ScrolIQ-same-byte-benchmark/1 (+https://github.com/Svyable/scrollq)"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch(url: str, *, attempts: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except Exception as exc:  # network evidence; preserve final cause
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise RuntimeError(f"could not fetch {url}: {last}") from last


def _fetch_json(url: str) -> tuple[dict[str, Any], str]:
    raw = _fetch(url)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} did not contain a JSON object")
    return value, _sha256_bytes(raw)


def _download_case(case: dict[str, Any], root: Path) -> tuple[Path, int]:
    case_dir = root / str(case["id"])
    case_dir.mkdir(parents=True, exist_ok=False)
    base_url = str(case["base_url"])
    if not base_url.endswith("/"):
        base_url += "/"

    total = 0
    files = case.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError(f"{case['id']}: manifest has no files")

    for name, expected in files.items():
        if not isinstance(expected, dict):
            raise RuntimeError(f"{case['id']}/{name}: invalid file manifest")
        raw = _fetch(base_url + name)
        total += len(raw)
        expected_bytes = int(expected["bytes"])
        expected_sha = str(expected["sha256"])
        if len(raw) != expected_bytes:
            raise RuntimeError(
                f"{case['id']}/{name}: byte count {len(raw)} != {expected_bytes}"
            )
        actual_sha = _sha256_bytes(raw)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"{case['id']}/{name}: sha256 {actual_sha} != {expected_sha}"
            )
        (case_dir / name).write_bytes(raw)

    return case_dir, total


def _doctor_map(results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observations = results.get("observations")
    if not isinstance(observations, list):
        raise RuntimeError("TIFXYZ Doctor results have no observations list")
    mapped: dict[str, dict[str, Any]] = {}
    for row in observations:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise RuntimeError("TIFXYZ Doctor observation is malformed")
        if row["id"] in mapped:
            raise RuntimeError(f"duplicate Doctor observation id: {row['id']}")
        mapped[row["id"]] = row
    return mapped


def _row(
    case: dict[str, Any],
    doctor: dict[str, Any],
    mesh: dict[str, Any],
    downloaded_bytes: int,
) -> dict[str, Any]:
    facts = doctor.get("facts") if isinstance(doctor.get("facts"), dict) else {}
    doctor_holes = int(facts.get("enclosed_face_holes", 0))
    doctor_components = int(facts.get("valid_face_components", 0))

    grid = mesh.get("grid") if isinstance(mesh.get("grid"), dict) else {}
    mesh_holes = int(grid.get("enclosed_invalid_components", 0))
    vc = (
        grid.get("valid_vertex_components")
        if isinstance(grid.get("valid_vertex_components"), dict)
        else {}
    )
    mesh_components = int(vc.get("components", 0))

    findings = [
        str(item.get("kind"))
        for item in mesh.get("findings", [])
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    ]

    return {
        "id": case["id"],
        "scroll_id": case.get("scroll_id"),
        "segment_id": case.get("segment_id"),
        "artifact_variant": case.get("artifact_variant"),
        "role": case.get("role"),
        "downloaded_bytes": downloaded_bytes,
        "mesh_iq": {
            "status": mesh.get("status"),
            "valid_vertices": grid.get("valid_vertices"),
            "valid_vertex_components": mesh_components,
            "enclosed_invalid_components": mesh_holes,
            "finding_kinds": findings,
        },
        "tifxyz_doctor": {
            "contract_status": doctor.get("contract_status"),
            "review_cues": doctor.get("review_cues", []),
            "valid_face_components": doctor_components,
            "enclosed_face_holes": doctor_holes,
        },
        "shared_topology": {
            "hole_presence_match": (mesh_holes > 0) == (doctor_holes > 0),
            "hole_count_match": mesh_holes == doctor_holes,
            "single_component_presence_match": (mesh_components == 1)
            == (doctor_components == 1),
        },
    }


def run() -> dict[str, Any]:
    manifest, manifest_sha = _fetch_json(MANIFEST_URL)
    doctor_results, results_sha = _fetch_json(RESULTS_URL)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("TIFXYZ Doctor manifest has no cases")

    doctor_by_id = _doctor_map(doctor_results)
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids):
        raise RuntimeError("benchmark case ids are missing or duplicated")
    missing = sorted(set(case_ids) - set(doctor_by_id))
    extra = sorted(set(doctor_by_id) - set(case_ids))
    if missing or extra:
        raise RuntimeError(
            f"manifest/results id mismatch: missing={missing}, extra={extra}"
        )

    rows: list[dict[str, Any]] = []
    bytes_total = 0
    with tempfile.TemporaryDirectory(prefix="scroliq-doctor-") as tmp:
        inputs = Path(tmp) / "inputs"
        inputs.mkdir()
        for case in cases:
            case_dir, downloaded = _download_case(case, inputs)
            bytes_total += downloaded
            mesh = audit_tifxyz(case_dir)
            if mesh.get("status") == "fail":
                raise RuntimeError(
                    f"{case['id']}: Mesh IQ could not audit pinned input: "
                    + "; ".join(mesh.get("errors", []))
                )
            rows.append(_row(case, doctor_by_id[case["id"]], mesh, downloaded))
            shutil.rmtree(case_dir)

    n = len(rows)
    hole_presence = sum(r["shared_topology"]["hole_presence_match"] for r in rows)
    hole_count = sum(r["shared_topology"]["hole_count_match"] for r in rows)
    component_presence = sum(
        r["shared_topology"]["single_component_presence_match"] for r in rows
    )
    positive = sum(r["tifxyz_doctor"]["enclosed_face_holes"] > 0 for r in rows)
    null = n - positive
    gp_rows = [r for r in rows if r["scroll_id"] in {"PHerc0800", "PHerc1447"}]

    # Positive + null controls are required so a vacuous always-clean comparison
    # cannot pass. The benchmark is not a quality-label benchmark.
    if not positive or not null:
        raise RuntimeError(
            f"benchmark lacks required positive/null topology controls: "
            f"positive={positive}, null={null}"
        )

    return {
        "schema_version": 1,
        "diagnostic": "same-byte-tifxyz-cross-validation",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scrollq_git_sha": os.environ.get("GITHUB_SHA"),
        "comparison": {
            "tool": "tifxyz-doctor",
            "repository": "https://github.com/aviad12g/tifxyz-doctor",
            "commit": DOCTOR_COMMIT,
            "manifest_url": MANIFEST_URL,
            "manifest_sha256": manifest_sha,
            "results_url": RESULTS_URL,
            "results_sha256": results_sha,
        },
        "input_contract": {
            "cases": n,
            "downloaded_bytes": bytes_total,
            "every_file_verified_against_doctor_manifest_sha256": True,
            "positive_hole_cases": positive,
            "null_hole_cases": null,
            "roles_are_ground_truth": False,
        },
        "shared_topology_summary": {
            "hole_presence_matches": hole_presence,
            "hole_presence_cases": n,
            "exact_hole_count_matches": hole_count,
            "exact_hole_count_cases": n,
            "single_component_presence_matches": component_presence,
            "single_component_presence_cases": n,
            "grand_prize_overlap_cases": len(gp_rows),
            "grand_prize_hole_presence_matches": sum(
                r["shared_topology"]["hole_presence_match"] for r in gp_rows
            ),
            "grand_prize_exact_hole_count_matches": sum(
                r["shared_topology"]["hole_count_match"] for r in gp_rows
            ),
        },
        "rows": rows,
        "interpretation": (
            "The two tools are run/read on the same SHA-256-pinned TIFXYZ bytes. "
            "Concordance is reported only for directly comparable local topology facts. "
            "TIFXYZ Doctor benchmark roles are provenance labels, not geometry ground truth; "
            "agreement does not establish sheet identity or correctness."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Run Mesh IQ on the exact TIFXYZ Doctor real-data benchmark bytes and "
            "report shared-topology concordance."
        )
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    s = result["shared_topology_summary"]
    print(
        "same-byte cross-validation: "
        f"holes {s['hole_presence_matches']}/{s['hole_presence_cases']} presence, "
        f"{s['exact_hole_count_matches']}/{s['exact_hole_count_cases']} exact counts; "
        f"components {s['single_component_presence_matches']}/"
        f"{s['single_component_presence_cases']}"
    )


if __name__ == "__main__":
    main()
