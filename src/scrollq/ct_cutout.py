"""Extract a bounded, provenance-bound level-0 CT cutout for local experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import requests

from zpa.report import validate_report as validate_zpa_report

from .support import ZarrV2Level


SCHEMA = "scroliq-ct-cutout/1"


class CutoutError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _triplet(value: Any, name: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise CutoutError(f"{name} must contain exactly three integer ZYX coordinates")
    return int(value[0]), int(value[1]), int(value[2])


def _parse_triplet(text: str) -> tuple[int, int, int]:
    try:
        values = tuple(int(part.strip()) for part in text.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("coordinate must be Z,Y,X integers") from exc
    if len(values) != 3:
        raise argparse.ArgumentTypeError("coordinate must be Z,Y,X integers")
    return values  # type: ignore[return-value]


def _verify_zpa_report(
    report: dict[str, Any],
    *,
    volume_root: str,
    validate_report_fn: Callable[[dict[str, Any]], list[str]] = validate_zpa_report,
) -> tuple[dict[str, Any], dict[str, Any]]:
    errors = validate_report_fn(report)
    if errors:
        raise CutoutError("ZPA report fails schema validation: " + "; ".join(errors[:3]))
    if report.get("tool") != "zarr-pyramid-audit":
        raise CutoutError("ZPA report tool must be zarr-pyramid-audit")
    if report.get("root") != volume_root:
        raise CutoutError("ZPA report root does not exactly match volume_root")
    if report.get("integrity") != "PASS":
        raise CutoutError(f"ZPA report integrity must be PASS, got {report.get('integrity')!r}")

    attestation = report.get("source_attestation")
    if not isinstance(attestation, dict):
        raise CutoutError("ZPA report source_attestation is required")
    if attestation.get("algorithm") != "zpa-metadata-semantics-v1":
        raise CutoutError("ZPA source attestation algorithm mismatch")
    if attestation.get("state") != "PRESENT":
        raise CutoutError("ZPA source attestation state must be PRESENT")
    digest = attestation.get("metadata_semantics_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise CutoutError("ZPA source metadata_semantics_sha256 must be lowercase 64-hex")
    if attestation.get("axes") != ["z", "y", "x"]:
        raise CutoutError(
            "level-0 cutout extraction requires audited source axes exactly ['z', 'y', 'x']"
        )

    levels = report.get("levels")
    if not isinstance(levels, list):
        raise CutoutError("ZPA report levels must be a list")
    base = [row for row in levels if isinstance(row, dict) and row.get("index") == 0]
    if len(base) != 1:
        raise CutoutError("ZPA report must contain exactly one level with index 0")
    row = base[0]
    shape = _triplet(row.get("shape"), "ZPA level-0 shape")
    chunks = _triplet(row.get("chunks"), "ZPA level-0 chunks")
    dtype = row.get("dtype")
    if not isinstance(dtype, str) or not dtype:
        raise CutoutError("ZPA level-0 dtype is required")

    return dict(attestation), {
        "path": row.get("path"),
        "shape_zyx": list(shape),
        "chunks_zyx": list(chunks),
        "dtype": dtype,
    }


def _validate_bbox(
    start: tuple[int, int, int],
    stop: tuple[int, int, int],
    shape: tuple[int, int, int],
) -> None:
    if any(v < 0 for v in start):
        raise CutoutError("cutout start must be non-negative")
    if any(a >= b for a, b in zip(start, stop)):
        raise CutoutError("cutout requires start < stop on every axis")
    if any(stop[d] > shape[d] for d in range(3)):
        raise CutoutError(f"cutout stop {list(stop)} exceeds source shape {list(shape)}")


def extract_from_level(
    level: Any,
    *,
    start_zyx: tuple[int, int, int],
    stop_zyx: tuple[int, int, int],
) -> tuple[np.ndarray, list[list[int]]]:
    """Extract one half-open global ZYX box, failing closed on missing chunks."""
    shape = _triplet(level.shape, "source shape")
    chunks = _triplet(level.chunks, "source chunks")
    _validate_bbox(start_zyx, stop_zyx, shape)

    out_shape = tuple(stop_zyx[d] - start_zyx[d] for d in range(3))
    out = np.empty(out_shape, dtype=np.uint8)
    touched: list[list[int]] = []

    ranges = [
        range(start_zyx[d] // chunks[d], (stop_zyx[d] - 1) // chunks[d] + 1)
        for d in range(3)
    ]
    for cz in ranges[0]:
        for cy in ranges[1]:
            for cx in ranges[2]:
                coord = (cz, cy, cx)
                chunk = level.chunk(coord)
                touched.append([cz, cy, cx])
                if chunk is None:
                    raise CutoutError(
                        f"source chunk {coord} is missing; refusing implicit fill values"
                    )
                chunk = np.asarray(chunk)
                if chunk.ndim != 3:
                    raise CutoutError(f"source chunk {coord} is not 3-D")
                c0 = tuple(coord[d] * chunks[d] for d in range(3))
                c1 = tuple(c0[d] + chunk.shape[d] for d in range(3))
                lo = tuple(max(start_zyx[d], c0[d]) for d in range(3))
                hi = tuple(min(stop_zyx[d], c1[d]) for d in range(3))
                if any(lo[d] >= hi[d] for d in range(3)):
                    continue
                source_slices = tuple(
                    slice(lo[d] - c0[d], hi[d] - c0[d]) for d in range(3)
                )
                dest_slices = tuple(
                    slice(lo[d] - start_zyx[d], hi[d] - start_zyx[d])
                    for d in range(3)
                )
                out[dest_slices] = chunk[source_slices]

    return out, touched


def run(
    *,
    ct_url: str,
    volume_root: str,
    zpa_report_path: str | Path,
    start_zyx: tuple[int, int, int],
    stop_zyx: tuple[int, int, int],
    out_path: str | Path,
    manifest_path: str | Path,
    session: Any | None = None,
    level_factory: Callable[[str, Any], Any] = ZarrV2Level,
    validate_report_fn: Callable[[dict[str, Any]], list[str]] = validate_zpa_report,
) -> dict[str, Any]:
    volume_root = volume_root.strip("/")
    ct_url = ct_url.rstrip("/")
    if not volume_root:
        raise CutoutError("volume_root must be non-empty")
    if not ct_url.startswith(("https://", "http://")):
        raise CutoutError("ct_url must be public http(s)")
    if not ct_url.endswith("/" + volume_root):
        raise CutoutError("ct_url must end with the exact volume_root")

    out_path = Path(out_path)
    manifest_path = Path(manifest_path)
    if out_path.exists():
        raise CutoutError(f"refusing to overwrite existing cutout: {out_path}")
    if manifest_path.exists():
        raise CutoutError(f"refusing to overwrite existing manifest: {manifest_path}")

    zpa_report_path = Path(zpa_report_path)
    try:
        report = json.loads(zpa_report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoutError(f"cannot read ZPA report: {exc}") from exc
    if not isinstance(report, dict):
        raise CutoutError("ZPA report must contain a JSON object")

    attestation, audited_level = _verify_zpa_report(
        report,
        volume_root=volume_root,
        validate_report_fn=validate_report_fn,
    )

    owned_session = session is None
    sess = requests.Session() if session is None else session
    try:
        level = level_factory(f"{ct_url}/0", sess)
        shape = _triplet(level.shape, "live source shape")
        chunks = _triplet(level.chunks, "live source chunks")
        dtype = "|u1"
        if list(shape) != audited_level["shape_zyx"]:
            raise CutoutError(
                f"live source shape {list(shape)} != audited {audited_level['shape_zyx']}"
            )
        if list(chunks) != audited_level["chunks_zyx"]:
            raise CutoutError(
                f"live source chunks {list(chunks)} != audited {audited_level['chunks_zyx']}"
            )
        if audited_level["dtype"] != dtype:
            raise CutoutError(
                f"audited level-0 dtype {audited_level['dtype']!r} != extractor dtype {dtype!r}"
            )
        array, touched = extract_from_level(
            level,
            start_zyx=start_zyx,
            stop_zyx=stop_zyx,
        )
    finally:
        if owned_session and hasattr(sess, "close"):
            sess.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("xb") as handle:
        np.save(handle, array, allow_pickle=False)
    array_sha = sha256_file(out_path)

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "measured",
        "volume_root": volume_root,
        "ct_url": ct_url,
        "level": 0,
        "coordinate_space": "level0-voxel-index",
        "source_attestation": attestation,
        "zpa_report": {
            "path": str(zpa_report_path),
            "sha256": sha256_file(zpa_report_path),
            "schema_version": report.get("schema_version"),
            "integrity": report.get("integrity"),
        },
        "source_array": audited_level,
        "bbox_zyx_half_open": {
            "start": list(start_zyx),
            "stop": list(stop_zyx),
        },
        "local_to_global": {
            "kind": "integer-translation",
            "start_zyx": list(start_zyx),
            "definition": "global_zyx = local_zyx + start_zyx",
        },
        "source_chunks": {
            "count": len(touched),
            "touched_zyx": touched,
            "missing_count": 0,
        },
        "cutout": {
            "path": str(out_path),
            "shape_zyx": [int(v) for v in array.shape],
            "dtype": str(array.dtype),
            "sha256": array_sha,
        },
        "claim_boundary": (
            "This manifest binds one local NumPy cutout to an exact audited level-0 "
            "ZYX box and records every touched source chunk. It does not establish "
            "papyrus sheet identity, topology, ink, or readability."
        ),
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ct-url", required=True)
    parser.add_argument("--volume-root", required=True)
    parser.add_argument("--zpa-report", required=True)
    parser.add_argument("--start", type=_parse_triplet, required=True, metavar="Z,Y,X")
    parser.add_argument("--stop", type=_parse_triplet, required=True, metavar="Z,Y,X")
    parser.add_argument("--out", required=True, help="new .npy path; refuses overwrite")
    parser.add_argument("--manifest", required=True, help="new JSON path; refuses overwrite")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(
            ct_url=args.ct_url,
            volume_root=args.volume_root,
            zpa_report_path=args.zpa_report,
            start_zyx=args.start,
            stop_zyx=args.stop,
            out_path=args.out,
            manifest_path=args.manifest,
        )
    except (CutoutError, requests.RequestException, OSError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
