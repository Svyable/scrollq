"""Frozen PHerc0800 Spiral-grid transfer evaluator (issue #130).

Geometry-only, deterministic evaluation of preregistered PHerc0800 reference
TIFXYZ meshes against per-winding Spiral grids.  Held-out geometry never
participates in winding-index alignment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

DIAGNOSTIC = "pherc0800-spiral-transfer"
SCHEMA_VERSION = 1
EXPECTED_VOLUME_ID = "20250521135224"
EXPECTED_REFERENCE_REPOSITORY = "https://github.com/pscamillo/vesuvius-eligible-meshes"
EXPECTED_REFERENCE_COMMIT = "620769e2e1e70d1e61b588092229cb76d3af4804"
EXPECTED_CONTRACT_BLOB = "abc10ffeb3ca3c5a3b2355403b0467ef0d971b5d"
EXPECTED_SPLIT_BLOB = "86dd19ffa63e1db6dc610b30936b341aa4504591"
MAX_POINTS = 1024
MARGIN = 64.0


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: expected JSON object")
    return obj


def _verify_frozen_documents(contract_path: Path, split_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract_bytes = contract_path.read_bytes()
    split_bytes = split_path.read_bytes()
    if _git_blob_sha1(contract_bytes) != EXPECTED_CONTRACT_BLOB:
        raise ValueError("transfer preregistration content differs from frozen Git blob")
    if _git_blob_sha1(split_bytes) != EXPECTED_SPLIT_BLOB:
        raise ValueError("geometry split content differs from frozen Git blob")
    contract = _load_json(contract_path)
    split = _load_json(split_path)
    volume = contract.get("volume", {})
    source = contract.get("reference_source", {})
    if volume.get("prize_volume_id") != EXPECTED_VOLUME_ID:
        raise ValueError("transfer contract volume mismatch")
    if source.get("repository") != EXPECTED_REFERENCE_REPOSITORY or source.get("commit") != EXPECTED_REFERENCE_COMMIT:
        raise ValueError("transfer contract reference source/commit mismatch")
    if source.get("frozen_split") != "artifacts/2026-09-30-grand-prize-qualifier/pherc0800_geometry_split.json":
        raise ValueError("transfer contract frozen split path mismatch")
    if split.get("prize_volume_id") != EXPECTED_VOLUME_ID or split.get("split", {}).get("status") != "frozen":
        raise ValueError("geometry split volume/status mismatch")
    return contract, split


def _read_2d_tif(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        arr = np.asarray(image)
    if arr.ndim != 2:
        raise ValueError(f"{path}: coordinate TIFF must be single-channel 2D")
    return np.asarray(arr, dtype=np.float64)


def _manifest_blob(manifest: dict[str, Any], rel: str) -> str:
    files = manifest.get("files")
    if not isinstance(files, dict) or rel not in files:
        raise ValueError(f"reference blob identity missing from manifest: {rel}")
    value = files[rel]
    if isinstance(value, dict):
        value = value.get("git_blob_sha1")
    if not isinstance(value, str) or len(value) != 40:
        raise ValueError(f"invalid reference blob identity for {rel}")
    return value.lower()


def _verified_file(root: Path, manifest: dict[str, Any], rel: str, expected: str | None = None) -> Path:
    path = root / rel
    data = path.read_bytes()
    actual = _git_blob_sha1(data)
    declared = _manifest_blob(manifest, rel)
    if actual != declared:
        raise ValueError(f"reference blob mismatch for {rel}: actual {actual}, manifest {declared}")
    if expected is not None and actual != expected:
        raise ValueError(f"reference blob mismatch for frozen contract file {rel}")
    return path


def _midpoint_ranks(n: int, max_points: int = MAX_POINTS) -> np.ndarray:
    if n <= 0 or max_points <= 0:
        raise ValueError("n and max_points must be positive")
    k = min(n, max_points)
    return np.floor((np.arange(k, dtype=np.float64) + 0.5) * n / k).astype(np.int64)


def _choose_offset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in rows if r.get("eligible") is True]
    if not eligible:
        raise ValueError("no winding offset has all required fit-role predictions/cores")
    return min(
        eligible,
        key=lambda r: (
            float(r["fit_mesh_median_of_medians"]),
            abs(int(r["offset"])),
            int(r["offset"]),
        ),
    )


def _candidate_by_path(split: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = split.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("geometry split candidates missing")
    out: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("malformed geometry split candidate")
        out[item["path"]] = item
    return out


def _reference_spec(
    mesh_path: str,
    split_item: dict[str, Any],
    contract_heldout: dict[str, Any] | None,
) -> dict[str, Any]:
    wrap = split_item.get("wrap")
    if not isinstance(wrap, str) or not wrap.startswith("w") or not wrap[1:].isdigit():
        raise ValueError(f"{mesh_path}: malformed wrap")
    core = split_item.get("evaluation_core_z_half_open")
    if not (isinstance(core, list) and len(core) == 2):
        raise ValueError(f"{mesh_path}: missing evaluation core")
    return {
        "path": mesh_path,
        "uuid": split_item["uuid"],
        "role": split_item["role"],
        "reference_winding": int(wrap[1:]),
        "core": (float(core[0]), float(core[1])),
        "expected_blobs": None if contract_heldout is None else contract_heldout.get("blobs"),
    }


def _load_reference_points(root: Path, manifest: dict[str, Any], spec: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    mesh = spec["path"]
    expected = spec["expected_blobs"] or {}
    arrays = []
    for axis in ("x", "y", "z"):
        rel = f"{mesh}/{axis}.tif"
        p = _verified_file(root, manifest, rel, expected.get(axis))
        arrays.append(_read_2d_tif(p))
    meta_rel = f"{mesh}/meta.json"
    _verified_file(root, manifest, meta_rel, expected.get("meta"))
    x, y, z = arrays
    if x.shape != y.shape or x.shape != z.shape:
        raise ValueError(f"{mesh}: x/y/z shapes differ")
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z) & (z > 0)
    lo, hi = spec["core"]
    eligible = valid & (z >= lo) & (z < hi)
    flat = np.flatnonzero(eligible.ravel(order="C"))
    n = int(flat.size)
    if n == 0:
        raise ValueError(f"{mesh}: no eligible reference vertices in frozen core")
    k = min(n, MAX_POINTS)
    ranks = _midpoint_ranks(n, MAX_POINTS)
    chosen = flat[ranks]
    rows, cols = np.unravel_index(chosen, z.shape, order="C")
    pts = np.column_stack((x.ravel()[chosen], y.ravel()[chosen], z.ravel()[chosen]))
    ids = [f"{spec['uuid']}:r{int(r)}:c{int(c)}" for r, c in zip(rows, cols)]
    return pts, ids


def _load_predictions(path: Path) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    with np.load(path, allow_pickle=False) as archive:
        for key in archive.files:
            if not (key.startswith("w") and key[1:].isdigit()):
                raise ValueError(f"NPZ key {key!r} is not wNNN")
            winding = int(key[1:])
            arr = np.asarray(archive[key])
            if arr.ndim != 3 or arr.shape[0] != 3:
                raise ValueError(f"NPZ {key} must have shape (3,H,W)")
            arr = np.asarray(arr, dtype=np.float64)
            positive = np.all(arr > 0, axis=0)
            if np.any(positive & ~np.all(np.isfinite(arr), axis=0)):
                raise ValueError(f"NPZ {key} contains non-finite positive prediction coordinates")
            out[winding] = arr
    if not out:
        raise ValueError("NPZ contains no winding arrays")
    return out


def _triangles(grid: np.ndarray, core: tuple[float, float]) -> np.ndarray:
    finite = np.all(np.isfinite(grid), axis=0)
    valid = finite & np.all(grid > 0, axis=0)
    v00 = np.moveaxis(grid[:, :-1, :-1], 0, -1)
    v01 = np.moveaxis(grid[:, :-1, 1:], 0, -1)
    v10 = np.moveaxis(grid[:, 1:, :-1], 0, -1)
    v11 = np.moveaxis(grid[:, 1:, 1:], 0, -1)
    q = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    if not np.any(q):
        return np.empty((0, 3, 3), dtype=np.float64)
    a = np.stack((v00[q], v01[q], v11[q]), axis=1)
    b = np.stack((v00[q], v11[q], v10[q]), axis=1)
    tri = np.concatenate((a, b), axis=0)
    lo, hi = core
    zmin = tri[:, :, 2].min(axis=1)
    zmax = tri[:, :, 2].max(axis=1)
    return tri[(zmax >= lo - MARGIN) & (zmin < hi + MARGIN)]


def _point_triangle_distance(point: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Vectorized exact point-to-triangle distance (Ericson region tests)."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    ab, ac = b - a, c - a
    ap = point - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    out = np.full(len(tri), np.nan, dtype=np.float64)
    done = (d1 <= 0) & (d2 <= 0)
    out[done] = np.linalg.norm(ap[done], axis=1)

    bp = point - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    m = (~done) & (d3 >= 0) & (d4 <= d3)
    out[m] = np.linalg.norm(bp[m], axis=1); done |= m

    vc = d1 * d4 - d3 * d2
    m = (~done) & (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    if np.any(m):
        v = d1[m] / (d1[m] - d3[m])
        out[m] = np.linalg.norm(ap[m] - v[:, None] * ab[m], axis=1)
    done |= m

    cp = point - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    m = (~done) & (d6 >= 0) & (d5 <= d6)
    out[m] = np.linalg.norm(cp[m], axis=1); done |= m

    vb = d5 * d2 - d1 * d6
    m = (~done) & (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    if np.any(m):
        w = d2[m] / (d2[m] - d6[m])
        out[m] = np.linalg.norm(ap[m] - w[:, None] * ac[m], axis=1)
    done |= m

    va = d3 * d6 - d5 * d4
    m = (~done) & (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    if np.any(m):
        bc = c[m] - b[m]
        w = (d4[m] - d3[m]) / ((d4[m] - d3[m]) + (d5[m] - d6[m]))
        out[m] = np.linalg.norm(bp[m] - w[:, None] * bc, axis=1)
    done |= m

    m = ~done
    if np.any(m):
        denom = va[m] + vb[m] + vc[m]
        good = np.abs(denom) > np.finfo(np.float64).eps
        idx = np.flatnonzero(m)
        if np.any(good):
            v = vb[m][good] / denom[good]
            w = vc[m][good] / denom[good]
            q = a[m][good] + ab[m][good] * v[:, None] + ac[m][good] * w[:, None]
            out[idx[good]] = np.linalg.norm(point - q, axis=1)
        if np.any(~good):
            # Degenerate triangles: exact minimum over the three segments.
            bad = idx[~good]
            vals = []
            for u, vtx in ((a[bad], b[bad]), (b[bad], c[bad]), (c[bad], a[bad])):
                edge = vtx - u
                den = np.einsum("ij,ij->i", edge, edge)
                t = np.divide(np.einsum("ij,ij->i", point - u, edge), den, out=np.zeros_like(den), where=den > 0)
                t = np.clip(t, 0.0, 1.0)
                vals.append(np.linalg.norm(point - (u + t[:, None] * edge), axis=1))
            out[bad] = np.min(np.stack(vals), axis=0)
    return out


class TriangleSurface:
    def __init__(self, triangles: np.ndarray):
        self.triangles = np.asarray(triangles, dtype=np.float64)
        if len(self.triangles):
            self.centroids = self.triangles.mean(axis=1)
            self.radii = np.linalg.norm(self.triangles - self.centroids[:, None, :], axis=2).max(axis=1)
            self.max_radius = float(self.radii.max())
            self.tree = cKDTree(self.centroids)
        else:
            self.centroids = np.empty((0, 3))
            self.radii = np.empty(0)
            self.max_radius = 0.0
            self.tree = None

    def distances(self, points: np.ndarray) -> np.ndarray:
        result = np.full(len(points), np.nan, dtype=np.float64)
        if self.tree is None:
            return result
        for i, point in enumerate(points):
            _, seed = self.tree.query(point, k=1)
            best = float(_point_triangle_distance(point, self.triangles[np.array([seed])])[0])
            ids = self.tree.query_ball_point(point, r=best + self.max_radius)
            cand = np.asarray(ids, dtype=np.int64)
            # Bounding-sphere lower bound makes this pruning exact.
            center_d = np.linalg.norm(self.centroids[cand] - point, axis=1)
            cand = cand[(center_d - self.radii[cand]) <= best]
            if cand.size:
                best = min(best, float(np.nanmin(_point_triangle_distance(point, self.triangles[cand]))))
            result[i] = best
        return result


def _surface(predictions: dict[int, np.ndarray], winding: int, core: tuple[float, float], cache: dict[tuple[int, float, float], TriangleSurface]) -> TriangleSurface | None:
    if winding not in predictions:
        return None
    key = (winding, core[0], core[1])
    if key not in cache:
        cache[key] = TriangleSurface(_triangles(predictions[winding], core))
    return cache[key]


def _finite_quantile(values: np.ndarray, q: float) -> float | None:
    a = values[np.isfinite(values)]
    return None if not a.size else float(np.quantile(a, q))


def _held_metrics(per_delta: dict[int, np.ndarray]) -> dict[str, Any]:
    expected = np.asarray(per_delta[0], dtype=np.float64)
    n = len(expected)
    if n == 0 or any(len(np.asarray(per_delta[d])) != n for d in (-2, -1, 0, 1, 2)):
        raise ValueError("held-out neighbor arrays must have the same nonzero sample count")
    finite_expected = np.isfinite(expected)
    counts = {str(d): 0 for d in (-2, -1, 0, 1, 2)}
    expected_nearest = 0
    classifiable = 0
    for i in range(n):
        choices = [(float(per_delta[d][i]), d) for d in (-2, -1, 0, 1, 2) if np.isfinite(per_delta[d][i])]
        if not choices:
            continue
        _, winner = min(choices, key=lambda x: (x[0], abs(x[1]), x[1]))
        counts[str(winner)] += 1
        classifiable += 1
        expected_nearest += int(winner == 0)
    return {
        "sample_count": n,
        "expected_winding_median_distance_voxels": _finite_quantile(expected, 0.5),
        "expected_winding_p95_distance_voxels": _finite_quantile(expected, 0.95),
        "expected_winding_p99_distance_voxels": _finite_quantile(expected, 0.99),
        "fraction_distance_le_5_voxels": float(np.count_nonzero(finite_expected & (expected <= 5.0)) / n),
        "fraction_distance_le_10_voxels": float(np.count_nonzero(finite_expected & (expected <= 10.0)) / n),
        "expected_winding_nearest_fraction_among_plus_minus_2": float(expected_nearest / n),
        "nearest_winding_delta_counts": counts,
        "neighbor_classifiable_samples": classifiable,
        "missing_or_unscorable_samples": int(n - np.count_nonzero(finite_expected)),
    }


def evaluate(
    *, contract_path: Path, split_path: Path, reference_root: Path,
    reference_blob_manifest: Path, predictions_npz: Path, volume_id: str,
) -> dict[str, Any]:
    if volume_id != EXPECTED_VOLUME_ID:
        raise ValueError(f"exact-volume mismatch: expected {EXPECTED_VOLUME_ID}, got {volume_id}")
    contract, split = _verify_frozen_documents(contract_path, split_path)
    manifest = _load_json(reference_blob_manifest)
    if manifest.get("repository") != EXPECTED_REFERENCE_REPOSITORY or manifest.get("commit") != EXPECTED_REFERENCE_COMMIT:
        raise ValueError("reference blob manifest repository/commit mismatch")
    predictions = _load_predictions(predictions_npz)
    by_path = _candidate_by_path(split)
    held_contract = {x["path"]: x for x in contract["held_out_meshes"]}
    specs = []
    for path, item in by_path.items():
        role = item.get("role")
        if role not in ("fit", "held_out"):
            raise ValueError(f"{path}: invalid role")
        hc = held_contract.get(path)
        if role == "held_out" and hc is None:
            raise ValueError(f"{path}: held-out candidate absent from preregistration")
        specs.append(_reference_spec(path, item, hc))
    if sum(s["role"] == "held_out" for s in specs) != 6:
        raise ValueError("frozen split must contain exactly six held-out meshes")

    refs = {}
    for spec in specs:
        refs[spec["path"]] = _load_reference_points(reference_root, manifest, spec)
    cache: dict[tuple[int, float, float], TriangleSurface] = {}

    fit = [s for s in specs if s["role"] == "fit"]
    offset_rows = []
    for offset in contract["winding_index_alignment"]["candidate_offsets"]:
        medians = []
        eligible = True
        for spec in fit:
            winding = spec["reference_winding"] + int(offset)
            surf = _surface(predictions, winding, spec["core"], cache)
            if surf is None or not len(surf.triangles):
                eligible = False
                break
            distances = surf.distances(refs[spec["path"]][0])
            if not np.all(np.isfinite(distances)):
                eligible = False
                break
            medians.append(float(np.median(distances)))
        score = float(np.median(medians)) if eligible else None
        offset_rows.append({"offset": int(offset), "eligible": eligible, "fit_mesh_median_of_medians": score})
    selected = _choose_offset(offset_rows)
    offset = int(selected["offset"])

    held_results = []
    for spec in [s for s in specs if s["role"] == "held_out"]:
        points, ids = refs[spec["path"]]
        per_delta: dict[int, np.ndarray] = {}
        for delta in (-2, -1, 0, 1, 2):
            winding = spec["reference_winding"] + offset + delta
            surf = _surface(predictions, winding, spec["core"], cache)
            per_delta[delta] = np.full(len(points), np.nan) if surf is None else surf.distances(points)
        metrics = _held_metrics(per_delta)
        held_results.append({
            "mesh": spec["path"],
            "reference_winding": spec["reference_winding"],
            "aligned_expected_prediction_winding": spec["reference_winding"] + offset,
            **metrics,
            "target_id_sha256": hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest(),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "volume_id": EXPECTED_VOLUME_ID,
        "selection_contract": {
            "geometry_only": True,
            "ink_inputs_consumed": False,
            "held_out_used_for_alignment": False,
            "sampling": "frozen row-major midpoint-rank; no RNG",
        },
        "provenance": {
            "reference_repository": EXPECTED_REFERENCE_REPOSITORY,
            "reference_commit": EXPECTED_REFERENCE_COMMIT,
            "contract_git_blob_sha1": EXPECTED_CONTRACT_BLOB,
            "split_git_blob_sha1": EXPECTED_SPLIT_BLOB,
            "predictions_sha256": hashlib.sha256(predictions_npz.read_bytes()).hexdigest(),
            "reference_blob_manifest_sha256": hashlib.sha256(reference_blob_manifest.read_bytes()).hexdigest(),
        },
        "winding_index_alignment": {
            "selected_offset": offset,
            "selected_fit_median_of_medians": selected["fit_mesh_median_of_medians"],
            "candidates": offset_rows,
        },
        "held_out_meshes": held_results,
        "limitations": [
            "Reference atlas meshes are approximate surfaces, not voxel-accurate labels.",
            "This report measures geometry transfer only; it makes no ink, readability, topology, or Grand Prize readiness claim.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate frozen PHerc0800 Spiral transfer without held-out tuning")
    ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--split", required=True, type=Path)
    ap.add_argument("--reference-root", required=True, type=Path)
    ap.add_argument("--reference-blob-manifest", required=True, type=Path)
    ap.add_argument("--predictions", required=True, type=Path)
    ap.add_argument("--volume-id", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite existing report: {args.out}")
    report = evaluate(
        contract_path=args.contract, split_path=args.split,
        reference_root=args.reference_root, reference_blob_manifest=args.reference_blob_manifest,
        predictions_npz=args.predictions, volume_id=args.volume_id,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"PHerc0800 transfer: selected fit-only winding offset {report['winding_index_alignment']['selected_offset']}; scored 6 held-out meshes")


if __name__ == "__main__":
    main()
