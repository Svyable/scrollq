"""Deterministic spatial scan diagnostics for Vesuvius volcomp volumes.

Unlike the legacy ScrolIQ volume score, this module preserves where each
measurement came from. Missing shards, sparse/background shards, read failures,
and decoded chunks all remain visible in the output so local scan condition is
not collapsed into one number.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from zpa.httpstore import open_store
from zpa import volcomp as vc

from .metrics import chunk_metrics
from .score import _spread

SCHEMA_VERSION = "1.0"
OPEN_PROBLEM = "scan-diagnostics"


def _flat_to_coord(flat_i: int, shape: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    coord: list[int] = []
    rem = flat_i
    for size in reversed(shape):
        coord.append(rem % size)
        rem //= size
    return tuple(reversed(coord))


def _bbox(start: list[int], stop: list[int]) -> dict[str, list[int]]:
    return {"start": start, "stop": stop}


def _metric_distribution(chunks: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    keys = ("nonzero_frac", "grad_energy", "dyn_range", "sat_frac")
    out: dict[str, dict[str, float]] = {}
    for key in keys:
        values = np.asarray(
            [float(c["metrics"][key]) for c in chunks if key in c["metrics"]],
            dtype=np.float64,
        )
        if values.size == 0:
            continue
        out[key] = {
            "min": round(float(values.min()), 6),
            "p10": round(float(np.percentile(values, 10)), 6),
            "median": round(float(np.median(values)), 6),
            "p90": round(float(np.percentile(values, 90)), 6),
            "max": round(float(values.max()), 6),
        }
    return out


def scan_volume_map(
    base_url: str,
    root: str,
    *,
    grid: int = 3,
    chunks_per_shard: int = 1,
    rotate: int = 0,
) -> dict[str, Any]:
    """Survey spatially distributed L0 shards and retain coordinate provenance.

    grid selects up to that many shard coordinates independently on each
    dimension. chunks_per_shard selects present inner chunks spread through
    each sampled shard. The output intentionally has no aggregate readiness
    score.
    """
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": "spatial-scan-map",
        "open_problem": OPEN_PROBLEM,
        "root": root,
        "base_url": base_url,
        "ok": False,
    }
    if grid < 1:
        result["error"] = "grid must be >= 1"
        return result
    if chunks_per_shard < 1:
        result["error"] = "chunks_per_shard must be >= 1"
        return result

    store = open_store(base_url)
    available, reason = vc.available()
    if not available:
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

    shard_grid = tuple(
        max(1, (size + outer - 1) // outer)
        for size, outer in zip(info.shape, info.outer_chunks)
    )
    candidates = [
        (x, y, z)
        for x in _spread(shard_grid[0], grid)
        for y in _spread(shard_grid[1], grid)
        for z in _spread(shard_grid[2], grid)
    ]
    if rotate:
        rotate %= max(1, len(candidates))
        candidates = candidates[rotate:] + candidates[:rotate]

    records: list[dict[str, Any]] = []
    decoded_chunks: list[dict[str, Any]] = []
    sess = store._session()

    for shard_coord in candidates:
        shard_start = [
            shard_coord[d] * info.outer_chunks[d]
            for d in range(3)
        ]
        shard_stop = [
            min(shard_start[d] + info.outer_chunks[d], info.shape[d])
            for d in range(3)
        ]
        record: dict[str, Any] = {
            "shard_coord": list(shard_coord),
            "shard_voxel_bbox": _bbox(shard_start, shard_stop),
            "status": "pending",
            "chunks": [],
        }

        shard_key = vc.shard_key(root, "0", shard_coord)
        cps = vc.inner_chunks_per_shard(info, shard_coord)
        n_inner = int(np.prod(cps))

        try:
            index_size = vc.index_encoded_size(n_inner, info.index_codecs)
            response = sess.get(
                f"{base_url}/{shard_key}",
                headers={"Range": f"bytes=-{index_size}"},
                timeout=60,
            )
            if response.status_code == 404:
                record["status"] = "unstored-shard"
                records.append(record)
                continue
            response.raise_for_status()
            raw_index = (
                response.content[-index_size:]
                if response.status_code == 200
                else response.content
            )
            entries = vc.parse_index(raw_index, n_inner, info.index_codecs)
        except Exception as exc:
            record["status"] = "read-failure"
            record["error"] = str(exc)
            records.append(record)
            continue

        if not entries:
            record["status"] = "empty-index"
            records.append(record)
            continue

        present_indices = [
            i for i, (offset, _length) in enumerate(entries)
            if offset != vc.MISSING
        ]
        present_frac = len(present_indices) / n_inner if n_inner else 0.0
        record["present_frac"] = round(present_frac, 6)

        if present_frac < 0.05:
            record["status"] = "sparse-mask"
            records.append(record)
            continue

        selected_positions = _spread(
            len(present_indices), min(chunks_per_shard, len(present_indices))
        )
        selected_indices = [present_indices[i] for i in selected_positions]

        decode_failures = 0
        for flat_i in selected_indices:
            inner_coord = _flat_to_coord(flat_i, cps)
            offset, length = entries[flat_i]
            try:
                blob = store.get_range(shard_key, offset, length)
                raw = vc.decode_chunk(blob)
                if raw is None:
                    decode_failures += 1
                    continue
                vox = np.frombuffer(raw, dtype=np.uint8).reshape(
                    (
                        info.inner_chunks[0],
                        info.inner_chunks[1],
                        info.inner_chunks[2],
                    )
                )
            except Exception:
                decode_failures += 1
                continue

            global_chunk_coord = [
                shard_coord[d] * (info.outer_chunks[d] // info.inner_chunks[d])
                + inner_coord[d]
                for d in range(3)
            ]
            voxel_start = [
                global_chunk_coord[d] * info.inner_chunks[d]
                for d in range(3)
            ]
            voxel_stop = [
                min(voxel_start[d] + info.inner_chunks[d], info.shape[d])
                for d in range(3)
            ]
            vox = vox[
                : voxel_stop[0] - voxel_start[0],
                : voxel_stop[1] - voxel_start[1],
                : voxel_stop[2] - voxel_start[2],
            ]
            chunk = {
                "inner_coord": list(inner_coord),
                "global_chunk_coord": global_chunk_coord,
                "voxel_bbox": _bbox(voxel_start, voxel_stop),
                "metrics": chunk_metrics(vox),
            }
            record["chunks"].append(chunk)
            decoded_chunks.append(chunk)

        record["decode_failures"] = decode_failures
        if record["chunks"]:
            record["status"] = "decoded"
        else:
            record["status"] = "decode-failure"
        records.append(record)

    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    result.update(
        {
            "ok": bool(decoded_chunks),
            "coordinate_space": "level0-voxel-index",
            "volume_shape": list(info.shape),
            "inner_chunk_shape": list(info.inner_chunks),
            "outer_shard_shape": list(info.outer_chunks),
            "shard_grid": list(shard_grid),
            "sampling": {
                "grid_per_dimension": grid,
                "chunks_per_shard": chunks_per_shard,
                "rotate": rotate,
                "candidate_shards": len(candidates),
                "chunks_decoded": len(decoded_chunks),
                "status_counts": status_counts,
            },
            "metric_distribution": _metric_distribution(decoded_chunks),
            "regions": records,
            "absence_semantics": (
                "An unstored shard is expected for masked background and is not "
                "evidence of corruption by itself."
            ),
            "interpretation": (
                "Measurements are local sampled CT diagnostics. Unstored, sparse, "
                "or failed regions are retained explicitly. No readability, surface "
                "correctness, ink-presence, or Grand Prize readiness score is inferred."
            ),
        }
    )
    if not decoded_chunks:
        result["error"] = "no chunks decoded from sampled shards"
    return result


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build a deterministic spatial scan-diagnostic map"
    )
    ap.add_argument("--base", default="https://dl.ash2txt.org")
    ap.add_argument("--root", required=True)
    ap.add_argument("--grid", type=int, default=3)
    ap.add_argument("--chunks-per-shard", type=int, default=1)
    ap.add_argument("--rotate", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    report = scan_volume_map(
        args.base,
        args.root,
        grid=args.grid,
        chunks_per_shard=args.chunks_per_shard,
        rotate=args.rotate,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({report.get('sampling', {}).get('chunks_decoded', 0)} chunks)")


if __name__ == "__main__":
    main()
