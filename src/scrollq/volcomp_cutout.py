from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from zpa import volcomp as vc
from zpa.httpstore import open_store
from zpa.report import audit_root


TOOL = "scroliq-volcomp-cutout"
SCHEMA_VERSION = 1


class CutoutError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _triplet(value: Any, name: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise ValueError(f"{name} must contain exactly three integers in Z,Y,X order")
    return int(value[0]), int(value[1]), int(value[2])


def _flatten_index(coord: tuple[int, int, int], dims: tuple[int, int, int]) -> int:
    z, y, x = coord
    dz, dy, dx = dims
    if not (0 <= z < dz and 0 <= y < dy and 0 <= x < dx):
        raise IndexError(f"inner chunk {coord} outside shard grid {dims}")
    return (z * dy + y) * dx + x


def _inner_location(
    info: vc.ShardingInfo, global_chunk: tuple[int, int, int]
) -> tuple[tuple[int, int, int], tuple[int, int, int], int]:
    per_outer = tuple(
        o // i for o, i in zip(info.outer_chunks, info.inner_chunks)
    )
    if any(v <= 0 for v in per_outer):
        raise CutoutError("outer chunk shape must be an integer multiple of inner chunk shape")
    shard = tuple(g // p for g, p in zip(global_chunk, per_outer))
    inner = tuple(g - s * p for g, s, p in zip(global_chunk, shard, per_outer))
    dims = vc.inner_chunks_per_shard(info, shard)
    flat = _flatten_index(inner, dims)
    return shard, inner, flat


def _read_index(store, root: str, info: vc.ShardingInfo, shard: tuple[int, int, int]):
    key = vc.shard_key(root, "0", shard)
    head = store.head(key)
    if not head.exists:
        if head.status == 404:
            return key, None
        raise CutoutError(
            f"cannot establish shard existence for {key}: {head.error or head.status}"
        )

    dims = vc.inner_chunks_per_shard(info, shard)
    count = int(np.prod(dims))
    try:
        encoded = store.get_suffix(
            key, vc.index_encoded_size(count, info.index_codecs)
        )
    except Exception as exc:
        raise CutoutError(f"cannot read shard index for {key}: {exc}") from exc

    checksum = vc.verify_index_checksum(encoded, info.index_codecs)
    if checksum is False:
        raise CutoutError(f"CRC32C mismatch in shard index for {key}")
    entries = vc.parse_index(encoded, count, info.index_codecs)
    if entries is None:
        raise CutoutError(f"invalid shard index for {key}")
    return key, entries


def read_box(
    store,
    root: str,
    lo_zyx: tuple[int, int, int],
    hi_zyx: tuple[int, int, int],
    *,
    decoder: Callable[[bytes], bytes | None] = vc.decode_chunk,
) -> tuple[np.ndarray, dict[str, Any]]:
    lo = _triplet(lo_zyx, "lo_zyx")
    hi = _triplet(hi_zyx, "hi_zyx")

    meta = store.get_json(f"{root.rstrip('/')}/0/zarr.json")
    if meta.get("data_type") != "uint8":
        raise CutoutError(f"expected uint8 level-0 data, got {meta.get('data_type')!r}")
    fill = meta.get("fill_value", 0)
    if isinstance(fill, bool) or not isinstance(fill, int) or not 0 <= fill <= 255:
        raise CutoutError(f"unsupported fill_value {fill!r}; expected integer uint8")

    info = vc.parse_zarr_json(meta)
    if info is None or info.inner_codec != "volcomp":
        raise CutoutError("level 0 is not a volcomp sharding_indexed array")
    if len(info.shape) != 3:
        raise CutoutError("level 0 must be three-dimensional")
    if tuple(int(v) for v in meta.get("shape", [])) != tuple(info.shape):
        raise CutoutError("zarr metadata shape is inconsistent")

    ok, reason = vc.available()
    if decoder is vc.decode_chunk and not ok:
        raise CutoutError(f"volcomp decoder unavailable: {reason}")

    clipped_lo = tuple(max(0, v) for v in lo)
    clipped_hi = tuple(min(int(s), v) for s, v in zip(info.shape, hi))
    if any(h <= l for l, h in zip(clipped_lo, clipped_hi)):
        raise CutoutError("requested box has no overlap with the array")

    shape = tuple(h - l for l, h in zip(clipped_lo, clipped_hi))
    voxels = int(np.prod(shape))
    if voxels > 256**3:
        raise CutoutError(f"requested box {shape} exceeds 256^3 voxels")
    out = np.full(shape, fill, dtype=np.uint8)

    inner = tuple(int(v) for v in info.inner_chunks)
    c0 = tuple(l // c for l, c in zip(clipped_lo, inner))
    c1 = tuple((h - 1) // c for h, c in zip(clipped_hi, inner))

    index_cache: dict[tuple[int, int, int], tuple[str, list[tuple[int, int]] | None]] = {}
    present_chunks = 0
    missing_chunks = 0
    decoded_bytes = 0
    shard_count: set[tuple[int, int, int]] = set()

    for gz in range(c0[0], c1[0] + 1):
        for gy in range(c0[1], c1[1] + 1):
            for gx in range(c0[2], c1[2] + 1):
                global_chunk = (gz, gy, gx)
                shard, _inner_coord, flat = _inner_location(info, global_chunk)
                shard_count.add(shard)
                if shard not in index_cache:
                    index_cache[shard] = _read_index(store, root.rstrip("/"), info, shard)
                shard_key, entries = index_cache[shard]
                if entries is None:
                    missing_chunks += 1
                    continue
                off, length = entries[flat]
                if off == vc.MISSING and length == vc.MISSING:
                    missing_chunks += 1
                    continue
                if off == vc.MISSING or length == vc.MISSING:
                    raise CutoutError(f"partially missing shard-index entry for {shard_key}#{flat}")
                try:
                    blob = store.get_range(shard_key, int(off), int(length))
                except Exception as exc:
                    raise CutoutError(
                        f"cannot read volcomp chunk {shard_key}#{flat}: {exc}"
                    ) from exc
                raw = decoder(blob)
                if raw is None:
                    raise CutoutError(f"volcomp decode failed for {shard_key}#{flat}")
                expected = int(np.prod(inner))
                if len(raw) != expected:
                    raise CutoutError(
                        f"decoded chunk {shard_key}#{flat} has {len(raw)} bytes; "
                        f"expected {expected}"
                    )
                chunk = np.frombuffer(raw, dtype=np.uint8).reshape(inner)
                present_chunks += 1
                decoded_bytes += len(raw)

                chunk_lo = tuple(g * c for g, c in zip(global_chunk, inner))
                chunk_hi = tuple(
                    min(int(s), l + c)
                    for s, l, c in zip(info.shape, chunk_lo, inner)
                )
                overlap_lo = tuple(max(a, b) for a, b in zip(clipped_lo, chunk_lo))
                overlap_hi = tuple(min(a, b) for a, b in zip(clipped_hi, chunk_hi))
                if any(h <= l for l, h in zip(overlap_lo, overlap_hi)):
                    continue

                oz0, oy0, ox0 = (overlap_lo[i] - clipped_lo[i] for i in range(3))
                oz1, oy1, ox1 = (overlap_hi[i] - clipped_lo[i] for i in range(3))
                cz0, cy0, cx0 = (overlap_lo[i] - chunk_lo[i] for i in range(3))
                cz1, cy1, cx1 = (overlap_hi[i] - chunk_lo[i] for i in range(3))
                out[oz0:oz1, oy0:oy1, ox0:ox1] = chunk[
                    cz0:cz1, cy0:cy1, cx0:cx1
                ]

    return out, {
        "requested_lo_zyx": list(lo),
        "requested_hi_zyx": list(hi),
        "clipped_lo_zyx": list(clipped_lo),
        "clipped_hi_zyx": list(clipped_hi),
        "shape_zyx": list(shape),
        "fill_value": int(fill),
        "shards_touched": len(shard_count),
        "chunks_present": present_chunks,
        "chunks_missing": missing_chunks,
        "decoded_bytes": decoded_bytes,
    }


def extract(
    *,
    base_url: str,
    root: str,
    lo_zyx: tuple[int, int, int],
    hi_zyx: tuple[int, int, int],
    out_path: str | Path,
    store=None,
) -> dict[str, Any]:
    out_path = Path(out_path)
    if out_path.suffix.lower() != ".npy":
        raise ValueError("--out must end in .npy")
    report_path = out_path.with_suffix(".json")
    if out_path.exists() or report_path.exists():
        raise ValueError("refusing to overwrite existing cutout or report")

    store = store or open_store(base_url)
    audit = audit_root(store, root)
    if audit.get("integrity") != "PASS":
        raise CutoutError(
            f"source volume integrity is {audit.get('integrity')}; refusing cutout"
        )
    attestation = audit.get("source_attestation")
    if not isinstance(attestation, dict):
        raise CutoutError("source audit lacks source_attestation")
    if (
        attestation.get("algorithm") != "zpa-metadata-semantics-v1"
        or attestation.get("state") != "PRESENT"
        or not isinstance(attestation.get("metadata_semantics_sha256"), str)
    ):
        raise CutoutError("source metadata attestation is not PRESENT and hash-bound")

    array, stats = read_box(store, root, lo_zyx, hi_zyx)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, array, allow_pickle=False)
    output_sha = _sha256_file(out_path)

    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "base_url": base_url,
        "root": root.rstrip("/"),
        "source_integrity": audit.get("integrity"),
        "source_schema_version": audit.get("schema_version"),
        "source_tool_version": audit.get("tool_version"),
        "source_attestation": attestation,
        "box": stats,
        "output": {
            "path": str(out_path),
            "sha256": output_sha,
            "dtype": str(array.dtype),
            "shape_zyx": [int(v) for v in array.shape],
            "min": int(array.min()),
            "max": int(array.max()),
            "nonzero_fraction": float(np.count_nonzero(array) / array.size),
        },
        "claim_boundary": (
            "This artifact proves a deterministic byte-level cutout from the declared "
            "volcomp level-0 object graph under the recorded ZPA metadata attestation. "
            "It does not establish that a supplied surface coordinate is correct."
        ),
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _parse_triplet(text: str) -> tuple[int, int, int]:
    parts = text.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected comma-separated z,y,x")
    try:
        values = tuple(int(v.strip()) for v in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("z,y,x must be integers") from exc
    return values  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract an exact hash-pinned L0 cutout from a volcomp Zarr v3 volume"
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--base", default="https://dl.ash2txt.org")
    parser.add_argument("--lo", type=_parse_triplet, required=True, help="z,y,x inclusive")
    parser.add_argument("--hi", type=_parse_triplet, required=True, help="z,y,x exclusive")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = extract(
            base_url=args.base,
            root=args.root,
            lo_zyx=args.lo,
            hi_zyx=args.hi,
            out_path=args.out,
        )
    except (OSError, ValueError, CutoutError) as exc:
        raise SystemExit(f"{TOOL}: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
