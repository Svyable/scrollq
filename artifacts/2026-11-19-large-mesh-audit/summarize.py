"""Summarize the 2026-11-19 large-mesh audit into summary.json and flagged.tsv.

Tiers count distinct finding kinds, as in 2026-10-01-corpus-mesh-audit:
clean (none), review (1-2), multi-defect (3+). The status is `complete` only
when every listed mesh has a report, the equivalence check found the row-block
code identical to the unblocked baseline on every sampled mesh, and nothing is
unaccounted for; `partial` when the rest are logged failures; otherwise
`unverified`.
"""
import csv
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OCT = os.path.join(HERE, "..", "2026-10-01-corpus-mesh-audit")


def tier(kinds):
    return "clean" if not kinds else "review" if len(kinds) < 3 else "multi-defect"


def report_path(mesh):
    p = mesh.split("/")
    return os.path.join(HERE, "reports", f"{p[0]}.{p[2]}.{os.path.basename(mesh)[:-7]}.json")


listed = [l.strip().rstrip("/") for l in open(os.path.join(HERE, "meshes.txt")) if l.strip()]
failed = {}
for line in open(os.path.join(HERE, "failed.tsv")):
    if line.strip():
        mesh, reason = line.rstrip("\n").split("\t", 1)
        if not os.path.exists(report_path(mesh.rstrip("/"))):
            failed[mesh.rstrip("/")] = reason
runs = {}
for line in open(os.path.join(HERE, "runs.tsv")):
    if line.strip():
        mesh, code, rss, secs = line.rstrip("\n").split("\t")
        runs[mesh.rstrip("/")] = {"exit": int(code), "peak_rss_mb": int(rss), "seconds": int(secs)}

rows = []
for mesh in listed:
    path = report_path(mesh)
    if not os.path.exists(path):
        continue
    r = json.load(open(path))
    g, q, e = r["grid"], r["quads"], r["edges"]
    m = re.search(r"-on-(\d+)(?:-([\d.]+um))?", mesh)
    kinds = sorted({f["kind"] for f in r["findings"]})
    iso = q["isometry"]["symmetric_stretch_distortion"]
    rows.append({
        "scroll": mesh.split("/")[0],
        "segment": mesh.split("/")[2],
        "volume_id": m.group(1) if m else None,
        "voxel": m.group(2) if m else None,
        "volume_root": r["volume_root"],
        "vertices": g["vertices"],
        "status": r["status"],
        "tier": tier(kinds),
        "valid_vertex_fraction": round(g["valid_vertex_fraction"], 3),
        "components": g["valid_vertex_components"]["components"],
        "enclosed_invalid_components": g["enclosed_invalid_components"],
        "jump_edges": e["columns"]["jump_edges"] + e["rows"]["jump_edges"],
        "normal_reversal_pairs": q["normal_reversal_pairs"],
        "isometry_stretch_p95": round(iso["p95"], 3) if iso["p95"] is not None else None,
        "findings": kinds,
        "run": runs.get(mesh),
        "report": f"reports/{os.path.basename(path)}",
    })

audited = {f"{x['scroll']}/segments/{x['segment']}" for x in rows}
missing = [m for m in listed if m not in failed and not os.path.exists(report_path(m))]
eq = json.load(open(os.path.join(HERE, "equivalence.json")))
equivalent = eq["meshes"] > 0 and eq["identical"] == eq["meshes"]

# Segment-level view across both artifacts: a segment is flagged when every
# audited registration (2026-10-01 or here) is multi-defect.
oct_rows = json.load(open(os.path.join(OCT, "summary.json")))["rows"]
by_seg = {}
for x in oct_rows + rows:
    by_seg.setdefault((x["scroll"], x["segment"]), []).append(x["tier"])
flagged_all = sorted(k for k, v in by_seg.items() if all(t == "multi-defect" for t in v))
newly_seen = sorted({(x["scroll"], x["segment"]) for x in rows}
                    - {(x["scroll"], x["segment"]) for x in oct_rows})

summary = {
    "diagnostic": "row-block scroliq-mesh on the 60 meshes 2026-10-01-corpus-mesh-audit could not audit",
    "source_bucket": "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com",
    "as_of": "2026-11-19",
    "status": ("unverified" if missing or not equivalent or not rows
               else "complete" if not failed else "partial"),
    "listed_meshes": len(listed),
    "audited_meshes": len(rows),
    "failed_meshes": len(failed),
    "unaccounted_meshes": missing,
    "equivalence": {k: eq[k] for k in ("baseline_ref", "meshes", "identical", "same_kinds_as_2026_10_01")},
    "peak_rss_mb_max": max((x["run"]["peak_rss_mb"] for x in rows if x["run"]), default=None),
    "vertices_max": max((x["vertices"] for x in rows), default=None),
    "tier_counts": {t: sum(1 for x in rows if x["tier"] == t) for t in ("clean", "review", "multi-defect")},
    "finding_counts": {k: sum(1 for x in rows if k in x["findings"])
                       for k in sorted({k for x in rows for k in x["findings"]})},
    "corpus": {
        "tifxyz_meshes_listed_2026_10_01": 903,
        "tifxyz_meshes_audited": len(oct_rows) + len(rows),
        "segments": len(by_seg),
        "segments_first_audited_here": len(newly_seen),
        "segments_multi_defect_on_every_registration": len(flagged_all),
        "flagged_by_scroll": {s: sum(1 for k in flagged_all if k[0] == s)
                              for s in sorted({k[0] for k in flagged_all})},
    },
    "failed": failed,
    "rows": rows,
}
with open(os.path.join(HERE, "summary.json"), "w") as fh:
    json.dump(summary, fh, indent=1)
    fh.write("\n")

with open(os.path.join(HERE, "flagged.tsv"), "w", newline="") as fh:
    w = csv.writer(fh, delimiter="\t")
    w.writerow(["scroll", "segment", "volume_id", "voxel", "components", "holes",
                "jump_edges", "normal_reversals", "isometry_p95", "findings"])
    for x in rows:
        if x["tier"] == "multi-defect":
            w.writerow([x["scroll"], x["segment"], x["volume_id"], x["voxel"], x["components"],
                        x["enclosed_invalid_components"], x["jump_edges"],
                        x["normal_reversal_pairs"], x["isometry_stretch_p95"],
                        ",".join(x["findings"])])
print(json.dumps({k: v for k, v in summary.items() if k not in ("rows", "failed")}, indent=1))
