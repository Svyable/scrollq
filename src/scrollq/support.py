"""Exact-volume surface-prediction CT support, sampled natively.

Definition (same as axiosdevs/herculaneum-scroll-tools ``ct_support``):

- a *positive* is a surface-prediction voxel above ``threshold`` (127);
- a *phantom* is a positive whose aligned masked-CT voxel is exactly 0;
- ``support_frac = 1 - phantoms / positives``, pooled over all samples.

The prediction and CT must share one voxel grid (same L0 shape), so a
prediction made on a different scan of the same scroll fails closed.

Sampling: each sample is one 128^3 CT chunk that lies wholly inside one
192^3 prediction chunk, so it costs one fetch of each. Candidate positions
are spread per dimension (flat-index spread degenerates on non-cubic grids)
and visited in a fixed-seed order. Absent prediction chunks are all-zero and
hold no positives; absent CT chunks are masked background and count fully as
phantom. This is a geometry-prior sanity metric, not ink or readability
evidence.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from numcodecs import get_codec

from .score import _spread

S3_BASE = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
THRESHOLD = 127
METHOD = "scrollq-chunk-sample-v1"


class SupportError(RuntimeError):
    pass


class ZarrV2Level:
    """Minimal read-only HTTP reader for one uint8 zarr v2 pyramid level."""

    def __init__(self, url: str, session: requests.Session):
        self.url = url.rstrip("/")
        self.session = session
        r = session.get(f"{self.url}/.zarray", timeout=60)
        r.raise_for_status()
        meta = r.json()
        if meta.get("dtype") != "|u1" or meta.get("order", "C") != "C":
            raise SupportError(f"{url}: expected C-order uint8, got {meta}")
        if meta.get("filters"):
            raise SupportError(f"{url}: filters are not supported")
        if meta.get("fill_value", 0) not in (0, None):
            raise SupportError(f"{url}: non-zero fill_value is not supported")
        comp = meta.get("compressor")
        if comp is not None and comp.get("id") != "blosc":
            raise SupportError(f"{url}: unsupported compressor {comp}")
        self.shape = tuple(meta["shape"])
        self.chunks = tuple(meta["chunks"])
        self.sep = meta.get("dimension_separator", ".")
        self.codec = get_codec(comp) if comp else None

    def chunk(self, idx: tuple[int, int, int]) -> np.ndarray | None:
        """Decoded chunk cropped to the array edge, or None when not stored."""
        key = self.sep.join(str(i) for i in idx)
        for attempt in range(3):
            try:
                r = self.session.get(f"{self.url}/{key}", timeout=120)
                if r.status_code in (403, 404):
                    return None
                r.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
        raw = self.codec.decode(r.content) if self.codec else r.content
        full = np.frombuffer(raw, dtype=np.uint8).reshape(self.chunks)
        hi = [min(c, s - i * c) for i, c, s in zip(idx, self.chunks, self.shape)]
        return full[: hi[0], : hi[1], : hi[2]]


def _candidates(pred_grid, per_dim: int, seed: int) -> list[tuple]:
    cands = [
        (z, y, x)
        for z in _spread(pred_grid[0], per_dim)
        for y in _spread(pred_grid[1], per_dim)
        for x in _spread(pred_grid[2], per_dim)
    ]
    order = np.random.default_rng(seed).permutation(len(cands))
    return [cands[i] for i in order]


def _measure(pred: ZarrV2Level, ct: ZarrV2Level, p: tuple, threshold: int):
    """Positives and phantoms in the CT chunk nested inside prediction chunk p."""
    pc, cc = pred.chunks, ct.chunks
    c = tuple((pc[d] * p[d] + cc[d] - 1) // cc[d] for d in range(3))
    lo = [cc[d] * c[d] for d in range(3)]
    if any(lo[d] >= ct.shape[d] for d in range(3)):
        return None
    if any(lo[d] + cc[d] > pc[d] * (p[d] + 1) and lo[d] + cc[d] <= ct.shape[d]
           for d in range(3)):
        return None  # CT chunk straddles two prediction chunks
    pchunk = pred.chunk(p)
    if pchunk is None:
        return {"p": p, "positives": 0, "phantom": 0}
    off = [lo[d] - pc[d] * p[d] for d in range(3)]
    ext = [min(cc[d], ct.shape[d] - lo[d]) for d in range(3)]
    pbox = pchunk[off[0]: off[0] + ext[0], off[1]: off[1] + ext[1],
                  off[2]: off[2] + ext[2]]
    pos = pbox > threshold
    n_pos = int(pos.sum())
    if n_pos == 0:
        return {"p": p, "positives": 0, "phantom": 0}
    cchunk = ct.chunk(c)
    if cchunk is None:
        phantom = n_pos
    else:
        phantom = int((pos & (cchunk[: ext[0], : ext[1], : ext[2]] == 0)).sum())
    return {"p": p, "positives": n_pos, "phantom": phantom}


def _bootstrap_ci(samples: list[dict], seed: int, n: int = 2000):
    pos = np.array([s["positives"] for s in samples], dtype=float)
    ph = np.array([s["phantom"] for s in samples], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pos), size=(n, len(pos)))
    fr = 1.0 - ph[idx].sum(axis=1) / pos[idx].sum(axis=1)
    return [round(float(np.percentile(fr, 2.5)), 4),
            round(float(np.percentile(fr, 97.5)), 4)]


def measure_support(pred_url: str, ct_url: str, *, samples: int = 64,
                    per_dim: int = 12, seed: int = 0, workers: int = 8,
                    threshold: int = THRESHOLD) -> dict:
    """Pooled support fraction over ``samples`` CT chunks holding positives."""
    sess = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=workers * 2)
    sess.mount("https://", adapter)
    pred = ZarrV2Level(f"{pred_url.rstrip('/')}/0", sess)
    ct = ZarrV2Level(f"{ct_url.rstrip('/')}/0", sess)
    if pred.shape != ct.shape:
        raise SupportError(
            f"prediction shape {pred.shape} != CT shape {ct.shape}: "
            "not the same voxel grid"
        )
    grid = [-(-s // c) for s, c in zip(pred.shape, pred.chunks)]
    cands = _candidates(grid, per_dim, seed)

    kept: list[dict] = []
    visited = empty = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(cands), workers * 2):
            batch = cands[start: start + workers * 2]
            for r in pool.map(lambda p: _measure(pred, ct, p, threshold), batch):
                if len(kept) >= samples:
                    break
                visited += 1
                if r is None or r["positives"] == 0:
                    empty += 1
                    continue
                kept.append(r)
            if len(kept) >= samples:
                break

    if not kept:
        raise SupportError("no sampled chunk contained prediction positives")
    positives = sum(s["positives"] for s in kept)
    phantom = sum(s["phantom"] for s in kept)
    return {
        "method": METHOD,
        "threshold": threshold,
        "seed": seed,
        "per_dim": per_dim,
        "samples_requested": samples,
        "samples_with_positives": len(kept),
        "complete": len(kept) == samples,
        "candidates_visited": visited,
        "candidates_without_positives": empty,
        "shape": list(pred.shape),
        "sampled_positives": positives,
        "sampled_phantom": phantom,
        "sampled_support_frac": round(1.0 - phantom / positives, 4),
        "support_ci95": _bootstrap_ci(kept, seed),
        "chunks": [list(s["p"]) for s in kept],
    }


def target_urls(scroll: str, volume_id: str, surface_prediction: str,
                ct_name: str, base: str = S3_BASE) -> tuple[str, str]:
    """Open-data URLs for the m7 L0 surface prediction made on this exact scan."""
    pred = (f"{base}/{scroll}/representations/predictions/surfaces/"
            f"{volume_id}-surface-{surface_prediction}-surface-m7-L0-th0.2.zarr")
    ct = f"{base}/{scroll}/volumes/{ct_name}"
    return pred, ct


def support_row(target: dict, ct_name: str, **kw) -> dict:
    """A row in the ``--surface-support`` evidence format, fail-closed."""
    scroll, vid = target["scroll"], target["volume_id"]
    pred_url, ct_url = target_urls(scroll, vid, target["surface_prediction"],
                                   ct_name)
    row = {
        "scroll": scroll,
        "eligible_volume_id": vid,
        "survey_ct": ct_url,
        "survey_preds": pred_url,
        "mode": METHOD,
    }
    if not ct_name.startswith(f"{vid}-"):
        return {**row, "volume_match": "mismatch",
                "usable_for_qualification": False,
                "exclusion_reason": f"CT {ct_name} is not scan {vid}"}
    try:
        m = measure_support(pred_url, ct_url, **kw)
    except (SupportError, requests.RequestException) as exc:
        return {**row, "volume_match": "unverified",
                "usable_for_qualification": False,
                "exclusion_reason": f"measurement failed: {exc}"}
    return {**row, **m, "volume_match": "exact",
            "usable_for_qualification": True}


def normalize_external(target: dict, survey: dict, path: str, sha: str) -> dict:
    """An imported ct_support survey as a ``--surface-support`` row, fail-closed.

    Usable only when both the CT URL and the prediction URL name the exact
    eligible scan; a survey run on another scan of the same scroll is kept
    for the record but excluded.
    """
    scroll, vid = target["scroll"], target["volume_id"]
    ct = str(survey.get("ct") or "")
    preds = str(survey.get("preds") or "")
    row = {
        "scroll": scroll,
        "eligible_volume_id": vid,
        "survey_path": path,
        "survey_sha": sha,
        "survey_ct": ct or None,
        "survey_preds": preds or None,
        "mode": survey.get("mode"),
        "planes_sampled": survey.get("planes_sampled"),
        "sampled_support_frac": survey.get("sampled_support_frac"),
    }
    if not ct:
        return {**row, "volume_match": "unverified",
                "usable_for_qualification": False,
                "exclusion_reason": "survey does not record its CT URL"}
    if (f"/{scroll}/volumes/{vid}-" not in ct
            or f"/{scroll}/" not in preds or f"/{vid}-surface-" not in preds):
        return {**row, "volume_match": "mismatch",
                "usable_for_qualification": False,
                "exclusion_reason": (
                    f"survey CT/prediction are not eligible scan {vid}: {ct}")}
    return {**row, "volume_match": "exact", "usable_for_qualification": True}


def main() -> None:
    from .grand_prize import MANIFESTS

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prize", choices=sorted(MANIFESTS), default="first-letters")
    ap.add_argument("--volumes-txt", default="volumes.txt",
                    help="volume roots; used to resolve each exact CT name")
    ap.add_argument("--scrolls", nargs="*", help="limit to these scrolls")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    roots = [ln.strip() for ln in Path(args.volumes_txt).read_text().splitlines()
             if ln.strip()]
    rows = []
    for t in MANIFESTS[args.prize]["targets"]:
        if args.scrolls and t["scroll"] not in args.scrolls:
            continue
        needle = f"/{t['scroll']}/volumes/{t['volume_id']}-"
        names = [r.split("/volumes/", 1)[1] for r in roots if needle in r]
        if len(names) != 1:
            rows.append({"scroll": t["scroll"],
                         "eligible_volume_id": t["volume_id"],
                         "usable_for_qualification": False,
                         "exclusion_reason": f"{len(names)} CT names match"})
            continue
        row = support_row(t, names[0], samples=args.samples, seed=args.seed,
                          workers=args.workers)
        rows.append(row)
        frac = row.get("sampled_support_frac")
        print(f"{t['scroll']:11} support={frac} ci={row.get('support_ci95')} "
              f"n={row.get('samples_with_positives')} "
              f"{row.get('exclusion_reason', '')}", flush=True)

    out = {
        "schema_version": 1,
        "source": {
            "tool": "scroliq-support",
            "method": METHOD,
            "definition": (
                "sampled_support_frac = 1 - phantom/positives; a positive is a "
                f"surface-prediction voxel > {THRESHOLD}; a phantom is a "
                "positive whose aligned masked-CT voxel is exactly 0."
            ),
            "note": "Geometry-prior sanity metric. Not ink or readability evidence.",
        },
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
