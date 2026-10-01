"""Summarize the corpus-wide scroliq-mesh and scroliq-obj reports into summary.json and flagged.tsv.

Tiers are counts of distinct finding kinds, not a quality score:
  clean         no findings
  review        1-2 finding kinds
  multi-defect  3 or more finding kinds
The audit is reported `unverified` unless every listed mesh has a report or a
logged failure, and the positive control (PHerc1447 z_dbg_gen_00320, flagged
by hand in 2026-10-01-real-mesh-audit) lands in multi-defect.
"""
import csv
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL = "20251105093211-z_dbg_gen_00320"


def tier(kinds):
    return "clean" if not kinds else "review" if len(kinds) < 3 else "multi-defect"


listed = [l.strip().rstrip("/") for l in open(os.path.join(HERE, "mesh_dirs.txt")) if l.strip()]
failed = {}
for line in open(os.path.join(HERE, "failed.tsv")):
    if line.strip():
        mesh, reason = line.rstrip("\n").split("\t", 1)
        mesh = mesh.rstrip("/")
        scroll, _, segment = mesh.split("/")[:3]
        report = os.path.join(HERE, "reports",
                              f"{scroll}.{segment}.{os.path.basename(mesh)[:-7]}.json")
        # scroliq-mesh exits 2 after writing a `fail` report; that is a result.
        if not os.path.exists(report):
            failed[mesh] = reason

rows = []
for path in sorted(glob.glob(os.path.join(HERE, "reports", "*.json"))):
    r = json.load(open(path))
    g, q, e = r["grid"], r["quads"], r["edges"]
    iso = q["isometry"]["symmetric_stretch_distortion"]
    scroll, segment, mesh = os.path.basename(path)[:-5].split(".", 2)
    m = re.search(r"-on-(\d+)(?:-([\d.]+um))?", mesh)
    kinds = sorted({f["kind"] for f in r["findings"]})
    rows.append({
        "scroll": scroll,
        "segment": segment,
        "volume_id": m.group(1) if m else None,
        "voxel": m.group(2) if m else None,
        "volume_root": r["volume_root"],
        "status": r["status"],
        "tier": tier(kinds),
        "valid_vertex_fraction": round(g["valid_vertex_fraction"], 3),
        "components": g["valid_vertex_components"]["components"],
        "enclosed_invalid_components": g["enclosed_invalid_components"],
        "jump_edges": e["columns"]["jump_edges"] + e["rows"]["jump_edges"],
        "normal_reversal_pairs": q["normal_reversal_pairs"],
        "isometry_stretch_p95": round(iso["p95"], 3) if iso["p95"] is not None else None,
        "findings": kinds,
        "report": f"reports/{os.path.basename(path)}",
    })

audited = {f"{x['scroll']}/segments/{x['segment']}/mesh/" for x in rows}
missing = [m for m in listed
           if m not in failed
           and not os.path.exists(os.path.join(
               HERE, "reports",
               f"{m.split('/')[0]}.{m.split('/')[2]}.{os.path.basename(m)[:-7]}.json"))]

# A segment registered on several volumes: does the geometry verdict agree?
by_seg = {}
for x in rows:
    by_seg.setdefault((x["scroll"], x["segment"]), []).append(x)
multi = {k: v for k, v in by_seg.items() if len(v) > 1}
agree = sum(1 for v in multi.values() if len({tuple(x["findings"]) for x in v}) == 1)

control = [x for x in rows if x["segment"] == CONTROL]
control_ok = bool(control) and all(x["tier"] == "multi-defect" for x in control)
complete = bool(rows) and not missing
by_scroll = {}
for x in rows:
    s = by_scroll.setdefault(x["scroll"], {"meshes": 0, "segments": set(),
                                           "clean": 0, "review": 0, "multi-defect": 0})
    s["meshes"] += 1
    s["segments"].add(x["segment"])
    s[x["tier"]] += 1
for s in by_scroll.values():
    s["segments"] = len(s["segments"])

# Same audit on the published *_original.obj triangle meshes (scroliq-obj).
SHARED = {"connectivity", "hole", "edge-jump", "normal-reversal", "isometry-distortion"}
obj_listed = [l.strip() for l in open(os.path.join(HERE, "obj_keys.txt")) if l.strip()]
obj_failed = {}
for line in open(os.path.join(HERE, "obj-failed.tsv")):
    if line.strip():
        key, reason = line.rstrip("\n").split("\t", 1)
        obj_failed[key] = reason
obj_rows = []
for path in sorted(glob.glob(os.path.join(HERE, "obj-reports", "*.json"))):
    r = json.load(open(path))
    scroll, segment = os.path.basename(path)[:-5].split(".", 1)
    kinds = sorted({f["kind"] for f in r["findings"]})
    t = r.get("topology", {})
    iso = r.get("isometry", {}).get("symmetric_stretch_distortion") or {}
    obj_rows.append({
        "scroll": scroll, "segment": segment, "status": r["status"], "tier": tier(kinds),
        "triangles": r.get("mesh", {}).get("triangles"),
        "components": t.get("components"), "holes": t.get("holes"),
        "nonmanifold_edges": t.get("nonmanifold_edges"),
        "inconsistent_winding_edges": t.get("inconsistent_winding_edges"),
        "jump_edges": r.get("edges", {}).get("jump_edges"),
        "normal_reversal_pairs": r.get("normals", {}).get("reversal_pairs"),
        "uv_flips": r.get("isometry", {}).get("flipped_uv_triangles"),
        "isometry_stretch_p95": round(iso["p95"], 3) if iso.get("p95") is not None else None,
        "findings": kinds, "errors": r.get("errors", []),
        "report": f"obj-reports/{os.path.basename(path)}",
    })
obj_missing = [k for k in obj_listed if k not in obj_failed and not os.path.exists(
    os.path.join(HERE, "obj-reports", f"{k.split('/')[0]}.{k.split('/')[2]}.json"))]
# Segment-level cross-format agreement on the shared finding kinds.
xf = {"both_flag": 0, "tifxyz_only": 0, "obj_only": 0, "neither": 0}
for o in obj_rows:
    meshes = by_seg.get((o["scroll"], o["segment"]))
    if not meshes:
        continue
    a = any(set(m["findings"]) & SHARED for m in meshes)
    b = bool(set(o["findings"]) & SHARED)
    xf["both_flag" if a and b else "tifxyz_only" if a else "obj_only" if b else "neither"] += 1
obj_control = [o for o in obj_rows if o["segment"] == CONTROL]
obj_summary = {
    "listed": len(obj_listed), "audited": len(obj_rows), "failed": obj_failed,
    "unaccounted": obj_missing,
    "positive_control_flagged": bool(obj_control) and bool(set(obj_control[0]["findings"]) & SHARED),
    "tier_counts": {t: sum(1 for x in obj_rows if x["tier"] == t)
                    for t in ("clean", "review", "multi-defect")},
    "finding_counts": {k: sum(1 for x in obj_rows if k in x["findings"])
                       for k in sorted({k for x in obj_rows for k in x["findings"]})},
    "cross_format_segments": xf,
    "rows": obj_rows,
}

summary = {
    "diagnostic": "scroliq-mesh on every primary TIFXYZ mesh in the open bucket",
    "source_bucket": "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com",
    "as_of": "2026-10-01",
    # complete: every listed mesh audited; partial: the rest are logged failures;
    # unverified: something is unaccounted for or the positive control missed.
    "status": ("unverified" if not (complete and control_ok)
               else "complete" if not failed else "partial"),
    "listed_meshes": len(listed),
    "audited_meshes": len(rows),
    "failed_meshes": len(failed),
    "unaccounted_meshes": missing,
    "segments": len(by_seg),
    "positive_control": {"segment": CONTROL, "meshes": len(control),
                         "all_multi_defect": control_ok},
    "tier_counts": {t: sum(1 for x in rows if x["tier"] == t)
                    for t in ("clean", "review", "multi-defect")},
    "finding_counts": {k: sum(1 for x in rows if k in x["findings"])
                       for k in sorted({k for x in rows for k in x["findings"]})},
    "cross_registration": {"segments_with_multiple_meshes": len(multi),
                           "identical_finding_kinds": agree},
    "by_scroll": dict(sorted(by_scroll.items())),
    "failed": failed,
    "rows": rows,
    "obj": obj_summary,
}
with open(os.path.join(HERE, "summary.json"), "w") as fh:
    json.dump(summary, fh, indent=1)

flagged = sorted((x for x in rows if x["tier"] == "multi-defect"),
                 key=lambda x: (x["scroll"], x["segment"], x["volume_id"] or ""))
with open(os.path.join(HERE, "flagged.tsv"), "w", newline="") as fh:
    w = csv.writer(fh, delimiter="\t")
    w.writerow(["scroll", "segment", "volume_id", "voxel", "components", "holes",
                "jump_edges", "normal_reversals", "isometry_p95", "findings"])
    for x in flagged:
        w.writerow([x["scroll"], x["segment"], x["volume_id"], x["voxel"], x["components"],
                    x["enclosed_invalid_components"], x["jump_edges"],
                    x["normal_reversal_pairs"], x["isometry_stretch_p95"],
                    ",".join(x["findings"])])
brief = {k: v for k, v in summary.items() if k not in ("rows", "failed", "obj")}
brief["obj"] = {k: v for k, v in obj_summary.items() if k != "rows"}
print(json.dumps(brief, indent=1))
