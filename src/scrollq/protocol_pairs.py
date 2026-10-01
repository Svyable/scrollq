"""Do local scan metrics recover the documented ordering of scan protocols?

The Vesuvius Challenge documents that finer, phase-optimized scan protocols
suffer less from "compressed region" haze than coarser ones (smaller voxels,
shorter propagation distance). Several scrolls were scanned under more than
one protocol and the rescan ships with a ``transform.json`` registering it to
the earlier scan. That gives a ground-truth-*ordered* test bed for any
proposed scan-quality metric:

    Sample the same physical region from both scans on one common physical
    grid. A metric that claims to measure layer separability / haze should
    rate the documented-better protocol higher, region after region.

This is a necessary-but-not-sufficient validity check, not a readability
claim. Every threshold below is fixed by ``docs/protocol-pairs-protocol.md``
*before* any real data was read; the verdict is computed by :func:`decide`
from those constants, so a failing result is reported as failing.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from math import comb
from pathlib import Path

import numpy as np

from .metrics import chunk_metrics
from .omezarr import HttpStore, OmeZarrVolume, ReadStats
from .registration import Registration, RegistrationError, infer_registration
from .score import score_from_metrics

SCHEMA_VERSION = 1
BUCKET_URL = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
BUCKET_S3 = "s3://vesuvius-challenge-open-data"
DEFAULT_INDEX = f"{BUCKET_URL}/metadata.min.json"

# --- pre-registered constants (see docs/protocol-pairs-protocol.md) ---------
TARGET_SPACING_UM = 9.0        # matched physical scale
MAX_LEVEL_MISMATCH = 0.15      # chosen pyramid level within 15% of target
CUBE_N = 64                    # samples per axis of each compared cube
MIN_PIXEL_RATIO = 1.8          # fine/coarse voxel-size ratio for a "pair"
MIN_OCCUPANCY = 0.98           # fraction of cube voxels inside the scan mask
MIN_DYN_RANGE = 20.0           # reject flat cubes (p99 - p1 intensity levels)
MAX_RESIDUAL_UM = 50.0         # mean landmark residual for pair inclusion
N_REGIONS = 24
MIN_REGIONS = 12
CANDIDATE_FACTOR = 8           # max candidates tried = factor * N_REGIONS
PRIMARY_METRICS = ("otsu_eta", "edge_sharpness")
EXPLORATORY_METRICS = ("grad_energy", "dyn_range", "legacy_score")
PAIR_CONCORDANT_FRACTION = 0.75   # share of regions with fine > coarse
PAIR_DISCORDANT_FRACTION = 0.25
METRIC_CONCORDANT_PAIRS = 0.80    # share of included pairs concordant
METRIC_DISCORDANT_PAIRS = 0.50
MIN_INCLUDED_PAIRS = 3
NULL_RATIO_MAX = 0.25             # pipeline null |d| < 25% of the effect
BOOTSTRAP_RESAMPLES = 4000


def preregistered_constants() -> dict:
    return {
        "target_spacing_um": TARGET_SPACING_UM,
        "max_level_mismatch": MAX_LEVEL_MISMATCH, "cube_n": CUBE_N,
        "min_pixel_ratio": MIN_PIXEL_RATIO, "min_occupancy": MIN_OCCUPANCY,
        "min_dyn_range": MIN_DYN_RANGE, "max_residual_um": MAX_RESIDUAL_UM,
        "n_regions": N_REGIONS, "min_regions": MIN_REGIONS,
        "candidate_factor": CANDIDATE_FACTOR,
        "primary_metrics": list(PRIMARY_METRICS),
        "exploratory_metrics": list(EXPLORATORY_METRICS),
        "pair_concordant_fraction": PAIR_CONCORDANT_FRACTION,
        "pair_discordant_fraction": PAIR_DISCORDANT_FRACTION,
        "metric_concordant_pairs": METRIC_CONCORDANT_PAIRS,
        "metric_discordant_pairs": METRIC_DISCORDANT_PAIRS,
        "min_included_pairs": MIN_INCLUDED_PAIRS,
        "null_ratio_max": NULL_RATIO_MAX,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
    }


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def separability_metrics(cube: np.ndarray) -> dict:
    """Layer-separability metrics for a float cube of 0..255 intensities.

    ``otsu_eta``: Otsu between-class variance over total variance (0..1).
    Two well separated phases (dark gaps, bright papyrus) give values near 1;
    haze that fills the gaps pulls the histogram together and lowers it.

    ``edge_sharpness``: 90th-percentile gradient magnitude per unit of
    p99-p1 contrast. Blur lowers it independent of overall brightness.

    The legacy ScrollQ components are returned too (exploratory only).
    """
    v = np.asarray(cube, dtype=np.float32)
    flat = v.ravel()
    vi = np.clip(np.rint(flat), 0, 255).astype(np.int64)
    p = np.bincount(vi, minlength=256).astype(np.float64)
    p /= p.sum()
    levels = np.arange(256, dtype=np.float64)
    omega = np.cumsum(p)
    mu = np.cumsum(p * levels)
    mu_t = mu[-1]
    var_t = float(np.sum(p * (levels - mu_t) ** 2))
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = np.where(denom > 1e-12, (mu_t * omega - mu) ** 2 / denom,
                           0.0)
    eta = float(sigma_b.max() / var_t) if var_t > 1e-9 else float("nan")

    p1, p99 = (float(x) for x in np.percentile(flat, (1, 99)))
    rng = p99 - p1
    gz, gy, gx = np.gradient(v)
    mag = np.sqrt(gz * gz + gy * gy + gx * gx)
    sharp = (float(np.percentile(mag, 90)) / rng if rng >= 1.0
             else float("nan"))

    legacy = chunk_metrics(np.clip(np.rint(v), 0, 255).astype(np.uint8))
    return {
        "otsu_eta": eta,
        "edge_sharpness": sharp,
        "grad_energy": legacy["grad_energy"],
        "dyn_range": legacy["dyn_range"],
        "legacy_score": float(score_from_metrics(legacy)),
        "occupancy": float((flat >= 0.5).mean()),
    }


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def sign_test_p(n_pos: int, n_neg: int) -> float:
    """One-sided exact sign test P(X >= n_pos), X ~ Bin(n_pos+n_neg, 1/2).

    Ties are dropped by the caller. Returns 1.0 when there are no
    informative regions.
    """
    n = n_pos + n_neg
    if n == 0:
        return 1.0
    return float(sum(comb(n, k) for k in range(n_pos, n + 1)) / 2**n)


def bootstrap_median_ci(values, seed: int, resamples: int = BOOTSTRAP_RESAMPLES,
                        alpha: float = 0.05) -> tuple[float, float]:
    v = np.asarray(values, dtype=np.float64)
    if len(v) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(resamples, len(v)))
    med = np.median(v[idx], axis=1)
    lo, hi = np.quantile(med, (alpha / 2, 1 - alpha / 2))
    return float(lo), float(hi)


def _seed_for(*parts) -> int:
    h = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**32)


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------
def cube_grid_xyz(center_xyz, n: int, step: float) -> np.ndarray:
    """``(n, n, n, 3)`` x,y,z points; axes are ``(iz, iy, ix)``."""
    offs = (np.arange(n, dtype=np.float64) - (n - 1) / 2.0) * step
    oz, oy, ox = np.meshgrid(offs, offs, offs, indexing="ij")
    c = np.asarray(center_xyz, dtype=np.float64)
    return np.stack([c[0] + ox, c[1] + oy, c[2] + oz], axis=-1)


def _to_level_zyx(vol: OmeZarrVolume, level: int, pts_xyz: np.ndarray):
    scale = np.array(vol.levels[level].scale, dtype=np.float64)  # z,y,x
    return pts_xyz.reshape(-1, 3)[:, ::-1] / scale


def sample_cube(vol: OmeZarrVolume, level: int, pts_xyz_level0: np.ndarray,
                n: int) -> tuple[np.ndarray, float, ReadStats]:
    """Sample a cube; returns ``(cube, valid_fraction, stats)``."""
    vals, valid, stats = vol.sample_trilinear(
        level, _to_level_zyx(vol, level, pts_xyz_level0))
    return vals.reshape(n, n, n), float(valid.mean()), stats


def choose_level(vol: OmeZarrVolume, px_um: float,
                 target_um: float = TARGET_SPACING_UM
                 ) -> tuple[int, float, float]:
    """Pyramid level nearest the target spacing: ``(level, spacing, error)``."""
    lvl = vol.nearest_level(target_um, px_um)
    spacing = px_um * float(np.mean(vol.levels[lvl].scale))
    return lvl, spacing, spacing / target_um - 1.0


@dataclass
class PairRun:
    """Everything :func:`run_pair` needs, already opened (no network here)."""
    sample: str
    moving_id: str
    fixed_id: str
    moving: OmeZarrVolume
    fixed: OmeZarrVolume
    registration: Registration
    px_moving_um: float
    px_fixed_um: float


def _fine_coarse(pr: PairRun):
    """Documented ordering: the smaller-voxel scan is the better protocol."""
    if pr.px_moving_um <= pr.px_fixed_um:
        return ("moving", "fixed")
    return ("fixed", "moving")


def run_pair(pr: PairRun, *, seed: int, n_regions: int = N_REGIONS,
             target_um: float = TARGET_SPACING_UM, cube_n: int = CUBE_N,
             progress=None) -> dict:
    """Run the paired comparison for one registered pair of scans."""
    fine_name, coarse_name = _fine_coarse(pr)
    vols = {"moving": pr.moving, "fixed": pr.fixed}
    px = {"moving": pr.px_moving_um, "fixed": pr.px_fixed_um}
    lvl, spacing = {}, {}
    for k in vols:
        lv, sp, err = choose_level(vols[k], px[k], target_um)
        if abs(err) > MAX_LEVEL_MISMATCH:
            return {"ok": False, "reason":
                    f"{k} has no pyramid level within "
                    f"{MAX_LEVEL_MISMATCH:.0%} of {target_um} um "
                    f"(nearest {sp:.2f} um)"}
        lvl[k], spacing[k] = lv, sp
    # Never sample finer than either chosen level: coarser of the two.
    h_um = max(spacing.values())
    step_fixed = h_um / pr.px_fixed_um   # fixed level-0 voxels per grid step

    fshape_zyx = pr.fixed.levels[0].shape
    half_diag = (cube_n / 2.0) * np.sqrt(3.0) * step_fixed
    lo = np.array([half_diag] * 3)
    hi = np.array([fshape_zyx[2], fshape_zyx[1], fshape_zyx[0]]) - half_diag
    if (hi <= lo).any():
        return {"ok": False, "reason": "fixed volume smaller than one cube"}
    rng = np.random.default_rng(_seed_for(seed, pr.sample, pr.moving_id))

    rows: list[dict] = []
    rejections = {"outside_volume": 0, "occupancy": 0, "flat": 0}
    stats = ReadStats()
    tried = 0
    max_tries = CANDIDATE_FACTOR * n_regions
    keys = list(PRIMARY_METRICS) + list(EXPLORATORY_METRICS)

    def metrics_at(center_fixed, shift=0.0):
        pts = cube_grid_xyz(center_fixed, cube_n, step_fixed)
        if shift:
            pts = pts + shift * step_fixed
        out = {}
        for k in ("fixed", "moving"):
            p = pts if k == "fixed" else pr.registration.fixed_to_moving(
                pts.reshape(-1, 3)).reshape(pts.shape)
            cube, vfrac, st = sample_cube(vols[k], lvl[k], p, cube_n)
            stats.add(st)
            out[k] = (cube, vfrac)
        return out

    while len(rows) < n_regions and tried < max_tries:
        tried += 1
        c = rng.uniform(lo, hi)
        cubes = metrics_at(c)
        if any(v[1] < 1.0 for v in cubes.values()):
            rejections["outside_volume"] += 1
            continue
        m = {k: separability_metrics(cubes[k][0]) for k in cubes}
        if any(m[k]["occupancy"] < MIN_OCCUPANCY for k in m):
            rejections["occupancy"] += 1
            continue
        if any(m[k]["dyn_range"] < MIN_DYN_RANGE for k in m):
            rejections["flat"] += 1
            continue
        # pipeline-null control: identical volume + pipeline, grid shifted by
        # half a step. Any "effect" here is resampling noise, not protocol.
        shifted = metrics_at(c, shift=0.5)
        if any(v[1] < 1.0 for v in shifted.values()):
            rejections["outside_volume"] += 1
            continue
        mn = {k: separability_metrics(shifted[k][0]) for k in shifted}
        row = {"center_fixed_xyz": [round(float(v), 2) for v in c],
               "fine": {k: m[fine_name][k] for k in keys},
               "coarse": {k: m[coarse_name][k] for k in keys},
               "d": {k: m[fine_name][k] - m[coarse_name][k] for k in keys},
               "null": {k: {"fine": mn[fine_name][k] - m[fine_name][k],
                            "coarse": mn[coarse_name][k] - m[coarse_name][k]}
                        for k in keys}}
        rows.append(row)
        if progress:
            progress(pr.sample, len(rows), n_regions)

    summary = summarize_pair(rows, seed=_seed_for(seed, pr.sample, "ci"))
    return {
        "ok": True, "fine": fine_name, "coarse": coarse_name,
        "levels": {k: lvl[k] for k in lvl},
        "level_spacing_um": {k: round(spacing[k], 4) for k in spacing},
        "grid_spacing_um": round(h_um, 4), "cube_n": cube_n,
        "candidates_tried": tried, "accepted": len(rows),
        "rejections": rejections,
        "chunks_present": stats.chunks_present,
        "chunks_missing": stats.chunks_missing,
        "bytes_read": stats.bytes_read,
        "regions": rows, "summary": summary,
    }


def summarize_pair(rows: list[dict], seed: int) -> dict:
    out: dict = {"metrics": {}, "null": {}}
    for k in list(PRIMARY_METRICS) + list(EXPLORATORY_METRICS):
        d = np.array([r["d"][k] for r in rows], dtype=np.float64)
        d = d[np.isfinite(d)]
        n_pos, n_neg = int((d > 0).sum()), int((d < 0).sum())
        lo, hi = bootstrap_median_ci(d, seed)
        out["metrics"][k] = {
            "n": int(len(d)),
            "median_d": float(np.median(d)) if len(d) else float("nan"),
            "mean_d": float(d.mean()) if len(d) else float("nan"),
            "frac_positive": float(n_pos / len(d)) if len(d) else float("nan"),
            "n_positive": n_pos, "n_negative": n_neg,
            "sign_test_p": sign_test_p(n_pos, n_neg),
            "median_ci95": [lo, hi],
        }
        nulls = np.array([abs(r["null"][k][s]) for r in rows
                          for s in ("fine", "coarse")], dtype=np.float64)
        nulls = nulls[np.isfinite(nulls)]
        out["null"][k] = {"median_abs": float(np.median(nulls))
                          if len(nulls) else float("nan")}
    return out


# --------------------------------------------------------------------------
# pre-registered decision rule
# --------------------------------------------------------------------------
def decide(pairs: list[dict]) -> dict:
    """Verdict per primary metric from per-pair summaries.

    ``pairs``: dicts with ``included`` (bool) and ``summary`` as produced by
    :func:`summarize_pair`. See ``docs/protocol-pairs-protocol.md``.
    """
    included = [p for p in pairs if p.get("included")]
    out: dict = {"n_included_pairs": len(included), "metrics": {}}
    for k in PRIMARY_METRICS:
        conc, disc, notes = [], [], []
        for p in included:
            s = p["summary"]["metrics"][k]
            null = p["summary"]["null"][k]["median_abs"]
            frac, med = s["frac_positive"], s["median_d"]
            null_ok = bool(null < NULL_RATIO_MAX * abs(med))
            if med > 0 and frac >= PAIR_CONCORDANT_FRACTION and null_ok:
                conc.append(p["name"])
            elif med < 0 and frac <= PAIR_DISCORDANT_FRACTION:
                disc.append(p["name"])
            else:
                notes.append(p["name"])
        n = len(included)
        if n < MIN_INCLUDED_PAIRS:
            verdict = "inconclusive"
            reason = (f"{n} included pairs < required {MIN_INCLUDED_PAIRS}")
        elif len(conc) / n >= METRIC_CONCORDANT_PAIRS:
            verdict, reason = "concordant", (
                f"{len(conc)}/{n} pairs concordant with the documented "
                "protocol ordering")
        elif len(disc) / n >= METRIC_DISCORDANT_PAIRS:
            verdict, reason = "discordant", (
                f"{len(disc)}/{n} pairs reverse the documented ordering")
        else:
            verdict, reason = "inconclusive", (
                f"{len(conc)} concordant, {len(disc)} discordant, "
                f"{len(notes)} mixed of {n} pairs")
        out["metrics"][k] = {"verdict": verdict, "reason": reason,
                             "concordant": conc, "discordant": disc,
                             "mixed": notes}
    return out


# --------------------------------------------------------------------------
# discovery against the bucket index
# --------------------------------------------------------------------------
_ID_RE = re.compile(r"(?<!\d)(\d{14})(?!\d)")
_UM_RE = re.compile(r"(\d+(?:\.\d+)?)um")
_KEV_RE = re.compile(r"(\d+(?:\.\d+)?)keV")


def _volume_origin(vol: dict) -> tuple[str, str] | None:
    """``(access_root_url, path)`` of a volume's ome-zarr, or ``None``."""
    for item in vol.get("data", []):
        if item.get("type") == "ome-zarr" and item.get("origins"):
            o = item["origins"][0]
            roots = o.get("access_roots") or []
            if roots:
                return roots[0]["url"], o["path"]
    return None


def _http_base(root_url: str) -> str:
    return BUCKET_URL if root_url == BUCKET_S3 else root_url.rstrip("/")


def resolve_fixed(volumes: dict, moving_id: str, fixed_name: str,
                  radix_of=None) -> tuple[str | None, str]:
    """Resolve a ``fixed_volume`` string to a volume id in the same sample.

    Order: an embedded 14-digit volume id; a unique ``scanRadix`` match (via
    ``radix_of(volume_id) -> str | None``); a unique (pixel size, energy)
    match. Anything else is reported ambiguous rather than guessed.
    """
    others = {vid: v for vid, v in volumes.items() if vid != moving_id}
    m = _ID_RE.search(fixed_name)
    if m:
        return (m.group(1), "volume id in name") if m.group(1) in others \
            else (None, f"named volume {m.group(1)} not in sample")
    stem = re.sub(r"_masked$", "", fixed_name)
    cands = list(others)
    um, kev = _UM_RE.search(fixed_name), _KEV_RE.search(fixed_name)
    if um:
        want = float(um.group(1))
        cands = [c for c in cands if abs(
            others[c]["properties"].get("pixel_size_um", -1) / want - 1) < .01]
    if kev:
        want = float(kev.group(1))
        cands = [c for c in cands if abs(
            others[c]["properties"].get("energy_keV", -1) - want) < 0.5]
    if radix_of is not None and len(cands) > 1:
        matched = [c for c in cands if (radix_of(c) or "").replace(
            "_masked", "") == stem]
        if len(matched) == 1:
            return matched[0], "scanRadix match"
    if len(cands) == 1:
        return cands[0], "unique pixel-size/energy match"
    if not cands:
        return None, "no candidate volume in sample"
    return None, f"ambiguous: {len(cands)} candidates {sorted(cands)}"


def load_json_maybe_gz(location: str):
    """Load JSON from a path or URL, transparently gunzipping."""
    if re.match(r"https?://", location):
        import requests
        r = requests.get(location, timeout=60)
        r.raise_for_status()
        raw = r.content
    else:
        raw = Path(location).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def discover(index: dict, *, only: set[str] | None = None, fetch=None,
             log=lambda *_: None) -> list[dict]:
    """List moving volumes with registrations and resolve their fixed scans.

    ``fetch(url) -> bytes | None`` defaults to an HTTP GET returning ``None``
    on 404. Each returned spec carries a ``status``; only ``"ok"`` specs can
    be run. Exclusions are reported, never dropped silently.
    """
    import requests

    sess = requests.Session()

    def default_fetch(url):
        try:
            r = sess.get(url, timeout=60)
        except Exception:
            return None
        return r.content if r.status_code == 200 else None

    fetch = fetch or default_fetch
    specs = []
    for sample, rec in sorted(index["samples"].items()):
        if only and sample not in only:
            continue
        vols = rec.get("volumes", {})
        for vid, v in sorted(vols.items()):
            origin = _volume_origin(v)
            if origin is None:
                continue
            base = f"{_http_base(origin[0])}/{origin[1]}"
            raw = fetch(base + "transform.json")
            if raw is None:
                continue  # not a registered (moving) volume
            spec = {"sample": sample, "moving_id": vid,
                    "moving_url": base,
                    "transform_sha256": hashlib.sha256(raw).hexdigest(),
                    "px_moving_um": v["properties"].get("pixel_size_um"),
                    "energy_moving_keV": v["properties"].get("energy_keV")}
            try:
                doc = json.loads(raw)
                reg = infer_registration(doc)
            except (ValueError, RegistrationError) as exc:
                spec.update(status="registration_rejected", detail=str(exc))
                specs.append(spec)
                continue

            def radix_of(cid, _vols=vols):
                o = _volume_origin(_vols[cid])
                if o is None:
                    return None
                meta = fetch(f"{_http_base(o[0])}/{o[1]}metadata.json")
                try:
                    return json.loads(meta)["scan"]["tomo"]["acquisition"][
                        "scanRadix"] if meta else None
                except (KeyError, ValueError, TypeError):
                    return None

            fixed_id, how = resolve_fixed(vols, vid, reg.fixed_name, radix_of)
            spec.update(fixed_name=reg.fixed_name, resolution=how,
                        registration={
                            "direction": reg.direction,
                            "axis_order": reg.axis_order,
                            "residual_mean_vox": round(reg.residual_mean, 3),
                            "residual_max_vox": round(reg.residual_max, 3),
                            "n_landmarks": reg.n_landmarks,
                            "scale": round(reg.scale, 5)})
            if fixed_id is None:
                spec.update(status="fixed_unresolved", detail=how)
            else:
                fo = _volume_origin(vols[fixed_id])
                spec.update(
                    fixed_id=fixed_id,
                    fixed_url=f"{_http_base(fo[0])}/{fo[1]}" if fo else None,
                    px_fixed_um=vols[fixed_id]["properties"].get(
                        "pixel_size_um"),
                    energy_fixed_keV=vols[fixed_id]["properties"].get(
                        "energy_keV"),
                    status="ok" if fo else "fixed_without_zarr")
            specs.append(spec)
            log(sample, vid, spec["status"])
    return specs


def inclusion(spec: dict) -> tuple[bool, str, str]:
    """Pre-registered pair inclusion rule (independent of any metric).

    Returns ``(included, reason, code)``; ``code`` is ``"ok"``,
    ``"residual"`` (eligible only for the sensitivity analysis) or
    ``"excluded"``.
    """
    if spec.get("status") != "ok":
        return False, (f"status {spec.get('status')}: "
                       f"{spec.get('detail', '')}"), "excluded"
    pm, pf = spec["px_moving_um"], spec["px_fixed_um"]
    ratio = max(pm, pf) / min(pm, pf)
    if ratio < MIN_PIXEL_RATIO:
        return False, (f"voxel-size ratio {ratio:.2f} < "
                       f"{MIN_PIXEL_RATIO}"), "excluded"
    reg = spec["registration"]
    # residuals are in destination-frame level-0 voxels
    dest_px = pf if reg["direction"] == "moving_to_fixed" else pm
    res_um = reg["residual_mean_vox"] * dest_px
    if res_um > MAX_RESIDUAL_UM:
        return False, (f"landmark residual {res_um:.0f} um > "
                       f"{MAX_RESIDUAL_UM:.0f} um"), "residual"
    return True, "ok", "ok"


def open_pair(spec: dict, cache_chunks: int = 96) -> PairRun:
    doc = json.loads(HttpStore(spec["moving_url"]).get("transform.json"))
    reg = infer_registration(doc)
    mv = OmeZarrVolume.open(HttpStore(spec["moving_url"]), "", cache_chunks)
    fx = OmeZarrVolume.open(HttpStore(spec["fixed_url"]), "", cache_chunks)
    return PairRun(spec["sample"], spec["moving_id"], spec["fixed_id"], mv,
                   fx, reg, spec["px_moving_um"], spec["px_fixed_um"])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="scroliq-pairs",
        description="Test whether scan metrics recover the documented "
                    "ordering of scan protocols on registered rescans.")
    ap.add_argument("--index", default=DEFAULT_INDEX,
                    help="bucket metadata index (path or URL; .gz ok)")
    ap.add_argument("--sample", action="append",
                    help="restrict to a sample (repeatable)")
    ap.add_argument("--regions", type=int, default=N_REGIONS)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--sensitivity", action="store_true",
                    help="also run pairs excluded only for landmark residual; "
                         "reported separately, never part of the decision")
    ap.add_argument("--list", action="store_true",
                    help="only discover and print pair specs")
    ap.add_argument("--out", help="write the JSON report here")
    args = ap.parse_args(argv)

    index, index_sha = load_json_maybe_gz(args.index)
    specs = discover(index, only=set(args.sample) if args.sample else None,
                     log=lambda *a: print("discovered", *a, file=sys.stderr))
    report: dict = {
        "schema_version": SCHEMA_VERSION, "index": args.index,
        "index_sha256": index_sha, "seed": args.seed,
        "preregistered": preregistered_constants(), "pairs": [],
    }
    for spec in specs:
        ok, why, code = inclusion(spec)
        entry = {"name": f"{spec['sample']}:{spec['moving_id']}",
                 "spec": spec, "included": ok, "inclusion_reason": why,
                 "sensitivity_only": code == "residual"}
        print(f"{entry['name']:<32} {'INCLUDE' if ok else 'exclude'}  {why}",
              file=sys.stderr)
        report["pairs"].append(entry)
    if not args.list:
        for entry in report["pairs"]:
            runnable = entry["included"] or (args.sensitivity
                                             and entry["sensitivity_only"])
            if not runnable:
                continue
            counts_toward_decision = entry["included"]
            try:
                pr = open_pair(entry["spec"])
                res = run_pair(
                    pr, seed=args.seed, n_regions=args.regions,
                    progress=lambda s, i, n: print(f"  {s} {i}/{n}",
                                                   file=sys.stderr))
            except Exception as exc:  # recorded, not silently dropped
                entry.update(included=False,
                             inclusion_reason=f"run failed: {exc}")
                continue
            if not res["ok"]:
                entry.update(included=False, inclusion_reason=res["reason"])
                continue
            entry.update(res)
            if not counts_toward_decision:
                entry["included"] = False  # sensitivity: reported, not counted
            elif res["accepted"] < MIN_REGIONS:
                entry.update(included=False, inclusion_reason=(
                    f"only {res['accepted']} regions accepted "
                    f"< {MIN_REGIONS}"))
        report["decision"] = decide([p for p in report["pairs"]
                                     if "summary" in p])
        for k, v in report["decision"]["metrics"].items():
            print(f"{k}: {v['verdict']} ({v['reason']})", file=sys.stderr)
    text = json.dumps(report, indent=2, sort_keys=True, default=float)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
