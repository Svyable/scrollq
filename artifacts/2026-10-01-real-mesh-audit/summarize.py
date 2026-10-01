"""Summarize the per-segment scroliq-mesh reports into summary.json."""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for path in sorted(glob.glob(os.path.join(HERE, "reports", "*.json"))):
    r = json.load(open(path))
    g, q, e = r["grid"], r["quads"], r["edges"]
    iso = q["isometry"]["symmetric_stretch_distortion"]
    scroll, segment = os.path.basename(path)[:-5].split(".", 1)
    rows.append({
        "scroll": scroll,
        "segment": segment,
        "volume_root": r["volume_root"],
        "status": r["status"],
        "valid_vertex_fraction": round(g["valid_vertex_fraction"], 3),
        "components": g["valid_vertex_components"]["components"],
        "enclosed_invalid_components": g["enclosed_invalid_components"],
        "jump_edges": e["columns"]["jump_edges"] + e["rows"]["jump_edges"],
        "normal_reversal_pairs": q["normal_reversal_pairs"],
        "isometry_stretch_p95": round(iso["p95"], 3),
        "isometry_stretch_max": round(iso["max"], 3),
        "findings": [f["kind"] for f in r["findings"]],
        "report": f"reports/{os.path.basename(path)}",
    })
summary = {
    "diagnostic": "scroliq-mesh on published TIFXYZ segments",
    "source_bucket": "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com",
    "segments": len(rows),
    "by_scroll": {s: sum(1 for x in rows if x["scroll"] == s)
                  for s in sorted({x["scroll"] for x in rows})},
    "status_counts": {s: sum(1 for x in rows if x["status"] == s)
                      for s in sorted({x["status"] for x in rows})},
    "rows": rows,
}
with open(os.path.join(HERE, "summary.json"), "w") as fh:
    json.dump(summary, fh, indent=1)
print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
