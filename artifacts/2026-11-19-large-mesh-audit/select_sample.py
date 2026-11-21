"""Deterministic equivalence sample from the 2026-10-01 corpus mesh audit.

Per scroll: the smallest multi-defect mesh, the smallest mesh in another tier,
and the largest mesh whose z.tif is at most 80 MB (so the unblocked baseline
still fits in 16 GB and the blocked code splits it into several row blocks).
Plus the hand-confirmed broken PHerc1447 segment. Prints one report path per
line, relative to ../2026-10-01-corpus-mesh-audit/.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "2026-10-01-corpus-mesh-audit")
LIMIT = 80_000_000
CONTROL = "20251105093211-z_dbg_gen_00320"

rows = json.load(open(os.path.join(SRC, "summary.json")))["rows"]
for r in rows:
    rep = json.load(open(os.path.join(SRC, r["report"])))
    r["z_bytes"] = rep["provenance"]["z.tif"]["bytes"]
picked = []
for scroll in sorted({r["scroll"] for r in rows}):
    mine = sorted((r for r in rows if r["scroll"] == scroll), key=lambda r: (r["z_bytes"], r["report"]))
    md = [r for r in mine if r["tier"] == "multi-defect"]
    other = [r for r in mine if r["tier"] != "multi-defect"]
    fits = [r for r in mine if r["z_bytes"] <= LIMIT]
    for r in (md[:1] + other[:1] + fits[-1:]):
        if r["report"] not in picked:
            picked.append(r["report"])
for r in rows:
    if r["segment"] == CONTROL and r["report"] not in picked:
        picked.append(r["report"])
print("\n".join(picked))
