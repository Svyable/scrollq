"""Beltrami -> modified-Laplacian -> harmonic reconstruction round-trip.

Experimental validation slice for issue #114. This is NOT the 2026
coarse-to-fine Beltrami-prolongation method yet.

Given an already-valid triangle OBJ with one consistent UV value per 3-D
vertex, the script:
1. extracts the per-face Beltrami coefficient of the existing 3-D->UV map;
2. applies L_mu(v) = v + mu * conjugate(v) to each intrinsic triangle;
3. derives the transformed corner cotangents and assembles the modified
   cotangent Laplacian;
4. fixes all boundary-loop vertices to their original UVs and solves the
   harmonic interior;
5. writes the reconstructed UV map on the exact same ordered 3-D geometry.

Because mu came from the source UV map itself, this is a closed-loop math
control. The reconstructed UVs should match the originals to numerical
precision. Failure means the Beltrami/Laplacian implementation is not yet
trustworthy enough to attempt coefficient prolongation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from scrollq.obj_audit import parse_obj


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fmt(value: float) -> str:
    return format(float(value), ".17g")


def _vertex_uvs(mesh: dict[str, Any]) -> np.ndarray:
    vertices = mesh["vertices"]
    uvs = mesh["uvs"]
    faces = mesh["faces"]
    face_uvs = mesh["face_uvs"]

    if mesh["polygons"] != len(faces):
        raise ValueError("Beltrami round-trip requires triangle-only OBJ input")
    if len(uvs) == 0 or any(item is None for item in face_uvs):
        raise ValueError("Beltrami round-trip requires UV coordinates on every face")

    out = np.full((len(vertices), 2), np.nan, dtype=np.float64)
    assigned = np.zeros(len(vertices), dtype=bool)

    for face, uv_face in zip(faces, face_uvs, strict=True):
        assert uv_face is not None
        for vi, ti in zip(face, uv_face, strict=True):
            value = uvs[int(ti)]
            vi = int(vi)
            if assigned[vi]:
                if not np.array_equal(out[vi], value):
                    raise ValueError(
                        "Beltrami round-trip currently requires one consistent UV "
                        f"coordinate per 3-D vertex; vertex {vi + 1} has a UV seam"
                    )
            else:
                out[vi] = value
                assigned[vi] = True

    if not np.all(assigned):
        missing = int(np.count_nonzero(~assigned))
        raise ValueError(f"OBJ has {missing} vertex/vertices without a face UV assignment")
    return out


def _orient_uvs(uv: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, bool]:
    a = uv[faces[:, 1]] - uv[faces[:, 0]]
    b = uv[faces[:, 2]] - uv[faces[:, 0]]
    signed = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]

    scale = max(
        1.0,
        float(np.ptp(uv[:, 0])),
        float(np.ptp(uv[:, 1])),
    )
    eps = np.finfo(np.float64).eps * scale * scale * 64.0
    if np.any(np.abs(signed) <= eps):
        raise ValueError("source UV map contains a degenerate triangle")

    positive = int(np.count_nonzero(signed > 0))
    negative = int(np.count_nonzero(signed < 0))
    orientation = 1.0 if positive >= negative else -1.0
    if np.any(signed * orientation <= 0):
        raise ValueError("source UV map contains inconsistent triangle orientation")

    if orientation > 0:
        return uv.copy(), False

    corrected = uv.copy()
    corrected[:, 1] *= -1.0
    return corrected, True


def _intrinsic_triangle_coordinates(
    vertices: np.ndarray, faces: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    p0 = vertices[faces[:, 0]]
    e1 = vertices[faces[:, 1]] - p0
    e2 = vertices[faces[:, 2]] - p0

    l1 = np.linalg.norm(e1, axis=1)
    bbox_diag = float(np.linalg.norm(np.ptp(vertices, axis=0))) if len(vertices) else 0.0
    eps = np.finfo(np.float64).eps * max(1.0, bbox_diag) * 64.0
    if np.any(l1 <= eps):
        raise ValueError("source 3-D mesh contains a degenerate triangle edge")

    x_axis = e1 / l1[:, None]
    x2 = np.einsum("ij,ij->i", e2, x_axis)
    perpendicular = e2 - x2[:, None] * x_axis
    y2 = np.linalg.norm(perpendicular, axis=1)
    if np.any(y2 <= eps):
        raise ValueError("source 3-D mesh contains a degenerate triangle")

    return l1, x2, y2


def extract_beltrami(
    vertices: np.ndarray,
    faces: np.ndarray,
    oriented_uv: np.ndarray,
) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Extract per-face mu for the intrinsic 3-D triangle -> UV affine map."""
    l1, x2, y2 = _intrinsic_triangle_coordinates(vertices, faces)

    q1 = oriented_uv[faces[:, 1]] - oriented_uv[faces[:, 0]]
    q2 = oriented_uv[faces[:, 2]] - oriented_uv[faces[:, 0]]

    # q = [x, y] A, where A's columns are the gradients of u and v.
    ux = q1[:, 0] / l1
    vx = q1[:, 1] / l1
    uy = (q2[:, 0] - x2 * ux) / y2
    vy = (q2[:, 1] - x2 * vx) / y2

    fz = 0.5 * ((ux + vy) + 1j * (vx - uy))
    fzb = 0.5 * ((ux - vy) + 1j * (vx + uy))

    if np.any(np.abs(fz) <= np.finfo(np.float64).tiny):
        raise ValueError("source map has a singular complex derivative")

    mu = fzb / fz
    abs_mu = np.abs(mu)
    if not np.all(np.isfinite(abs_mu)):
        raise ValueError("non-finite Beltrami coefficient")
    if np.any(abs_mu >= 1.0):
        worst = float(abs_mu.max())
        raise ValueError(
            "source map is not strictly orientation-preserving in Beltrami form "
            f"(max |mu|={worst:.17g})"
        )

    return mu, (l1, x2, y2)


def modified_corner_cotangents(
    mu: np.ndarray,
    intrinsic: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> np.ndarray:
    """Return [cot(angle0), cot(angle1), cot(angle2)] per triangle."""
    l1, x2, y2 = intrinsic
    z1 = l1.astype(np.complex128)
    z2 = x2 + 1j * y2

    w1 = z1 + mu * np.conjugate(z1)
    w2 = z2 + mu * np.conjugate(z2)

    cross = np.imag(np.conjugate(w1) * w2)
    if np.any(cross <= 0):
        raise ValueError("Beltrami-transformed local triangle lost orientation")

    dot12 = np.real(np.conjugate(w1) * w2)
    area2 = cross

    cot0 = dot12 / area2
    cot1 = (np.abs(w1) ** 2 - dot12) / area2
    cot2 = (np.abs(w2) ** 2 - dot12) / area2
    cot = np.column_stack((cot0, cot1, cot2))

    if not np.all(np.isfinite(cot)):
        raise ValueError("modified corner cotangent is non-finite")
    return cot


def _laplacian_triplets(
    faces: np.ndarray,
    cot: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Cotangent at vertex 0 weights edge (1,2), etc.
    a = np.concatenate((faces[:, 1], faces[:, 0], faces[:, 0]))
    b = np.concatenate((faces[:, 2], faces[:, 2], faces[:, 1]))
    w = np.concatenate((cot[:, 0], cot[:, 1], cot[:, 2]))

    rows = np.concatenate((a, a, b, b))
    cols = np.concatenate((a, b, a, b))
    data = np.concatenate((w, -w, -w, w))
    return rows.astype(np.int64), cols.astype(np.int64), data.astype(np.float64)


def boundary_vertices(faces: np.ndarray) -> np.ndarray:
    edges = np.concatenate(
        (
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ),
        axis=0,
    )
    edges = np.sort(edges, axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    boundary_edges = unique[counts == 1]
    if len(boundary_edges) == 0:
        raise ValueError("mesh has no boundary; disk-like harmonic control is undefined")
    return np.unique(boundary_edges.reshape(-1))


def _solve_harmonic(
    vertex_count: int,
    rows: np.ndarray,
    cols: np.ndarray,
    data: np.ndarray,
    boundary: np.ndarray,
    boundary_uv: np.ndarray,
) -> tuple[np.ndarray, str, float]:
    fixed = np.zeros(vertex_count, dtype=bool)
    fixed[boundary] = True
    interior = np.flatnonzero(~fixed)

    out = np.zeros((vertex_count, 2), dtype=np.float64)
    out[boundary] = boundary_uv

    if len(interior) == 0:
        return out, "boundary-only", 0.0

    try:
        import scipy.sparse as sp
        import scipy.sparse.linalg as spla
    except ImportError:
        if vertex_count > 256:
            raise RuntimeError(
                "SciPy is required for Beltrami round-trip meshes with more than "
                "256 vertices; install scipy==1.18.1 for the R&D workflow"
            )
        dense = np.zeros((vertex_count, vertex_count), dtype=np.float64)
        np.add.at(dense, (rows, cols), data)
        a = dense[np.ix_(interior, interior)]
        rhs = -dense[np.ix_(interior, boundary)] @ boundary_uv
        out[interior] = np.linalg.solve(a, rhs)
        residual = dense @ out
        max_residual = float(np.max(np.abs(residual[interior])))
        return out, "numpy-dense", max_residual

    lap = sp.coo_matrix(
        (data, (rows, cols)),
        shape=(vertex_count, vertex_count),
        dtype=np.float64,
    ).tocsr()
    lap.sum_duplicates()

    a = lap[interior][:, interior]
    coupling = lap[interior][:, boundary]
    rhs = -(coupling @ boundary_uv)

    solved = np.empty((len(interior), 2), dtype=np.float64)
    solved[:, 0] = spla.spsolve(a, rhs[:, 0])
    solved[:, 1] = spla.spsolve(a, rhs[:, 1])
    if not np.all(np.isfinite(solved)):
        raise ValueError("harmonic solve produced non-finite UV coordinates")

    out[interior] = solved
    residual = lap @ out
    max_residual = float(np.max(np.abs(residual[interior])))
    return out, "scipy-spsolve", max_residual


def _write_obj(
    path: Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    uv: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# ScrolIQ Beltrami/Laplacian round-trip candidate\n")
        for x, y, z in vertices:
            fh.write(f"v {_fmt(x)} {_fmt(y)} {_fmt(z)}\n")
        for u, v in uv:
            fh.write(f"vt {_fmt(u)} {_fmt(v)}\n")
        for i, j, k in faces:
            i, j, k = int(i) + 1, int(j) + 1, int(k) + 1
            fh.write(f"f {i}/{i} {j}/{j} {k}/{k}\n")


def beltrami_roundtrip(
    source: str | Path,
    destination: str | Path,
    *,
    max_normalized_uv_error: float = 1e-8,
) -> dict[str, Any]:
    if not math.isfinite(max_normalized_uv_error) or max_normalized_uv_error <= 0:
        raise ValueError("max_normalized_uv_error must be finite and positive")

    src = Path(source)
    dst = Path(destination)
    mesh = parse_obj(src)
    vertices = mesh["vertices"]
    faces = mesh["faces"]
    source_uv = _vertex_uvs(mesh)
    oriented_uv, reflected = _orient_uvs(source_uv, faces)

    mu, intrinsic = extract_beltrami(vertices, faces, oriented_uv)
    cot = modified_corner_cotangents(mu, intrinsic)
    rows, cols, data = _laplacian_triplets(faces, cot)
    boundary = boundary_vertices(faces)

    reconstructed_oriented, backend, max_residual = _solve_harmonic(
        len(vertices),
        rows,
        cols,
        data,
        boundary,
        oriented_uv[boundary],
    )

    reconstructed = reconstructed_oriented.copy()
    if reflected:
        reconstructed[:, 1] *= -1.0

    delta = reconstructed - source_uv
    point_error = np.linalg.norm(delta, axis=1)
    uv_span = float(np.linalg.norm(np.ptp(source_uv, axis=0)))
    normalization = max(uv_span, np.finfo(np.float64).tiny)
    max_error = float(point_error.max(initial=0.0))
    rms_error = float(np.sqrt(np.mean(point_error**2))) if len(point_error) else 0.0
    normalized_max = max_error / normalization

    _write_obj(dst, vertices, faces, reconstructed)

    abs_mu = np.abs(mu)
    status = "pass" if normalized_max <= max_normalized_uv_error else "fail"
    return {
        "schema_version": 1,
        "diagnostic": "beltrami-laplacian-roundtrip",
        "status": status,
        "source": {
            "path": str(src),
            "sha256": _sha256(src),
        },
        "candidate": {
            "path": str(dst),
            "sha256": _sha256(dst),
        },
        "mesh": {
            "vertices": int(len(vertices)),
            "triangles": int(len(faces)),
            "boundary_vertices": int(len(boundary)),
        },
        "source_orientation_reflected_for_solve": reflected,
        "beltrami": {
            "max_abs_mu": float(abs_mu.max(initial=0.0)),
            "p95_abs_mu": float(np.percentile(abs_mu, 95)) if len(abs_mu) else 0.0,
            "strictly_orientation_preserving": bool(np.all(abs_mu < 1.0)),
        },
        "solver": {
            "backend": backend,
            "max_interior_laplacian_residual": max_residual,
        },
        "uv_reconstruction": {
            "uv_span": uv_span,
            "max_vertex_error": max_error,
            "rms_vertex_error": rms_error,
            "normalized_max_vertex_error": normalized_max,
            "threshold_max_normalized_error": max_normalized_uv_error,
        },
        "claim_boundary": (
            "This validates Beltrami extraction, transformed corner cotangents, "
            "modified-Laplacian assembly, and harmonic reconstruction only. It does "
            "not implement or validate mesh simplification, coarse optimization, "
            "parallel transport, closest-point projection, or Beltrami prolongation, "
            "and cannot promote a production flattening backend."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--max-normalized-uv-error", type=float, default=1e-8)
    args = ap.parse_args()

    try:
        report = beltrami_roundtrip(
            args.source,
            args.out,
            max_normalized_uv_error=args.max_normalized_uv_error,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        report = {
            "schema_version": 1,
            "diagnostic": "beltrami-laplacian-roundtrip",
            "status": "fail",
            "error": str(exc),
        }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{report['status'].upper()} Beltrami/Laplacian round-trip: "
        f"{report.get('uv_reconstruction', {}).get('normalized_max_vertex_error', 'n/a')}"
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
