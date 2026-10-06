"""Crop-coordinate invariance gate for frozen dense-embedding fixtures.

Dense self-supervised features (DINO-style, including volumetric ones) can
carry the *position of a voxel inside its crop*. A cosine-similarity field
then looks spatially coherent partly because two voxels occupy analogous
positions in their crops, not because they depict analogous structure. INSID3
(Apache-2.0, CVPR 2026) reports such a positional bias in 2-D DINOv3 and a
training-free correction. That transfer to 3-D Vesuvius CT is unmeasured here;
this module is the audit that measures it on a fixture, and does not import
INSID3, DINOv3 or any weights.

Input: embeddings of the *same physical voxels* extracted under several
deliberately shifted crop frames (``embeddings`` C x N x D, ``crop_origin``
C x 3, ``points_xyz`` N x 3, ``labels``, ``split``). Points are labelled
sheet / neighbor_sheet / fiber / void / ink / negative, and split into
``calibration`` (used only to fit the debiasing transform) and ``evaluation``.

Per variant (raw, debiased) on evaluation points only:

- ``position_r2``: held-out fraction of the *within-point* (across-crop)
  embedding variance explained by crop-relative coordinates (degree-3
  polynomial, ridge, fitted on calibration points);
- ``frame_variance_fraction``: within-point variance over total variance;
- ``same_voxel_cosine``: cosine of one voxel's embedding across crop pairs;
- ``nn_stability``: fraction of voxels whose nearest neighbour identity is
  unchanged between crop pairs;
- ``sheet_vs_neighbor_auroc`` / ``ink_vs_negative_auroc``: within-crop AUROC
  of same-class vs cross-class cosine, i.e. the physical discrimination.

The debiasing transform subtracts the calibration-fitted crop-position
component. A frozen rule decides. Smoother similarity maps never count: a
transform is promoted only if position dependence falls, same-voxel agreement
and neighbour stability do not fall, and both physical separations stay within
tolerance. Raw separations near chance make the result ``unverified`` (there
is no discrimination to preserve). Missing embeddings report
``unavailable_input``, which is not ``failed``.

Scope: only polynomial position dependence is probed. Frame dependence the
polynomial does not explain is reported as ``FRAME_DEPENDENCE_UNEXPLAINED``,
not as absence of bias. Evidence about one fixture; never ink or surface
evidence by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

SCHEMA_VERSION = 1
TOOL = "scroliq-crop-invariance"
CLASSES = ("sheet", "neighbor_sheet", "fiber", "void", "ink", "negative")
RULE = {
    "poly_degree": 3,
    "ridge": 1e-6,
    "min_points_per_class": 10,
    "min_crops": 3,
    "min_raw_auroc": 0.60,        # below this there is no discrimination to keep
    "r2_present": 0.10,           # raw held-out position R^2 that counts as dependence
    "frame_fraction_present": 0.10,
    "r2_resid_abs": 0.05,         # debiased R^2 must be <= this ...
    "r2_resid_rel": 0.25,         # ... and <= this fraction of the raw R^2
    "auroc_tolerance": 0.02,      # allowed drop in either separation
}
ARRAYS = ("embeddings", "crop_origin", "points_xyz", "labels", "split")


class InvarianceError(ValueError):
    pass


# ---------------------------------------------------------------- numerics
def _unit(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.where(n == 0, 1.0, n)


def _poly(rel: np.ndarray, degree: int) -> np.ndarray:
    cols = []
    for d in range(1, degree + 1):
        for combo in itertools.combinations_with_replacement(range(3), d):
            c = np.ones(rel.shape[:-1])
            for k in combo:
                c = c * rel[..., k]
            cols.append(c)
    return np.stack(cols, axis=-1)


def _rankdata(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    flag = np.r_[True, xs[1:] != xs[:-1]]
    grp = np.cumsum(flag) - 1
    starts = np.flatnonzero(flag)
    ends = np.r_[starts[1:], len(x)]
    ranks = np.empty(len(x))
    ranks[order] = ((starts + ends + 1) / 2.0)[grp]
    return ranks


def _auroc(pos: np.ndarray, neg: np.ndarray) -> float:
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    r = _rankdata(np.concatenate([pos, neg]))
    u = r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2.0
    return float(u / (len(pos) * len(neg)))


def _centered(a: np.ndarray) -> np.ndarray:
    return a - a.mean(axis=0, keepdims=True)


def _fit_position(emb: np.ndarray, phi: np.ndarray, rule: dict) -> np.ndarray:
    """Ridge map from within-point-centred position features to embedding."""
    x = _centered(phi).reshape(-1, phi.shape[-1])
    y = _centered(emb).reshape(-1, emb.shape[-1])
    gram = x.T @ x + rule["ridge"] * np.eye(x.shape[1])
    return np.linalg.solve(gram, x.T @ y)


def _position_r2(w: np.ndarray, emb: np.ndarray, phi: np.ndarray) -> float:
    y = _centered(emb).reshape(-1, emb.shape[-1])
    x = _centered(phi).reshape(-1, phi.shape[-1])
    sst = float((y ** 2).sum())
    if sst <= 0:
        return 0.0
    return float(1.0 - ((y - x @ w) ** 2).sum() / sst)


def _pair_means(emb: np.ndarray) -> tuple[float, float]:
    """(same-voxel cosine, nn-identity stability) over crop pairs."""
    u = _unit(emb)
    c, n = u.shape[:2]
    cos, nn_same = [], []
    nns = []
    for a in range(c):
        s = u[a] @ u[a].T
        np.fill_diagonal(s, -np.inf)
        nns.append(s.argmax(axis=1))
    for a, b in itertools.combinations(range(c), 2):
        cos.append(float((u[a] * u[b]).sum(axis=1).mean()))
        nn_same.append(float((nns[a] == nns[b]).mean()))
    return float(np.mean(cos)), float(np.mean(nn_same))


def _separation(emb: np.ndarray, labels: np.ndarray, a: str, b: str) -> float:
    u = _unit(emb)
    ia, ib = np.flatnonzero(labels == a), np.flatnonzero(labels == b)
    scores = []
    for k in range(u.shape[0]):
        same = u[k][ia] @ u[k][ia].T
        same = same[np.triu_indices(len(ia), 1)]
        cross = (u[k][ia] @ u[k][ib].T).ravel()
        scores.append(_auroc(same, cross))
    return float(np.mean(scores))


def _metrics(emb, phi, labels, cal, ev, rule) -> dict:
    w = _fit_position(emb[:, cal], phi[:, cal], rule)
    e_ev, p_ev, l_ev = emb[:, ev], phi[:, ev], labels[ev]
    y = _centered(e_ev).reshape(-1, e_ev.shape[-1])
    total = e_ev.reshape(-1, e_ev.shape[-1])
    total = total - total.mean(axis=0, keepdims=True)
    cos, nn = _pair_means(e_ev)
    out = {
        "position_r2": _position_r2(w, e_ev, p_ev),
        "frame_variance_fraction": float((y ** 2).sum() / max((total ** 2).sum(), 1e-300)),
        "same_voxel_cosine": cos,
        "nn_stability": nn,
        "sheet_vs_neighbor_auroc": _separation(e_ev, l_ev, "sheet", "neighbor_sheet"),
        "ink_vs_negative_auroc": _separation(e_ev, l_ev, "ink", "negative"),
        "per_class": {},
    }
    for cls in CLASSES:
        idx = np.flatnonzero(l_ev == cls)
        out["per_class"][cls] = {
            "n_eval_points": int(len(idx)),
            "same_voxel_cosine": _pair_means(e_ev[:, idx])[0],
        }
    return out


# ---------------------------------------------------------------- decision
def decide(raw: dict, deb: dict, rule: dict = RULE) -> dict:
    """Frozen rule over the raw and debiased metric blocks."""
    tol = rule["auroc_tolerance"]
    weak = [k for k in ("sheet_vs_neighbor_auroc", "ink_vs_negative_auroc")
            if not raw[k] >= rule["min_raw_auroc"]]
    if weak:
        return {"status": "unverified", "verdict": None,
                "reason": f"raw {', '.join(weak)} below {rule['min_raw_auroc']}: "
                          "no physical discrimination to preserve"}
    positional = raw["position_r2"] >= rule["r2_present"]
    if not positional:
        if raw["frame_variance_fraction"] >= rule["frame_fraction_present"]:
            return {"status": "measured", "verdict": "FRAME_DEPENDENCE_UNEXPLAINED",
                    "reason": "embeddings vary across crop frames but not as a "
                              "polynomial of crop-relative position; neither "
                              "bias nor invariance is established"}
        return {"status": "measured", "verdict": "NO_POSITIONAL_DEPENDENCE_DETECTED",
                "reason": "within the polynomial position family; INSID3-style "
                          "debiasing has nothing to correct on this fixture"}
    checks = {
        "residual_position_r2": deb["position_r2"] <= min(
            rule["r2_resid_abs"], rule["r2_resid_rel"] * raw["position_r2"]),
        "same_voxel_cosine_not_lower": deb["same_voxel_cosine"] >= raw["same_voxel_cosine"],
        "nn_stability_not_lower": deb["nn_stability"] >= raw["nn_stability"],
        "sheet_vs_neighbor_kept": raw["sheet_vs_neighbor_auroc"]
        - deb["sheet_vs_neighbor_auroc"] <= tol,
        "ink_vs_negative_kept": raw["ink_vs_negative_auroc"]
        - deb["ink_vs_negative_auroc"] <= tol,
    }
    failed = [k for k, ok in checks.items() if not ok]
    return {"status": "measured",
            "verdict": ("POSITIONAL_DEPENDENCE_DEBIAS_PROMOTED" if not failed
                        else "POSITIONAL_DEPENDENCE_DEBIAS_REJECTED"),
            "checks": checks, "failed_checks": failed}


def evaluate(arrays: dict, crop_shape: Sequence[float], rule: dict = RULE) -> dict:
    try:
        emb = np.asarray(arrays["embeddings"], dtype=np.float64)
        origin = np.asarray(arrays["crop_origin"], dtype=np.float64)
        pts = np.asarray(arrays["points_xyz"], dtype=np.float64)
        labels = np.asarray(arrays["labels"]).astype(str)
        split = np.asarray(arrays["split"]).astype(str)
    except KeyError as exc:
        raise InvarianceError(f"missing array {exc}") from None
    shape = np.asarray(crop_shape, dtype=np.float64)
    if emb.ndim != 3 or origin.shape != (emb.shape[0], 3) \
            or pts.shape != (emb.shape[1], 3) or shape.shape != (3,) \
            or labels.shape != (emb.shape[1],) or split.shape != (emb.shape[1],):
        raise InvarianceError("array shapes are inconsistent")
    if not np.isfinite(emb).all() or not np.isfinite(pts).all() \
            or not np.isfinite(origin).all():
        raise InvarianceError("non-finite values in fixture")
    if not set(split) <= {"calibration", "evaluation"}:
        raise InvarianceError("split must be calibration / evaluation")
    unknown = set(labels) - set(CLASSES)
    if unknown:
        raise InvarianceError(f"unknown labels {sorted(unknown)}")
    rel = pts[None] - origin[:, None]
    if (rel < 0).any() or (rel >= shape).any():
        raise InvarianceError("a point lies outside one of its crops; the same "
                              "physical voxel must be present in every frame")
    base = {"schema_version": SCHEMA_VERSION, "tool": TOOL, "rule": dict(rule),
            "n_crops": int(emb.shape[0]), "n_points": int(emb.shape[1]),
            "scope": ("one frozen fixture; polynomial crop-position family "
                      "only; not ink or surface evidence")}

    problems = []
    if emb.shape[0] < rule["min_crops"]:
        problems.append(f"need >= {rule['min_crops']} crop frames")
    if emb.shape[0] >= 2 and (rel.std(axis=0).max() <= 1e-9):
        problems.append("crop origins do not differ: invariance is untestable")
    for part in ("calibration", "evaluation"):
        for cls in CLASSES:
            n = int(((split == part) & (labels == cls)).sum())
            if n < rule["min_points_per_class"]:
                problems.append(f"{part} class {cls} has {n} points "
                                f"(< {rule['min_points_per_class']})")
    if problems:
        return {**base, "status": "unverified", "reason": "; ".join(problems)}

    cal, ev = np.flatnonzero(split == "calibration"), np.flatnonzero(split == "evaluation")
    phi = _poly(rel / shape - 0.5, rule["poly_degree"])
    w = _fit_position(emb[:, cal], phi[:, cal], rule)
    deb_emb = emb - (phi - phi[:, cal].mean(axis=(0, 1))) @ w
    raw = _metrics(emb, phi, labels, cal, ev, rule)
    deb = _metrics(deb_emb, phi, labels, cal, ev, rule)
    return {**base, "raw": raw, "debiased": deb, **decide(raw, deb, rule)}


# ---------------------------------------------------------------- controls
def synthetic_fixture(bias: float = 1.0, seed: int = 0, kind: str = "polynomial",
                      n: int = 160, d: int = 24) -> tuple[dict, tuple]:
    """Same voxels under shifted crops; ``bias`` scales the planted position term."""
    rng = np.random.default_rng(seed)
    shape = (64.0, 64.0, 64.0)
    origins = np.array([[0, 0, 0], [16, 0, 0], [0, 16, 0], [0, 0, 16],
                        [16, 16, 0], [8, 8, 8]], dtype=float)
    pts = rng.uniform(16, 63.9, size=(n, 3))
    per = n // len(CLASSES) + 1
    labels = np.array((list(CLASSES) * per)[:n])
    split = np.array(["calibration" if (i // len(CLASSES)) % 2 == 0 else "evaluation"
                      for i in range(n)])
    proto = {c: rng.normal(size=d) for c in CLASSES}
    ident = np.stack([proto[c] for c in labels]) + 0.4 * rng.normal(size=(n, d))
    rel = (pts[None] - origins[:, None]) / np.asarray(shape) - 0.5
    if kind == "polynomial":
        pos = _poly(rel, RULE["poly_degree"]) @ rng.normal(size=(19, d))
    elif kind == "highfreq":
        pos = np.sin(40.0 * rel @ rng.normal(size=(3, d)))
    else:
        raise InvarianceError(f"unknown kind {kind}")
    emb = ident[None] + bias * pos + 0.02 * rng.normal(size=(len(origins), n, d))
    return {"embeddings": emb, "crop_origin": origins, "points_xyz": pts,
            "labels": labels, "split": split}, shape


def positive_control() -> dict:
    biased = evaluate(*synthetic_fixture(bias=1.5))
    clean = evaluate(*synthetic_fixture(bias=0.0))
    highfreq = evaluate(*synthetic_fixture(bias=1.0, kind="highfreq"))
    same_frame = synthetic_fixture(bias=1.0)
    same_frame[0]["crop_origin"] = np.zeros_like(same_frame[0]["crop_origin"])
    # a point must still be inside every crop of the (now identical) frames
    untestable = evaluate(*same_frame)
    # a transform that deletes the signal is smoother and must still be rejected
    raw = biased["raw"]
    collapsed = dict(biased["debiased"], position_r2=0.0, same_voxel_cosine=1.0,
                     nn_stability=1.0, sheet_vs_neighbor_auroc=0.5,
                     ink_vs_negative_auroc=0.5)
    obs = {
        "planted_bias_detected_and_removed":
            biased["verdict"] == "POSITIONAL_DEPENDENCE_DEBIAS_PROMOTED",
        "clean_fixture_not_debiased":
            clean["verdict"] == "NO_POSITIONAL_DEPENDENCE_DETECTED",
        "nonpolynomial_frame_dependence_not_called_clean":
            highfreq["verdict"] != "NO_POSITIONAL_DEPENDENCE_DETECTED",
        "identical_frames_unverified": untestable["status"] == "unverified",
        "smoothing_collapse_rejected":
            decide(raw, collapsed)["verdict"] == "POSITIONAL_DEPENDENCE_DEBIAS_REJECTED",
    }
    return {"passed": all(obs.values()), "observed": obs}


# ---------------------------------------------------------------- CLI
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run_manifest(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise InvarianceError("manifest: schema_version must be 1")
    head = {"experiment_id": doc.get("experiment_id"),
            "embedding_source": doc.get("embedding_source")}
    ref = doc.get("arrays")
    if not ref:
        return {**head, "status": "unavailable_input",
                "reason": "manifest declares no embedding arrays; this gate "
                          "cannot currently be evaluated, which is not a failure"}
    arrays_path = (path.parent / ref).resolve()
    if not arrays_path.is_file():
        return {**head, "status": "unavailable_input",
                "reason": f"arrays file {ref!r} not found"}
    declared = doc.get("arrays_sha256")
    actual = _sha256(arrays_path)
    if declared != actual:
        raise InvarianceError("arrays_sha256 does not match the arrays file")
    with np.load(arrays_path, allow_pickle=False) as npz:
        arrays = {k: npz[k] for k in ARRAYS if k in npz.files}
    return {**head, "arrays_sha256": actual,
            **evaluate(arrays, doc.get("crop_shape") or [])}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=TOOL, description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", help="fixture manifest JSON (see docs/crop-invariance.md)")
    ap.add_argument("--out", help="create-only result JSON path")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        ctl = positive_control()
        print(json.dumps(ctl, indent=1))
        return 0 if ctl["passed"] else 2
    if not args.manifest:
        ap.print_help()
        return 0
    try:
        result = run_manifest(Path(args.manifest))
    except (InvarianceError, OSError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=1, sort_keys=True, default=float) + "\n"
    if args.out:
        with open(args.out, "x", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    print(f"{result['status']}: {result.get('verdict') or result.get('reason')}",
          file=sys.stderr)
    return 0 if result["status"] == "measured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
