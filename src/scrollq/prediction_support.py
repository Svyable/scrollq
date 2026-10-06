"""Prediction-volume physical-support preflight, run before any tracer.

``scroliq-support`` estimates *how much* of a released surface prediction is
phantom by sampling chunks. This module is the per-voxel invariant that must
hold before a prediction is allowed to seed geometry (for example VC3D's
``vc_grow_seg_from_seed``): a prediction positive is only seed-eligible when
the masked CT voxel it sits on was physically measured.

For one region of one exact voxel grid it reports:

- ``pred_positive`` = prediction > ``threshold`` (127, as ``scroliq-support``);
- ``pred_positive ∩ ct_supported`` (masked CT != 0) and
  ``pred_positive ∩ ct_zero`` (masked CT == 0, the *phantom* positives);
- for phantoms, the Euclidean distance (voxels) to the nearest CT support;
- for every prediction chunk holding positives, whether the chunk itself holds
  CT support (``supported``), only a 26-neighbour chunk does (``halo``), no
  chunk within one chunk does (``beyond``), or that cannot be decided because
  part of the neighbourhood lies outside the audited region (``unresolved``);
- how many phantoms lie within ``blend_margin`` voxels of a prediction-chunk
  face, next to the fraction a uniform spread would put there.

The chunk and blend-boundary layout is preserved rather than cleaned away: a
halo concentrated in one chunk margin is diagnostic of *why* the phantom
exists (an inference blending margin), which a bare filter would erase.

The raw prediction is ``seed_safe`` only when it has positives and none of
them is phantom. Otherwise only ``pred_positive ∩ ct_supported`` may seed
(``supported_prediction``), and ``gate_seeds`` rejects any seed on zero CT.
An audit that saw no positives is ``unverified``, never clean, and every report
re-runs a built-in synthetic positive control (``positive_control``) whose
supported/halo/beyond counts are known; a failing control makes the report
``unverified``.

This is input-validity evidence about the prediction volume. It says nothing
about whether supported positives lie on the right sheet, or about ink.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from scipy.ndimage import distance_transform_edt

SCHEMA_VERSION = "scroliq-prediction-support-v1"
THRESHOLD = 127
DEFAULT_CHUNK = (192, 192, 192)  # released m7 surface predictions
DEFAULT_BLEND_MARGIN = 16
DISTANCE_BINS = (1, 2, 4, 8, 16, 32, 64, 128, 256)
SEED_POLICY = ("only pred_positive ∩ ct_supported (masked CT != 0) may seed "
               "geometry; positives on CT == 0 are never seeds")


class PredictionSupportError(ValueError):
    pass


def _triple(v, name: str) -> tuple[int, int, int]:
    t = tuple(int(x) for x in v)
    if len(t) != 3:
        raise PredictionSupportError(f"{name} must have 3 entries, got {v!r}")
    return t  # type: ignore[return-value]


def _check_pair(pred: np.ndarray, ct: np.ndarray) -> None:
    if pred.ndim != 3 or ct.ndim != 3:
        raise PredictionSupportError(
            f"expected 3-D arrays, got {pred.ndim}-D prediction and "
            f"{ct.ndim}-D CT")
    if pred.shape != ct.shape:
        raise PredictionSupportError(
            f"prediction region {pred.shape} != CT region {ct.shape}: "
            "not the same voxel grid")
    for name, a in (("prediction", pred), ("CT", ct)):
        if not np.issubdtype(a.dtype, np.integer):
            raise PredictionSupportError(
                f"{name} must be an integer array, got {a.dtype}")


def supported_prediction(pred: np.ndarray, ct: np.ndarray) -> np.ndarray:
    """The source filter: the prediction with every CT == 0 voxel zeroed."""
    _check_pair(pred, ct)
    return np.where(ct != 0, pred, 0).astype(pred.dtype, copy=False)


def gate_seeds(seeds_zyx: Iterable[Sequence[int]], ct: np.ndarray, *,
               origin: Sequence[int] = (0, 0, 0)) -> dict:
    """Accept a seed only when it sits on measured (non-zero) CT.

    Seeds are global voxel coordinates (z, y, x). A seed outside the audited
    region is ``unverified``, not accepted.
    """
    org = _triple(origin, "origin")
    rows = []
    for s in seeds_zyx:
        g = _triple(s, "seed")
        loc = tuple(g[d] - org[d] for d in range(3))
        if any(loc[d] < 0 or loc[d] >= ct.shape[d] for d in range(3)):
            rows.append({"seed_zyx": list(g), "status": "unverified",
                         "reason": "outside audited region"})
            continue
        v = int(ct[loc])
        rows.append({"seed_zyx": list(g), "ct_value": v,
                     "status": "accepted" if v != 0 else "rejected_ct_zero"})
    counts = {k: sum(r["status"] == k for r in rows)
              for k in ("accepted", "rejected_ct_zero", "unverified")}
    return {"policy": SEED_POLICY, "counts": counts, "seeds": rows}


def _distance_summary(dist: np.ndarray) -> dict:
    edges = (0,) + DISTANCE_BINS
    hist = []
    for lo, hi in zip(edges, edges[1:]):
        hist.append({"gt": lo, "le": hi,
                     "count": int(((dist > lo) & (dist <= hi)).sum())})
    hist.append({"gt": edges[-1], "le": None,
                 "count": int((dist > edges[-1]).sum())})
    return {
        "unit": "voxel",
        "min": round(float(dist.min()), 3),
        "median": round(float(np.median(dist)), 3),
        "p95": round(float(np.percentile(dist, 95)), 3),
        "max": round(float(dist.max()), 3),
        "histogram": hist,
    }


def _chunk_table(pos: np.ndarray, supp: np.ndarray, origin, chunk,
                 volume_shape) -> list[dict]:
    """Per prediction chunk overlapping the region: counts and observation."""
    shape = pos.shape
    lo_idx = [origin[d] // chunk[d] for d in range(3)]
    hi_idx = [(origin[d] + shape[d] - 1) // chunk[d] for d in range(3)]
    rows = []
    for idx in itertools.product(*(range(lo_idx[d], hi_idx[d] + 1)
                                   for d in range(3))):
        g0 = [idx[d] * chunk[d] for d in range(3)]
        g1 = [min(g0[d] + chunk[d], volume_shape[d]) for d in range(3)]
        l0 = [max(g0[d] - origin[d], 0) for d in range(3)]
        l1 = [min(g1[d] - origin[d], shape[d]) for d in range(3)]
        sl = tuple(slice(l0[d], l1[d]) for d in range(3))
        p, s = pos[sl], supp[sl]
        rows.append({
            "chunk": idx,
            "complete": all(l1[d] - l0[d] == g1[d] - g0[d] for d in range(3)),
            "positives": int(p.sum()),
            "phantom": int((p & ~s).sum()),
            "has_support": bool(s.any()),
        })
    return rows


def _classify_chunks(rows: list[dict], volume_shape, chunk) -> dict:
    by_idx = {r["chunk"]: r for r in rows}
    grid = [-(-volume_shape[d] // chunk[d]) for d in range(3)]
    out = {k: {"chunks": 0, "positives": 0, "phantom": 0}
           for k in ("supported", "halo", "beyond", "unresolved")}
    listed: dict[str, list] = {"halo": [], "beyond": [], "unresolved": []}
    for r in rows:
        if r["positives"] == 0:
            continue
        if r["has_support"]:
            cls = "supported"
        elif not r["complete"]:
            cls = "unresolved"  # unseen part of the chunk may hold support
        else:
            neigh_support = False
            neigh_unseen = False
            for off in itertools.product((-1, 0, 1), repeat=3):
                if off == (0, 0, 0):
                    continue
                n = tuple(r["chunk"][d] + off[d] for d in range(3))
                if any(n[d] < 0 or n[d] >= grid[d] for d in range(3)):
                    continue  # outside the volume: nothing to observe
                nr = by_idx.get(n)
                if nr is not None and nr["has_support"]:
                    neigh_support = True
                elif nr is None or not nr["complete"]:
                    neigh_unseen = True
            if neigh_support:
                cls = "halo"
            elif neigh_unseen:
                cls = "unresolved"
            else:
                cls = "beyond"
        o = out[cls]
        o["chunks"] += 1
        o["positives"] += r["positives"]
        o["phantom"] += r["phantom"]
        if cls in listed:
            listed[cls].append(list(r["chunk"]))
    total = sum(v["chunks"] for v in out.values())
    return {
        "definition": ("supported: chunk holds CT support; halo: only a "
                       "26-neighbour chunk does; beyond: no chunk within one "
                       "chunk does; unresolved: neighbourhood partly outside "
                       "the audited region"),
        "chunks_with_positives": total,
        "classes": out,
        "fractions": {k: (round(v["chunks"] / total, 4) if total else None)
                      for k, v in out.items()},
        "chunk_ids": {k: sorted(v) for k, v in listed.items()},
    }


def _blend_boundary(zero_pos: np.ndarray, origin, chunk, margin: int) -> dict:
    zz = np.nonzero(zero_pos)
    n = int(zz[0].size)
    expected = 1.0
    for d in range(3):
        expected *= max(chunk[d] - 2 * margin, 0) / chunk[d]
    expected = 1.0 - expected
    if n == 0:
        return {"margin_voxels": margin, "phantom": 0,
                "within_margin": 0, "observed_frac": None,
                "uniform_expected_frac": round(expected, 4),
                "enrichment": None}
    near = np.zeros(n, dtype=bool)
    for d in range(3):
        off = (zz[d] + origin[d]) % chunk[d]
        near |= np.minimum(off, chunk[d] - 1 - off) < margin
    within = int(near.sum())
    obs = within / n
    return {
        "margin_voxels": margin,
        "phantom": n,
        "within_margin": within,
        "observed_frac": round(obs, 4),
        "uniform_expected_frac": round(expected, 4),
        "enrichment": round(obs / expected, 3) if expected else None,
        "note": ("diagnostic only: enrichment above 1 points at a chunk "
                 "blending margin; it never changes the seed verdict"),
    }


def audit_arrays(pred: np.ndarray, ct: np.ndarray, *,
                 threshold: int = THRESHOLD,
                 chunk: Sequence[int] = DEFAULT_CHUNK,
                 origin: Sequence[int] = (0, 0, 0),
                 volume_shape: Sequence[int] | None = None,
                 blend_margin: int = DEFAULT_BLEND_MARGIN,
                 seeds: Iterable[Sequence[int]] | None = None,
                 run_control: bool = True) -> dict:
    """Support audit of one region; the arrays share one voxel grid.

    ``origin`` is the region's global (z, y, x) offset and ``volume_shape`` the
    full L0 shape (default: the region is the whole volume). Chunk classes are
    computed on the global prediction-chunk grid of size ``chunk``.
    """
    _check_pair(pred, ct)
    chunk = _triple(chunk, "chunk")
    origin = _triple(origin, "origin")
    vshape = _triple(volume_shape if volume_shape is not None else
                     tuple(origin[d] + pred.shape[d] for d in range(3)),
                     "volume_shape")
    if any(c <= 0 for c in chunk) or any(o < 0 for o in origin):
        raise PredictionSupportError("chunk must be positive, origin >= 0")
    if any(origin[d] + pred.shape[d] > vshape[d] for d in range(3)):
        raise PredictionSupportError("region extends past volume_shape")
    if blend_margin < 0:
        raise PredictionSupportError("blend_margin must be >= 0")

    pos = pred > threshold
    supp = ct != 0
    zero_pos = pos & ~supp
    n_pos = int(pos.sum())
    n_zero = int(zero_pos.sum())
    n_sup = n_pos - n_zero

    if n_zero == 0:
        distance = None
    elif not supp.any():
        distance = {"unit": "voxel", "no_ct_support_in_region": True}
    else:
        d = distance_transform_edt(~supp)[zero_pos]
        distance = _distance_summary(d)
        if (origin != (0, 0, 0)) or tuple(vshape) != pred.shape:
            distance["bound"] = ("upper: support outside the audited region "
                                 "may be closer")

    rows = _chunk_table(pos, supp, origin, chunk, vshape)
    control = positive_control() if run_control else None

    if control is not None and not control["passed"]:
        status, reason = "unverified", "built-in positive control failed"
    elif n_pos == 0:
        status, reason = "unverified", "no prediction positives inspected"
    elif n_zero == 0:
        status, reason = "seed_safe", "every positive sits on measured CT"
    else:
        status = "requires_support_filter"
        reason = (f"{n_zero} of {n_pos} positives sit on CT == 0 and must "
                  "not seed geometry")

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "raw_prediction_seed_safe": status == "seed_safe",
        "seed_policy": SEED_POLICY,
        "threshold": threshold,
        "region": {"origin_zyx": list(origin), "shape_zyx": list(pred.shape),
                   "volume_shape_zyx": list(vshape),
                   "prediction_chunk_zyx": list(chunk)},
        "counts": {
            "pred_positive": n_pos,
            "pred_positive_ct_supported": n_sup,
            "pred_positive_ct_zero": n_zero,
            "ct_supported_voxels": int(supp.sum()),
            "region_voxels": int(pred.size),
        },
        "fractions": {
            "supported": round(n_sup / n_pos, 6) if n_pos else None,
            "phantom": round(n_zero / n_pos, 6) if n_pos else None,
        },
        "phantom_distance_to_ct_support": distance,
        "chunk_classes": _classify_chunks(rows, vshape, chunk),
        "blend_boundary": _blend_boundary(zero_pos, origin, chunk,
                                          blend_margin),
        "positive_control": control,
        "scope": ("input-validity evidence for the prediction volume only; "
                  "not surface, sheet-identity, readability or ink evidence"),
    }
    if seeds is not None:
        report["seed_gate"] = gate_seeds(seeds, ct, origin=origin)
    return report


def positive_control() -> dict:
    """Synthetic volume with known supported / halo / beyond phantoms.

    32^3 voxels, 8^3 prediction chunks. CT is measured for z < 12. Prediction
    planes sit at z = 10 (supported), 13 (phantom inside a supported chunk),
    20 (halo chunk) and 30 (beyond: two chunks from any support).
    """
    pred = np.zeros((32, 32, 32), dtype=np.uint8)
    ct = np.zeros_like(pred)
    ct[:12] = 90
    for z in (10, 13, 20, 30):
        pred[z] = 255
    r = audit_arrays(pred, ct, chunk=(8, 8, 8), blend_margin=1,
                     run_control=False)
    plane = 32 * 32
    cls = r["chunk_classes"]["classes"]
    dist = r["phantom_distance_to_ct_support"] or {}
    expect = {
        "pred_positive": 4 * plane,
        "pred_positive_ct_supported": plane,
        "pred_positive_ct_zero": 3 * plane,
        "supported_chunks": 16,
        "halo_chunks": 16,
        "beyond_chunks": 16,
        "unresolved_chunks": 0,
        "phantom_distance_min": 2.0,
        "phantom_distance_max": 19.0,
        "status": "requires_support_filter",
    }
    got = {
        "pred_positive": r["counts"]["pred_positive"],
        "pred_positive_ct_supported": r["counts"]["pred_positive_ct_supported"],
        "pred_positive_ct_zero": r["counts"]["pred_positive_ct_zero"],
        "supported_chunks": cls["supported"]["chunks"],
        "halo_chunks": cls["halo"]["chunks"],
        "beyond_chunks": cls["beyond"]["chunks"],
        "unresolved_chunks": cls["unresolved"]["chunks"],
        "phantom_distance_min": dist.get("min"),
        "phantom_distance_max": dist.get("max"),
        "status": r["status"],
    }
    filtered = supported_prediction(pred, ct)
    got["filtered_phantom"] = int(((filtered > THRESHOLD) & (ct == 0)).sum())
    expect["filtered_phantom"] = 0
    return {"passed": got == expect, "expected": expect, "observed": got}


# --------------------------------------------------------------------- inputs


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _parse_box(text: str) -> tuple[tuple[int, int], ...]:
    parts = text.split(",")
    if len(parts) != 3:
        raise PredictionSupportError("--box must be z0:z1,y0:y1,x0:x1")
    box = []
    for p in parts:
        a, b = (int(v) for v in p.split(":"))
        if not 0 <= a < b:
            raise PredictionSupportError(f"empty or negative box range {p}")
        box.append((a, b))
    return tuple(box)


def read_box(level, box) -> np.ndarray:
    """Assemble a box from a chunked level; unstored chunks read as zero.

    ``level`` has ``shape``, ``chunks`` and ``chunk(idx) -> array | None``
    (``scrollq.support.ZarrV2Level``). An unstored CT chunk is masked
    background, so zero is the correct value: it is *unsupported*, and
    positives over it count as phantom.
    """
    if any(box[d][1] > level.shape[d] for d in range(3)):
        raise PredictionSupportError(
            f"box {box} extends past level shape {level.shape}")
    out = np.zeros(tuple(b - a for a, b in box), dtype=np.uint8)
    c = level.chunks
    ranges = [range(box[d][0] // c[d], (box[d][1] - 1) // c[d] + 1)
              for d in range(3)]
    for idx in itertools.product(*ranges):
        data = level.chunk(idx)
        if data is None:
            continue
        g0 = [idx[d] * c[d] for d in range(3)]
        lo = [max(box[d][0], g0[d]) for d in range(3)]
        hi = [min(box[d][1], g0[d] + data.shape[d]) for d in range(3)]
        src = tuple(slice(lo[d] - g0[d], hi[d] - g0[d]) for d in range(3))
        dst = tuple(slice(lo[d] - box[d][0], hi[d] - box[d][0])
                    for d in range(3))
        out[dst] = data[src]
    return out


def _load_seeds(path: str) -> list[list[int]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seeds = data.get("seeds_zyx") if isinstance(data, dict) else data
    if not isinstance(seeds, list):
        raise PredictionSupportError(
            "seeds file must be a list of [z, y, x] or {\"seeds_zyx\": [...]}")
    return [list(s) for s in seeds]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="scroliq-prediction-support",
        description=__doc__.splitlines()[0])
    src = ap.add_argument_group("local region (.npy, same grid)")
    src.add_argument("--pred", help="prediction region .npy")
    src.add_argument("--ct", help="masked CT region .npy")
    src.add_argument("--origin", default="0,0,0",
                     help="global z,y,x of the region's first voxel")
    src.add_argument("--volume-shape",
                     help="full L0 z,y,x (default: region is the volume)")
    rem = ap.add_argument_group("remote zarr v2 L0 levels")
    rem.add_argument("--pred-url", help="prediction zarr level URL (…/0)")
    rem.add_argument("--ct-url", help="masked CT zarr level URL (…/0)")
    rem.add_argument("--box", help="z0:z1,y0:y1,x0:x1 global voxel box")
    ap.add_argument("--chunk", help="prediction chunk z,y,x "
                    "(default: the prediction level's chunks, else 192^3)")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--blend-margin", type=int, default=DEFAULT_BLEND_MARGIN)
    ap.add_argument("--seeds", help="JSON seeds [[z,y,x], …] to gate")
    ap.add_argument("--write-filtered",
                    help="write pred ∩ ct_supported as .npy (local mode)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 2 unless the raw prediction is seed_safe")
    ap.add_argument("--self-test", action="store_true",
                    help="run only the built-in positive control")
    ap.add_argument("--out", help="write the JSON report here")
    args = ap.parse_args(argv)

    if args.self_test:
        ctl = positive_control()
        print(json.dumps(ctl, indent=1))
        return 0 if ctl["passed"] else 2

    def parse3(s):
        return _triple(s.split(","), "triple") if s else None

    sources: dict = {}
    origin = parse3(args.origin)
    vshape = parse3(args.volume_shape)
    chunk = parse3(args.chunk)
    try:
        if args.pred and args.ct:
            pred = np.load(args.pred, allow_pickle=False)
            ct = np.load(args.ct, allow_pickle=False)
            sources = {"mode": "local",
                       "prediction": {"path": args.pred,
                                      "sha256": _sha256(Path(args.pred))},
                       "ct": {"path": args.ct,
                              "sha256": _sha256(Path(args.ct))}}
        elif args.pred_url and args.ct_url and args.box:
            import requests

            from .support import ZarrV2Level

            sess = requests.Session()
            pl = ZarrV2Level(args.pred_url, sess)
            cl = ZarrV2Level(args.ct_url, sess)
            if pl.shape != cl.shape:
                raise PredictionSupportError(
                    f"prediction shape {pl.shape} != CT shape {cl.shape}: "
                    "not the same voxel grid")
            box = _parse_box(args.box)
            pred, ct = read_box(pl, box), read_box(cl, box)
            origin = tuple(a for a, _ in box)
            vshape = pl.shape
            chunk = chunk or pl.chunks
            sources = {"mode": "remote", "prediction": {"url": args.pred_url},
                       "ct": {"url": args.ct_url},
                       "box_zyx": [list(b) for b in box],
                       "unstored_chunks": "read as zero (masked background)"}
        else:
            ap.error("give --pred/--ct, or --pred-url/--ct-url/--box, "
                     "or --self-test")
        seeds = _load_seeds(args.seeds) if args.seeds else None
        report = audit_arrays(pred, ct, threshold=args.threshold,
                              chunk=chunk or DEFAULT_CHUNK, origin=origin,
                              volume_shape=vshape,
                              blend_margin=args.blend_margin, seeds=seeds)
    except (PredictionSupportError, OSError, ValueError) as exc:
        print(f"scroliq-prediction-support: {exc}", file=sys.stderr)
        return 2
    report["sources"] = sources
    if args.write_filtered:
        if sources.get("mode") != "local":
            print("--write-filtered needs local inputs", file=sys.stderr)
            return 2
        np.save(args.write_filtered, supported_prediction(pred, ct))
        report["filtered_output"] = {
            "path": args.write_filtered,
            "sha256": _sha256(Path(args.write_filtered)),
            "definition": "prediction with every CT == 0 voxel set to 0",
        }
    text = json.dumps(report, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    c = report["counts"]
    print(f"{report['status']}: positives={c['pred_positive']} "
          f"supported={c['pred_positive_ct_supported']} "
          f"ct_zero={c['pred_positive_ct_zero']}", file=sys.stderr)
    if report["status"] == "unverified":
        return 2
    if args.strict and not report["raw_prediction_seed_safe"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
