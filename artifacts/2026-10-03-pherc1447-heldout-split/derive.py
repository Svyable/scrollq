#!/usr/bin/env python3
"""Regenerate the frozen PHerc1447 geometry-only held-out split."""
from __future__ import annotations
import hashlib, json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SUMMARY = ROOT / "artifacts/2026-10-01-corpus-mesh-audit/summary.json"
SUMMARY_SHA = "194561344ba1d998a3ae0fba9f16e2b3185bce54"
REPORT_SHAS = {
  "reports/PHerc1447.20250703025628-auto_grown_20250703025628283.20250703025628-on-20250521151220-8.64um.json": "2d74fc9e10c87e8215168a745f678c6c4e79ee48",
  "reports/PHerc1447.20250703034159-auto_grown_20250703034159599.20250703034159-on-20250521151220-8.64um.json": "41497145f86d293738fb9aeabf6a3de108055f67",
  "reports/PHerc1447.20251105093211-z_dbg_gen_00320.20251105093211-on-20250521151220-8.64um.json": "c842ee93b9e843534211df8612d44a56c135e9e4",
  "reports/PHerc1447.20250702235910-auto_grown_20250702235910292.20250702235910-on-20250521151220-8.64um.json": "b295d55969c62309c0f0e4b69dad86c9588eca4a",
  "reports/PHerc1447.20250502205333-auto_grown_20250502181030065.20250502205333-on-20250521151220-8.64um.json": "2dc18ea2b8ce8ca7828e81d6933041b70a35d9fe",
  "reports/PHerc1447.20250502182142-auto_grown_20250502161324419.20250502182142-on-20250521151220-8.64um.json": "9716653b956e2b60b31a6b3f14d8c854eac34097",
  "reports/PHerc1447.20250502183138-auto_grown_20250502162038685.20250502183138-on-20250521151220-8.64um.json": "b873bd3d8e300cc61b8b4c37a82e3ba2638f660e",
  "reports/PHerc1447.20250502182456-auto_grown_20250502161202782.20250502182456-on-20250521151220-8.64um.json": "3d6021c132cf70cffe539c83b8eeba030700e6b1",
  "reports/PHerc1447.20250502183421-auto_grown_20250502161744358.20250502183421-on-20250521151220-8.64um.json": "c84dc97544027cc61f474c6965ea53c05441b71a",
  "reports/PHerc1447.20250502180748-auto_grown_20250502160748721.20250502180748-on-20250521151220-8.64um.json": "f80a199e4d40895789ef55b572528f451d1ff832",
  "reports/PHerc1447.20250502184845-auto_grown_20250502164121265.20250502184845-on-20250521151220-8.64um.json": "43aed135d4b8f10028132d9d20c0290770fb0c8e",
  "reports/PHerc1447.20250502184658-auto_grown_20250502163923577.20250502184658-on-20250521151220-8.64um.json": "2e78d98f0263d466f7bf04752b4333797a2e4e83",
  "reports/PHerc1447.20250502185519-auto_grown_20250502164303733.20250502185519-on-20250521151220-8.64um.json": "a465bac33ce7ee4621ccd118fc4db50541d47db8",
  "reports/PHerc1447.20250502184201-auto_grown_20250502163549332.20250502184201-on-20250521151220-8.64um.json": "444fcd02b1298fd825ea04b32552dc3bb5d9b04f",
  "reports/PHerc1447.20250502180708-auto_grown_20250502160708188.20250502180708-on-20250521151220-8.64um.json": "cd492a252c2a0dfbf41502ce342649bc81502a8a"
}
CORE_DEPTH = 256
ISOLATION = 128

def blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + bytes([0]) + raw).hexdigest()

def read_pinned(path: Path, expected: str):
    raw = path.read_bytes()
    actual = blob_sha(raw)
    if actual != expected:
        raise RuntimeError(f"source drift {path.relative_to(ROOT)}: {actual} != {expected}")
    return json.loads(raw)

def gap(a, b):
    aa, bb = a["core_z_half_open"], b["core_z_half_open"]
    if aa[1] <= bb[0]: return bb[0] - aa[1]
    if bb[1] <= aa[0]: return aa[0] - bb[1]
    return 0

def main() -> int:
    summary = read_pinned(SUMMARY, SUMMARY_SHA)
    rows = [r for r in summary["rows"] if r.get("scroll") == "PHerc1447" and r.get("volume_id") == "20250521151220"]
    if len(rows) != 15: raise RuntimeError(f"expected 15 rows, got {len(rows)}")
    items = []
    for row in rows:
        rel = row["report"]
        expected = REPORT_SHAS.get(rel)
        if not expected: raise RuntimeError(f"un-pinned report {rel}")
        report = read_pinned(ROOT / "artifacts/2026-10-01-corpus-mesh-audit" / rel, expected)
        bbox = report["bbox"]["observed_bbox_xyz"]
        z = (float(bbox[0][2]) + float(bbox[1][2])) / 2.0
        center = math.floor(z + 0.5)
        items.append({"segment":row["segment"],"z_center":z,"core_z_half_open":[center-128,center+128],"report":rel,"report_git_blob_sha1":expected})
    items.sort(key=lambda r:(r["z_center"],r["segment"]))
    for item in items:
        item["minimum_axial_gap_to_any_other_core_slices"] = min(gap(item, other) for other in items if other is not item)
    isolated = [r for r in items if r["minimum_axial_gap_to_any_other_core_slices"] >= ISOLATION]
    ranks = [min(len(isolated)-1, math.floor((i+0.5)*len(isolated)/3)) for i in range(3)]
    if len(set(ranks)) != 3: raise RuntimeError(f"non-unique ranks {ranks}")
    held_ids = {isolated[i]["segment"] for i in ranks}
    for item in items: item["role"] = "held_out" if item["segment"] in held_ids else "fit"
    held=[r for r in items if r["role"]=="held_out"]; fit=[r for r in items if r["role"]=="fit"]
    minimum_gap=min(gap(h,f) for h in held for f in fit)
    if minimum_gap < ISOLATION: raise RuntimeError(f"minimum held-out/fit gap {minimum_gap}")
    result = {
      "schema_version":1,"diagnostic":"PHerc1447-geometry-only-heldout-split","as_of":"2026-10-03",
      "scroll":"PHerc1447","volume_id":"20250521151220",
      "volume_root":"community-uploads/forrest/volcomp/PHerc1447/volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr",
      "sources":{"corpus_summary":{"path":"artifacts/2026-10-01-corpus-mesh-audit/summary.json","git_blob_sha1":SUMMARY_SHA},
                 "reports":[{"segment":r["segment"],"path":"artifacts/2026-10-01-corpus-mesh-audit/"+r["report"],"git_blob_sha1":r["report_git_blob_sha1"]} for r in items]},
      "method":{"input_rule":"Use all 15 exact-volume PHerc1447 segment reports from the frozen corpus mesh census. Selection reads only observed XYZ bounding boxes and segment identity; it does not read findings, tiers, scan score, render appearance, or ink.",
                "core_depth_slices":CORE_DEPTH,"core_center_rule":"z_center = midpoint of observed bbox z bounds; integer center = floor(z_center + 0.5); core = [center-128, center+128).",
                "isolation_threshold_slices":ISOLATION,"isolated_rule":"A candidate is isolated when its 256-slice core has at least 128 slices of axial gap from every other candidate core.",
                "heldout_rule":"Sort isolated candidates by z_center and select three even-quantile ranks floor((i+0.5)*N/3) for i=0,1,2. All other candidates are fit-role candidates.",
                "selected_isolated_ranks":ranks,"uses_findings":False,"uses_quality_or_ink":False},
      "counts":{"candidates":len(items),"isolated_candidates":len(isolated),"fit_candidates":len(fit),"held_out_candidates":len(held)},
      "minimum_heldout_fit_axial_gap_slices":minimum_gap,
      "isolated_candidates":[r["segment"] for r in isolated],"held_out_segments":[r["segment"] for r in held],"candidates":items,
      "invariants":["Every one of the 15 exact-volume segment reports is retained in the denominator.","No Mesh IQ finding or tier is read by the selection algorithm.","No scan-quality score, render appearance, or ink output is read by the selection algorithm.","Held-out 256-slice cores are axially disjoint from every fit core by at least 128 slices."],
      "claim_boundary":"This freezes a geometry-only fit/held-out path. It does not show that the fit succeeds, that any mesh is the correct papyrus sheet, or that the measured gap exceeds the influence radius of a future fitting method. The fit method must declare an influence radius no larger than that gap or use a stricter split."
    }
    (HERE/"split.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return 0
if __name__ == "__main__": raise SystemExit(main())
