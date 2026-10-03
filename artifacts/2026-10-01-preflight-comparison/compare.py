"""Join upstream preflight reports with the frozen scroliq-mesh reports.

Before joining, every mesh file under out/s3/ is hashed and checked against
the SHA-256 recorded in the scroliq-mesh report, so both tools are shown to
have judged the same bytes.
"""
import glob
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MESH = os.path.join(ROOT, "artifacts", "2026-10-01-real-mesh-audit")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


rows = []
for path in sorted(glob.glob(os.path.join(MESH, "reports", "*.json"))):
    name = os.path.basename(path)
    mesh = json.load(open(path))
    pre = json.load(open(os.path.join(HERE, "preflight", name)))
    tifxyz = os.path.join(ROOT, mesh["tifxyz_path"])
    same_bytes = all(
        sha256(os.path.join(tifxyz, f)) == rec["sha256"]
        for f, rec in mesh["provenance"].items()
    )
    gates = pre["gates"]
    scroll, segment = name[:-5].split(".", 1)
    rows.append({
        "scroll": scroll,
        "segment": segment,
        "same_bytes_as_mesh_audit": same_bytes,
        "preflight_status": pre["status"],
        "preflight_gates_passed": sum(1 for g in gates if g["passed"]),
        "preflight_gates_run": len(gates),
        "preflight_failed_gates": [g["name"] for g in gates if not g["passed"]],
        "scroliq_mesh_status": mesh["status"],
        "scroliq_mesh_findings": [f["kind"] for f in mesh["findings"]],
    })


# Fail closed rather than write a comparison that checked nothing: a preflight
# that could not read its inputs (e.g. imagecodecs missing for the LZW tifs)
# reports FAIL on every mesh, which would read as the opposite finding.
unread = [f"{r['scroll']}.{r['segment']}" for r in rows
          if "input_readable" in r["preflight_failed_gates"]]
if not rows or unread or not all(r["same_bytes_as_mesh_audit"] for r in rows):
    raise SystemExit(
        f"refusing to write comparison.json: {len(rows)} rows, "
        f"{len(unread)} preflight reports could not read their inputs, "
        f"same bytes: {all(r['same_bytes_as_mesh_audit'] for r in rows)}")


def counts(key):
    return {v: sum(1 for r in rows if r[key] == v)
            for v in sorted({r[key] for r in rows})}


comparison = {
    "question": "Does upstream structure-only preflight separate the meshes "
                "that scroliq-mesh flags?",
    "upstream": {
        "tool": "vesuvius.surface_preflight",
        "repo": "https://github.com/ScrollPrize/villa",
        "commit": "078e9eb3410f93f965951334bebca107cbe8dffb",
        "file_sha256": "862e4f1f78659730bbab43345716e52c3dc8c5c743c97718bd55b6ba2d3bce46",
        "mode": "structure-only (no --volume)",
    },
    "segments": len(rows),
    "all_same_bytes": all(r["same_bytes_as_mesh_audit"] for r in rows),
    "preflight_status_counts": counts("preflight_status"),
    "scroliq_mesh_status_counts": counts("scroliq_mesh_status"),
    "rows": rows,
}
with open(os.path.join(HERE, "comparison.json"), "w") as fh:
    json.dump(comparison, fh, indent=1)
    fh.write("\n")
print(json.dumps({k: v for k, v in comparison.items() if k != "rows"}, indent=1))
