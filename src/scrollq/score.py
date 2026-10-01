"""Volume-level quality scoring for volcomp scroll volumes.

Decodes K sampled 128^3 inner chunks at full resolution (L0) through the
vendored libvolcomp decoder (via the ``zpa`` package), aggregates
per-chunk metrics, and produces a documented 0-100 triage score.
"""

from __future__ import annotations

from collections.abc import Collection

import hashlib

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


CANDIDATE_ORDERS = ("grid", "balanced")


def _radical_inverse(n: int, base: int) -> float:
    inv, f = 0.0, 1.0 / base
    while n:
        inv += f * (n % base)
        n //= base
        f /= base
    return inv


def _balanced_lattice(dims: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """Every lattice point, ordered so that each prefix fills the volume.

    Halton points (bases 2, 3, 5) are mapped, in sequence, to the nearest
    lattice point not yet used (ties broken by lattice order). The first
    points land in the interior and spread through x, y and z; the boundary
    planes, which are mostly masked background in a scroll scan, come late.
    Deterministic, no randomness.
    """
    remaining = [(i, j, k) for i in range(dims[0]) for j in range(dims[1]) for k in range(dims[2])]
    order = []
    n = 1
    while remaining:
        target = [_radical_inverse(n, b) * (d - 1) for b, d in zip((2, 3, 5), dims)]
        best = min(range(len(remaining)), key=lambda t: (
            sum((remaining[t][a] - target[a]) ** 2 for a in range(3)), remaining[t]))
        order.append(remaining.pop(best))
        n += 1
    return order


def _candidates(shard_grid, spread: int, rotate: int = 0,
                order: str = "grid",
                part: tuple[int, int] | None = None) -> list[tuple[int, int, int]]:
    """Shard candidates in the order sampling consumes them.

    ``grid`` (default, used by every published campaign) is x-major, so the
    first spread**2 candidates share one x plane and a small sample can be
    drawn from a single slab. ``balanced`` orders the same lattice so
    every prefix fills the volume (see ``_balanced_lattice``). ``part=(k, i)`` keeps every k-th
    candidate starting at i, after ordering and rotation: parts with the
    same k are shard-disjoint, so their chunks are disjoint by construction.
    """
    if order not in CANDIDATE_ORDERS:
        raise ValueError(f"order must be one of {CANDIDATE_ORDERS}")
    axes = [_spread(g, spread) for g in shard_grid]
    dims = (len(axes[0]), len(axes[1]), len(axes[2]))
    if order == "balanced":
        lattice = _balanced_lattice(dims)
    else:
        lattice = [(i, j, k) for i in range(dims[0]) for j in range(dims[1]) for k in range(dims[2])]
    cands = [(axes[0][i], axes[1][j], axes[2][k]) for i, j, k in lattice]
    if rotate:
        rotate %= max(1, len(cands))
        cands = cands[rotate:] + cands[:rotate]
    if part is not None:
        k, i = part
        if k < 1 or not 0 <= i < k:
            raise ValueError("part must be (k, i) with k >= 1 and 0 <= i < k")
        cands = _split(cands, k)[i]
    return cands


def _split(cands: list[tuple[int, int, int]], k: int) -> list[list[tuple[int, int, int]]]:
    """Split an ordered candidate list into k shard-disjoint, interleaved parts.

    Taking every k-th element is not neutral for a Halton-ordered list:
    consecutive Halton points alternate between halves of x, so position
    parity would put each part in one half of the volume. Instead each
    consecutive block of k candidates is dealt one per part, with the
    assignment permuted by a fixed hash of the block's coordinates.
    """
    parts: list[list[tuple[int, int, int]]] = [[] for _ in range(k)]
    for start in range(0, len(cands), k):
        block = cands[start:start + k]
        digest = hashlib.sha256(repr(block).encode()).digest()
        shift = int.from_bytes(digest[:4], "big") % k
        for offset, cand in enumerate(block):
            parts[(offset + shift) % k].append(cand)
    return parts


def _read_shard_index(
    store, path: str, length: int
) -> tuple[bytes | None, str, str | None]:
    """Read a shard-index suffix through the public store contract.

    A failed suffix read is not evidence that an object is absent.  Confirm a
    404 with the public ``head`` API; every other failure remains explicitly
    unknown/read-failure evidence.
    """
    try:
        return store.get_suffix(path, length), "present", None
    except Exception as exc:
        try:
            info = store.head(path)
        except Exception:
            return None, "read-failure", str(exc)
        if not info.exists and info.status == 404:
            return None, "missing", None
        return None, "read-failure", str(exc)


def score_components(m: dict) -> dict[str, float]:
    """Unrounded additive terms of the documented 0-100 triage formula.

    This is the single place the weights live: the score and the published
    per-volume ``components`` breakdown are both derived from it, so they
    cannot drift apart. Keys are the public JSON component names.
    """
    return {
        "signal_40": 40.0 * min(1.0, m["nonzero_frac"] / 0.9),
        "texture_30": 30.0 * min(1.0, m["grad_energy"] / 12.0),
        "dynamic_20": 20.0 * min(1.0, m["dyn_range"] / 200.0),
        "pen_sat": 25.0 * min(1.0, m["sat_frac"] / 0.05),
        "pen_dead": min(30.0, 15.0 * m["dead_slices"]),
    }


def score_from_metrics(m: dict) -> float:
    """Apply the documented 0-100 triage formula to one chunk's metrics.

    Calibrated against the PHerc0009B reference volume; weights are a
    judgment call, published here so anyone can re-weight.
    """
    c = score_components(m)
    return max(0.0, min(100.0, c["signal_40"] + c["texture_30"]
                        + c["dynamic_20"] - c["pen_sat"] - c["pen_dead"]))


def score_volume(base_url: str, root: str, samples: int = 4,
                 rotate: int = 0, spread: int = 3,
                 exclude: Collection[str] | None = None,
                 order: str = "grid",
                 part: tuple[int, int] | None = None) -> dict:
    """Score one volcomp scroll volume. Returns a result dict.

    ``rotate`` cyclically shifts the shard-candidate order, giving a
    different deterministic sample for stability checks. ``spread`` is the
    per-dimension candidate count (spread^3 candidates); 3 gives 27,
    5 gives 125. Denser spreads find more present shards on sparse
    volumes, at the cost of more candidate probes.

    ``exclude`` is a set of chunk identities (``shard_key#inner_flat``, as
    recorded in ``sample_provenance``) that must not be read. Passing a
    previous run's identities forces a chunk-disjoint resample; the run
    may then decode fewer than ``samples`` chunks, which ``sampling``
    reports. ``None`` (the default) leaves sampling unchanged.

    ``order`` and ``part`` select the candidate order (see ``_candidates``).
    The defaults reproduce every published campaign exactly.
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
    shard_index_invalid = 0
    chunk_read_failures = 0
    chunk_decode_failures = 0
    excluded_chunks = 0
    # Spread shard candidates per-dimension (flat-index spread degenerates
    # to an edge line on non-cubic grids). Skip shards that are nearly
    # all mask so the score reflects the scroll body, not the background.
    try:
        cands = _candidates(shard_grid, spread, rotate, order, part)
    except ValueError as exc:
        result["error"] = str(exc)
        return result
    if rotate:
        # Record rotate normalised over the full lattice, as before.
        rotate %= max(1, len(_candidates(shard_grid, spread)))
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
        except Exception:
            shard_read_failures += 1
            continue
        raw_index, index_state, _index_error = _read_shard_index(
            store, skey, idx_size
        )
        if index_state == "missing":
            missing_shards += 1
            continue
        if index_state == "read-failure" or raw_index is None:
            shard_read_failures += 1
            continue
        entries = vc.parse_index(raw_index, n_inner, info.index_codecs)
        if not entries:
            # parse_index returns None on a structurally invalid index.
            # That is not "masked background": count it, don't drop it.
            shard_index_invalid += 1
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
            if exclude is not None and f"{skey}#{flat_i}" in exclude:
                excluded_chunks += 1
                continue
            try:
                blob = store.get_range(skey, off, ln)
            except Exception:
                chunk_read_failures += 1
                continue
            raw = vc.decode_chunk(blob)
            if raw is None:
                chunk_decode_failures += 1
                continue
            try:
                vox = np.frombuffer(raw, dtype=np.uint8).reshape(
                    (info.inner_chunks[0], info.inner_chunks[1],
                     info.inner_chunks[2]))
            except ValueError:
                # The decoder always yields 128^3 bytes; any other inner
                # chunk shape cannot be interpreted. Same handling as
                # scan_map: a decode failure, not a crash.
                chunk_decode_failures += 1
                continue
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
        "shard_index_invalid": shard_index_invalid,
        "chunk_read_failures": chunk_read_failures,
        "chunk_decode_failures": chunk_decode_failures,
    }
    if exclude is not None:
        sampling["excluded_chunks"] = excluded_chunks
    if order != "grid":
        sampling["order"] = order
    if part is not None:
        sampling["part"] = list(part)
    result["sampling"] = sampling
    # Provenance: stable identity per decoded chunk. Enables verifying
    # that two runs actually sampled disjoint chunks (not just disjoint
    # candidate order).
    result["sample_provenance"] = chunk_provenance
    if not chunk_results:
        result["error"] = (f"no chunks decoded "
                           f"({missing_shards} shards absent, "
                           f"{shard_read_failures} shard read failures, "
                           f"{shard_index_invalid} shard index invalid, "
                           f"{chunk_read_failures} chunk read failures, "
                           f"{chunk_decode_failures} chunk decode failures)")
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
        "components": {k: round(v, 1)
                       for k, v in score_components(agg).items()},
        "metrics": {k: round(v, 4) if isinstance(v, float) else v
                    for k, v in agg.items()},
    })
    return result
