"""Read-only Wavefront OBJ triangle-mesh diagnostics for Vesuvius Challenge surfaces.

The TIFXYZ audit (``scroliq-mesh``) relies on the quad grid for adjacency. A
triangle mesh has no grid, so this audit derives adjacency from shared edges
and reports the same defect families where they translate (connectivity,
holes, edge jumps, neighbouring-normal reversals, UV-to-3D isometry), plus the
ones only a free-form mesh can have: non-manifold edges, inconsistent face
winding, degenerate faces and flipped UV triangles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from scrollq.tifxyz_audit import _summary

DIAGNOSTIC = "obj-mesh-audit"
SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _index(token: str, count: int) -> int:
    """OBJ indices are 1-based; negative indices count back from the end."""
    i = int(token)
    if i == 0:
        raise ValueError("OBJ index 0 is invalid")
    return i - 1 if i > 0 else count + i


def parse_obj(path: str | Path) -> dict[str, Any]:
    """Parse vertices, texture coordinates and faces (polygons fan-triangulated)."""
    vertices: list[list[float]] = []
    uvs: list[list[float]] = []
    faces: list[list[int]] = []
    face_uvs: list[list[int] | None] = []
    polygons = 0
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            tag = parts[0]
            try:
                if tag == "v":
                    vertices.append([float(x) for x in parts[1:4]])
                    if len(vertices[-1]) != 3:
                        raise ValueError("vertex needs 3 coordinates")
                elif tag == "vt":
                    uvs.append([float(x) for x in parts[1:3]])
                    if len(uvs[-1]) != 2:
                        raise ValueError("texture coordinate needs 2 values")
                elif tag == "f":
                    refs = [p.split("/") for p in parts[1:]]
                    if len(refs) < 3:
                        raise ValueError("face needs at least 3 vertices")
                    vi = [_index(r[0], len(vertices)) for r in refs]
                    ti = ([_index(r[1], len(uvs)) for r in refs]
                          if all(len(r) > 1 and r[1] for r in refs) else None)
                    polygons += 1
                    for k in range(1, len(vi) - 1):
                        faces.append([vi[0], vi[k], vi[k + 1]])
                        face_uvs.append([ti[0], ti[k], ti[k + 1]] if ti else None)
            except ValueError as exc:
                raise ValueError(f"line {lineno}: {exc}") from None
    return {
        "vertices": np.asarray(vertices, dtype=np.float64).reshape(-1, 3),
        "uvs": np.asarray(uvs, dtype=np.float64).reshape(-1, 2),
        "faces": np.asarray(faces, dtype=np.int64).reshape(-1, 3),
        "face_uvs": face_uvs,
        "polygons": polygons,
    }


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = np.arange(n)

    def find(self, i: int) -> int:
        p = self.parent
        root = i
        while p[root] != root:
            root = p[root]
        while p[i] != root:
            p[i], i = root, p[i]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _edge_table(faces: np.ndarray) -> dict[str, np.ndarray]:
    """Directed half-edges grouped by undirected edge."""
    n = len(faces)
    a = faces.reshape(-1)
    b = faces[:, [1, 2, 0]].reshape(-1)
    face = np.repeat(np.arange(n), 3)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    order = np.lexsort((hi, lo))
    lo, hi, a, face = lo[order], hi[order], a[order], face[order]
    new = np.ones(len(lo), dtype=bool)
    new[1:] = (lo[1:] != lo[:-1]) | (hi[1:] != hi[:-1])
    group = np.cumsum(new) - 1
    counts = np.bincount(group)
    return {"lo": lo, "hi": hi, "start": a, "face": face, "group": group,
            "counts": counts, "first": np.flatnonzero(new)}


def audit_obj(
    path: str | Path,
    *,
    jump_ratio: float = 4.0,
    isometry_p95_threshold: float = 2.0,
    normal_flip_angle_deg: float = 120.0,
) -> dict[str, Any]:
    src = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, str]] = []
    base = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "obj_path": str(src),
    }
    if jump_ratio <= 1 or isometry_p95_threshold <= 1 or not 0 < normal_flip_angle_deg < 180:
        raise ValueError("thresholds must be > 1 and the flip angle in (0, 180)")
    try:
        mesh = parse_obj(src)
    except (OSError, ValueError) as exc:
        return {**base, "status": "fail", "error_count": 1, "warning_count": 0,
                "errors": [f"cannot parse OBJ: {exc}"], "warnings": [], "findings": []}

    v, faces, uv = mesh["vertices"], mesh["faces"], mesh["uvs"]
    provenance = {"sha256": _sha256(src), "bytes": src.stat().st_size}
    if not len(faces):
        # Nothing inspected is not a clean result.
        return {**base, "status": "fail", "provenance": provenance,
                "error_count": 1, "warning_count": 0,
                "errors": ["OBJ has no faces; nothing to audit"], "warnings": [],
                "findings": []}
    if faces.min() < 0 or faces.max() >= len(v):
        return {**base, "status": "fail", "provenance": provenance,
                "error_count": 1, "warning_count": 0,
                "errors": ["face references a vertex index out of range"],
                "warnings": [], "findings": []}
    if not np.isfinite(v).all():
        errors.append(f"{int((~np.isfinite(v).all(axis=1)).sum())} vertex(es) have non-finite coordinates")

    used = np.zeros(len(v), dtype=bool)
    used[faces.reshape(-1)] = True
    p0, p1, p2 = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
    cross = np.cross(p1 - p0, p2 - p0)
    area2 = np.linalg.norm(cross, axis=1)
    repeated = ((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2])
                | (faces[:, 0] == faces[:, 2]))
    degenerate = repeated | ~np.isfinite(area2) | (area2 <= 1e-12)
    if degenerate.any():
        warnings.append(f"{int(degenerate.sum())} degenerate (zero-area) face(s)")
        findings.append({"kind": "degenerate", "severity": "review",
                         "message": f"{int(degenerate.sum())} zero-area face(s)"})

    et = _edge_table(faces)
    counts = et["counts"]
    boundary_edges = int((counts == 1).sum())
    nonmanifold_edges = int((counts > 2).sum())
    if nonmanifold_edges:
        warnings.append(f"{nonmanifold_edges} non-manifold edge(s) shared by more than two faces")
        findings.append({"kind": "non-manifold", "severity": "review",
                         "message": f"{nonmanifold_edges} edge(s) shared by more than two faces"})

    # Edge-connected face components.
    uf = _UnionFind(len(faces))
    for gid in np.flatnonzero(counts > 1):
        s = et["first"][gid]
        for k in range(1, counts[gid]):
            uf.union(int(et["face"][s]), int(et["face"][s + k]))
    roots = np.fromiter((uf.find(i) for i in range(len(faces))), dtype=np.int64, count=len(faces))
    comp_ids, comp_sizes = np.unique(roots, return_counts=True)
    components = int(len(comp_ids))
    if components > 1:
        warnings.append(f"mesh has {components} edge-disconnected components")
        findings.append({"kind": "connectivity", "severity": "review",
                         "message": f"{components} edge-disconnected face components"})

    # Boundary loops: connected components of the boundary-edge graph.
    bmask = counts[et["group"]] == 1
    bl, bh = et["lo"][bmask], et["hi"][bmask]
    bverts = np.unique(np.concatenate([bl, bh])) if bl.size else np.asarray([], dtype=np.int64)
    loops = 0
    if bverts.size:
        local = {int(x): i for i, x in enumerate(bverts)}
        buf = _UnionFind(len(bverts))
        for x, y in zip(bl, bh):
            buf.union(local[int(x)], local[int(y)])
        loops = len({buf.find(i) for i in range(len(bverts))})
    comp_of_face = {int(r): i for i, r in enumerate(comp_ids)}
    bfaces = et["face"][bmask]
    components_with_boundary = len({comp_of_face[int(roots[f])] for f in bfaces})
    holes = max(0, loops - components_with_boundary)
    if holes:
        warnings.append(f"{holes} interior boundary loop(s) (holes)")
        findings.append({"kind": "hole", "severity": "review",
                         "message": f"{holes} interior boundary loop(s)"})

    # Winding consistency and neighbouring-normal reversal over manifold interior edges.
    interior = np.flatnonzero(counts == 2)
    s = et["first"][interior]
    fa, fb = et["face"][s], et["face"][s + 1]
    same_direction = et["start"][s] == et["start"][s + 1]
    inconsistent = int(same_direction.sum())
    if inconsistent:
        warnings.append(f"{inconsistent} interior edge(s) with inconsistent face winding")
        findings.append({"kind": "orientation", "severity": "review",
                         "message": f"{inconsistent} edge(s) traversed in the same direction by both faces"})
    ok = ~degenerate
    unit = np.zeros_like(cross)
    unit[ok] = cross[ok] / area2[ok, None]
    pair_ok = ok[fa] & ok[fb]
    dots = (unit[fa] * unit[fb]).sum(axis=1)
    # A winding flip negates one normal; compare surfaces, not bookkeeping.
    dots = np.where(same_direction, -dots, dots)[pair_ok]
    cutoff = math.cos(math.radians(normal_flip_angle_deg))
    reversals = int((dots < cutoff).sum())
    if reversals:
        warnings.append(f"{reversals} neighbouring face pair(s) reverse by more than {normal_flip_angle_deg:g} degrees")
        findings.append({"kind": "normal-reversal", "severity": "review",
                         "message": f"{reversals} severe neighbouring-normal reversals"})

    # Edge jumps relative to the median edge length.
    lengths = np.linalg.norm(v[et["lo"][et["first"]]] - v[et["hi"][et["first"]]], axis=1)
    finite = lengths[np.isfinite(lengths) & (lengths > 0)]
    median = float(np.median(finite)) if finite.size else 0.0
    jumps = int((lengths > jump_ratio * median).sum()) if median > 0 else 0
    if jumps:
        warnings.append(f"{jumps} edge(s) exceed {jump_ratio:g}x the median edge length")
        findings.append({"kind": "edge-jump", "severity": "review",
                         "message": f"{jumps} edges exceed {jump_ratio:g}x median length"})

    # UV -> 3D isometry, up to one global scale (OBJ UVs are normalized).
    textured = np.asarray([fu is not None for fu in mesh["face_uvs"]], dtype=bool)
    isometry: dict[str, Any] = {"status": "unknown", "reason": "no texture coordinates on faces"}
    if textured.any() and len(uv):
        tu = np.asarray([fu for fu in mesh["face_uvs"] if fu is not None], dtype=np.int64)
        if tu.min() < 0 or tu.max() >= len(uv):
            errors.append("face references a texture coordinate out of range")
        else:
            t0, t1, t2 = uv[tu[:, 0]], uv[tu[:, 1]], uv[tu[:, 2]]
            d1, d2 = t1 - t0, t2 - t0
            uv_area2 = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
            e1 = (p1 - p0)[textured]
            e2 = (p2 - p0)[textured]
            good = (np.abs(uv_area2) > 1e-18) & ok[textured]
            majority = 1.0 if (uv_area2[good] > 0).sum() >= (uv_area2[good] < 0).sum() else -1.0
            flipped = int((good & (np.sign(uv_area2) == -majority)).sum())
            scale = math.sqrt(area2[textured][good].sum() / np.abs(uv_area2[good]).sum()) if good.any() else 0.0
            # J maps UV to 3D: [e1 e2] = J [d1 d2]  =>  J = E D^-1
            D = np.stack([d1, d2], axis=-1)[good] * scale
            E = np.stack([e1, e2], axis=-1)[good]
            J = E @ np.linalg.inv(D)
            gram = np.einsum("nki,nkj->nij", J, J)
            sv = np.sqrt(np.clip(np.linalg.eigvalsh(gram), 0.0, None))
            usable = sv[:, 0] > 1e-8
            stretch = np.maximum(sv[usable, 1], 1.0 / sv[usable, 0])
            summary = _summary(stretch)
            isometry = {
                "status": "measured",
                "method": "per-triangle singular values of the UV-to-3D Jacobian, "
                          "UVs rescaled by one global factor so total areas match",
                "global_uv_scale": scale,
                "textured_triangles": int(textured.sum()),
                "untextured_triangles": int((~textured).sum()),
                "degenerate_uv_triangles": int((~good).sum()),
                "flipped_uv_triangles": flipped,
                "symmetric_stretch_distortion": summary,
            }
            if flipped:
                warnings.append(f"{flipped} UV triangle(s) folded over (opposite orientation)")
                findings.append({"kind": "uv-flip", "severity": "review",
                                 "message": f"{flipped} flipped UV triangles"})
            p95 = summary["p95"]
            if p95 is not None and p95 > isometry_p95_threshold:
                warnings.append(f"p95 local isometry distortion {p95:.2f} exceeds {isometry_p95_threshold:g}")
                findings.append({"kind": "isometry-distortion", "severity": "review",
                                 "message": f"p95 local symmetric stretch {p95:.2f} exceeds {isometry_p95_threshold:g}"})

    status = "fail" if errors else ("partial" if warnings else "pass")
    return {
        **base,
        "status": status,
        "provenance": provenance,
        "mesh": {
            "vertices": int(len(v)),
            "unreferenced_vertices": int((~used).sum()),
            "polygons": mesh["polygons"],
            "triangles": int(len(faces)),
            "degenerate_triangles": int(degenerate.sum()),
            "surface_area": float(0.5 * area2[ok].sum()),
            "bbox": ([v[used].min(axis=0).tolist(), v[used].max(axis=0).tolist()]
                     if used.any() and np.isfinite(v[used]).all() else None),
        },
        "topology": {
            "components": components,
            "largest_component_faces": int(comp_sizes.max()),
            "edges": int(len(counts)),
            "boundary_edges": boundary_edges,
            "nonmanifold_edges": nonmanifold_edges,
            "boundary_loops": loops,
            "holes": holes,
            "inconsistent_winding_edges": inconsistent,
        },
        "edges": {"length": _summary(lengths), "jump_ratio": jump_ratio, "jump_edges": jumps},
        "normals": {"neighbor_dot": _summary(dots), "flip_angle_deg": normal_flip_angle_deg,
                    "reversal_pairs": reversals},
        "isometry": isometry,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
        "limitation": ("Geometry and parameterization only. Says nothing about whether the "
                       "surface follows the papyrus sheet in the CT; self-intersection is not "
                       "checked."),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit one Wavefront OBJ triangle mesh without modifying it")
    ap.add_argument("--obj", required=True)
    ap.add_argument("--jump-ratio", type=float, default=4.0)
    ap.add_argument("--isometry-p95-threshold", type=float, default=2.0)
    ap.add_argument("--normal-flip-angle", type=float, default=120.0)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--fail-on-findings", action="store_true",
        help="exit 2 when review findings are present, for CI/pipeline gating",
    )
    args = ap.parse_args()
    result = audit_obj(
        args.obj,
        jump_ratio=args.jump_ratio,
        isometry_p95_threshold=args.isometry_p95_threshold,
        normal_flip_angle_deg=args.normal_flip_angle,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['status'].upper()} {args.obj}: "
          f"{result.get('error_count', 0)} error(s), {result.get('warning_count', 0)} warning(s)")
    if result["status"] == "fail" or (args.fail_on_findings and result.get("findings")):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
