"""Volume-level quality scoring for volcomp scroll volumes.

Decodes K sampled 128^3 inner chunks at full resolution (L0) through the
vendored libvolcomp decoder (via the ``zpa`` package), aggregates
per-chunk metrics, and produces a documented 0-100 triage score.
"""

from __future__ import annotations

import numpy as np

from zpa.httpstore import open_store
from zpa import volcomp as vc

from .metrics import chunk_metrics


def _spread(n: int, k: int) -> list[int]:
    if n <= 0 or k <= 0:
        return []
    if k == 1:
        return [0]
    if n <= k:
        return list(range(n))
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def score_from_metrics(m: dict) -> float:
    """Apply the documented 0-100 triage formula to one chunk's metrics.

    Calibrated against the PHerc0009B reference volume; weights are a
    judgment call, published here so anyone can re-weight.
    """
    s_signal = 40.0 * min(1.0, m["nonzero_frac"] / 0.9)
    s_texture = 30.0 * min(1.0, m["grad_energy"] / 12.0)
    s_dynamic = 20.0 * min(1.0, m["dyn_range"] / 200.0)
    p_sat = 25.0 * min(1.0, m["sat_frac"] / 0.05)
    p_dead = min(30.0, 15.0 * m["dead_slices"])
    return max(0.0, min(100.0, s_signal + s_texture + s_dynamic
                        - p_sat - p_dead))

def score_volume(base_url: str, root: str, samples: int = 4,
                 rotate: int = 0, spread: int = 3) -> dict:
    """Score one volcomp scroll volume. Returns a result dict.

    ``rotate`` cyclically shifts the shard-candidate order, giving a
    different deterministic sample for stability checks. ``spread`` is the
    per-dimension candidate count (spread^3 candidates); 3 gives 27,
    5 gives 125. Denser spreads find more present shards on sparse
    volumes, at the cost of more candidate probes.
    """
    result: dict = {"root": root, "ok": False}
    if samples < 1:
        result["error"] = "samples must be >= 1"
        return result
    store = open_store(base_url)
    ok, reason = vc.available()
    if not ok:
        result["error"] = f"volcomp unavailable: {reason}"
        return result
    try:
        meta = store.get_json(f"{root}/0/zarr.json")
    except Exception as exc:
        result["error"] = f"zarr.json unreadable: {exc}"
        return result
    info = vc.parse_zarr_json(meta)
    if info is None or info.inner_codec != "volcomp":
        result["error"] = "not a volcomp-sharded v3 level"
        return result

    shard_grid = [max(1, (s + o - 1) // o)
                  for s, o in zip(info.shape, info.outer_chunks)]
    n_shards = 1
    for g in shard_grid:
        n_shards *= g

    chunk_results = []
    chunk_provenance = []  # parallel to chunk_results: where each chunk came from
    missing_shards = 0
    shard_read_failures = 0
    sess = store._session()
    # Spread shard candidates per-dimension (flat-index spread degenerates
    # to an edge line on non-cubic grids). Skip shards that are nearly
    # all mask so the score reflects the scroll body, not the background.
    cands = [(x, y, z)
             for x in _spread(shard_grid[0], spread)
             for y in _spread(shard_grid[1], spread)
             for z in _spread(shard_grid[2], spread)]
    if rotate:
        rotate %= max(1, len(cands))
        cands = cands[rotate:] + cands[:rotate]
    for sc in cands:
        if len(chunk_results) >= samples:
            break
        skey = vc.shard_key(root, "0", sc)
        cps = vc.inner_chunks_per_shard(info, sc)
        n_inner = 1
        for c in cps:
            n_inner *= c
        try:
            idx_size = vc.index_encoded_size(n_inner, info.index_codecs)
            r = sess.get(f"{base_url}/{skey}",
                         headers={"Range": f"bytes=-{idx_size}"},
                         timeout=60)
            if r.status_code == 404:
                missing_shards += 1
                continue
            r.raise_for_status()
            raw_index = (r.content[-idx_size:] if r.status_code == 200
                         else r.content)
        except Exception:
            shard_read_failures += 1
            continue
        entries = vc.parse_index(raw_index, n_inner, info.index_codecs)
        if not entries:
            continue
        present_frac = (sum(1 for o, _ in entries if o != vc.MISSING)
                        / n_inner)
        if present_frac < 0.05:
            continue  # nearly all mask; not representative of the scroll
        # Spread inner-chunk indices; decode up to 2 present ones per
        # shard (masked background legitimately leaves most absent).
        inner_grid_n = 1
        for c in cps:
            inner_grid_n *= c
        decoded_here = 0
        for flat_i in _spread(inner_grid_n, 6):
            if decoded_here >= 2 or len(chunk_results) >= samples:
                break
            ic = []
            rem = flat_i
            for c in reversed(cps):
                ic.append(rem % c)
                rem //= c
            ic = tuple(reversed(ic))
            off, ln = entries[flat_i]
            if off == vc.MISSING:
                continue
            try:
                blob = store.get_range(skey, off, ln)
            except Exception:
                continue
            raw = vc.decode_chunk(blob)
            if raw is None:
                continue
            vox = np.frombuffer(raw, dtype=np.uint8).reshape(
                (info.inner_chunks[0], info.inner_chunks[1],
                 info.inner_chunks[2]))
            # edge crop (same logic as the zpa probe)
            gic = tuple(sc[d] * (info.outer_chunks[d] //
                                 info.inner_chunks[d]) + ic[d]
                        for d in range(3))
            lo = [gic[d] * info.inner_chunks[d] for d in range(3)]
            hi = [min(lo[d] + info.inner_chunks[d], info.shape[d])
                  for d in range(3)]
            vox = vox[: hi[0] - lo[0], : hi[1] - lo[1], : hi[2] - lo[2]]
            chunk_results.append(chunk_metrics(vox))
            # Provenance: stable identity for this decoded sample. The shard
            # key + inner flat index uniquely identifies the chunk within the
            # volume; coordinates are recorded for human inspection.
            chunk_provenance.append({
                "identity": f"{skey}#{flat_i}",
                "shard_coord": list(sc),
                "shard_key": skey,
                "inner_flat": flat_i,
                "inner_coord": list(ic),
            })
            decoded_here += 1

    sampling = {
        "requested": samples,
        "decoded": len(chunk_results),
        "complete": len(chunk_results) == samples,
        "rotate": rotate,
        "spread": spread,
        "shard_candidates": len(cands),
        "missing_shards": missing_shards,
        "shard_read_failures": shard_read_failures,
    }
    result["sampling"] = sampling
    # Provenance: stable identity per decoded chunk. Enables verifying
    # that two runs actually sampled disjoint chunks (not just disjoint
    # candidate order).
    result["sample_provenance"] = chunk_provenance
    if not chunk_results:
        result["error"] = (f"no chunks decoded "
                           f"({missing_shards} shards absent, "
                           f"{shard_read_failures} shard read failures)")
        return result

    agg: dict[str, float] = {}
    for key in ("nonzero_frac", "std", "dyn_range", "sat_frac",
                "grad_energy"):
        agg[key] = float(np.mean([c[key] for c in chunk_results]))
    agg["dead_slices"] = int(sum(c["dead_slices"] for c in chunk_results))
    agg["chunks_decoded"] = len(chunk_results)

    # --- documented heuristic triage score (0-100) ---
    score = score_from_metrics(agg)
    # Per-chunk score distribution: quantifies within-volume heterogeneity.
    # A high mean with high std means "good on average but inconsistent" —
    # the ranking's uncertainty, not just its level.
    chunk_scores = [score_from_metrics(c) for c in chunk_results]
    cs = np.array(chunk_scores)
    result.update({
        "ok": True,
        "score": round(score, 1),
        "score_std": round(float(np.std(cs)), 1),
        "score_min": round(float(np.min(cs)), 1),
        "score_max": round(float(np.max(cs)), 1),
        "components": {
            "signal_40": round(40.0 * min(1.0, agg["nonzero_frac"] / 0.9), 1),
            "texture_30": round(30.0 * min(1.0, agg["grad_energy"] / 12.0), 1),
            "dynamic_20": round(20.0 * min(1.0, agg["dyn_range"] / 200.0), 1),
            "pen_sat": round(25.0 * min(1.0, agg["sat_frac"] / 0.05), 1),
            "pen_dead": round(min(30.0, 15.0 * agg["dead_slices"]), 1),
        },
        "metrics": {k: round(v, 4) if isinstance(v, float) else v
                    for k, v in agg.items()},
    })
    return result
