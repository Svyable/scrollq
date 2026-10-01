"""Audit declared-vs-stored chunk sizes of uncompressed OME-Zarr v2 volumes.

An uncompressed Zarr v2 array stores every chunk as exactly
``prod(chunks) * itemsize`` bytes, edge chunks included. Any other object size
under an array's key prefix means the data and the ``.zarray`` metadata
disagree and a strict reader cannot decode that chunk. S3 listings carry
object sizes, so the check needs no chunk downloads.

Fail-closed rules:

* a level where **no chunk object was checked** is ``unverified``, never
  ``ok`` (an audit that inspected nothing proves nothing);
* compressed/filtered arrays are ``not_applicable`` (sizes legitimately vary);
* the CLI exits non-zero on any mismatch or unverified level;
* **absent is not unavailable.** ``fetch`` returns ``None`` only for an HTTP
  404 and raises ``OSError`` for anything else (network failure, 5xx, 403).
  An unavailable object leaves its volume or level ``unverified`` with an
  ``unavailable:`` detail; it is never read as "missing" or as "corrupt".

A ``mismatch`` is an *observation* that stored object sizes contradict the
declared chunk shape. It does not establish a cause or how any particular
reader behaves.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .protocol_pairs import BUCKET_S3, BUCKET_URL, DEFAULT_INDEX, \
    _seed_for, load_json_maybe_gz

SCHEMA_VERSION = 1
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_ITEMSIZE = {"|u1": 1, "<u1": 1, "u1": 1, "|i1": 1, "<u2": 2, "<i2": 2,
             "<f4": 4, "<f8": 8}


def parse_listing(xml: bytes) -> tuple[list[tuple[str, int]], str | None]:
    """Parse an S3 ListObjectsV2 response into ``([(key, size)], token)``.

    Uses a real XML parser: S3 inserts optional elements (checksums, storage
    class) between ``ETag`` and ``Size`` that break regex extraction.
    """
    root = ET.fromstring(xml)
    entries = []
    for c in root.findall(f"{_NS}Contents"):
        key = c.find(f"{_NS}Key")
        size = c.find(f"{_NS}Size")
        if key is None or size is None or key.text is None:
            raise ValueError("listing entry without Key/Size")
        entries.append((key.text, int(size.text)))
    token = root.find(f"{_NS}NextContinuationToken")
    return entries, (token.text if token is not None else None)


def classify_level(declared_chunks, dtype, compressor, filters,
                   entries: list[tuple[str, int]]) -> dict:
    """Judge one level from the sampled ``(key, size)`` listing entries."""
    out: dict = {"declared_chunks": list(declared_chunks), "dtype": dtype}
    if compressor is not None or filters:
        out.update(status="not_applicable",
                   detail="compressed or filtered chunks vary in size")
        return out
    item = _ITEMSIZE.get(dtype)
    if item is None:
        out.update(status="not_applicable", detail=f"unknown dtype {dtype!r}")
        return out
    expected = int(math.prod(declared_chunks)) * item
    chunks = [(k, s) for k, s in entries
              if not k.rsplit("/", 1)[-1].startswith(".")]
    out.update(expected_bytes=expected, n_checked=len(chunks))
    if not chunks:
        out.update(status="unverified",
                   detail="no chunk objects were checked")
        return out
    sizes = Counter(s for _, s in chunks)
    bad = [(k, s) for k, s in chunks if s != expected]
    out["size_histogram"] = {str(k): v for k, v in sorted(sizes.items())}
    out["n_mismatch"] = len(bad)
    out["status"] = "mismatch" if bad else "ok"
    if bad:
        out["examples"] = [{"key": k, "size": s,
                            "ratio_to_expected": s / expected}
                           for k, s in bad[:5]]
    return out


def _list_page(fetch, bucket_url, prefix, *, max_keys, token=None,
               start_after=None):
    q = {"list-type": "2", "prefix": prefix, "max-keys": str(max_keys)}
    if token:
        q["continuation-token"] = token
    if start_after:
        q["start-after"] = start_after
    raw = fetch(f"{bucket_url}/?{urllib.parse.urlencode(q)}")
    if raw is None:
        raise OSError(f"listing failed for {prefix}")
    return parse_listing(raw)


def collect_entries(fetch, bucket_url, prefix, grid_z, *, full=False,
                    head_pages=2, random_pages=6, seed=0, page_keys=1000):
    """Sample (or, with ``full``, enumerate) the chunk objects of one level."""
    seen: dict[str, int] = {}
    token = None
    pages = 0
    while True:
        entries, token = _list_page(fetch, bucket_url, prefix,
                                    max_keys=page_keys, token=token)
        seen.update(entries)
        pages += 1
        if token is None or (not full and pages >= head_pages):
            break
    if not full and token is not None and grid_z > 0:
        rng = np.random.default_rng(seed)
        zs = rng.choice(grid_z, size=min(random_pages, grid_z), replace=False)
        for z in sorted(int(v) for v in zs):
            entries, _ = _list_page(fetch, bucket_url, prefix,
                                    max_keys=page_keys // 2,
                                    start_after=f"{prefix}{z}/")
            seen.update(entries)
            pages += 1
    return sorted(seen.items()), pages


def _get(fetch, url: str):
    """``(bytes | None, detail | None)``: absent -> (None, None); unavailable
    -> (None, 'unavailable: ...')."""
    try:
        return fetch(url), None
    except OSError as exc:
        return None, f"unavailable: {exc}"


def audit_volume(fetch, bucket_url, path, *, full=False, seed=0) -> dict:
    out: dict = {"path": path, "levels": []}
    raw, unavailable = _get(fetch, f"{bucket_url}/{path}.zattrs")
    if unavailable:
        out["error"] = f".zattrs {unavailable}"
        return out
    if raw is None:
        out["error"] = ".zattrs not found"
        return out
    try:
        datasets = json.loads(raw)["multiscales"][0]["datasets"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        out["error"] = f"unusable .zattrs: {exc}"
        return out
    for ds in datasets:
        level = ds["path"]
        za_raw, unavailable = _get(fetch, f"{bucket_url}/{path}{level}/.zarray")
        if unavailable or za_raw is None:
            out["levels"].append({
                "level": level, "status": "unverified",
                "detail": (f".zarray {unavailable}" if unavailable
                           else ".zarray not found")})
            continue
        try:
            za = json.loads(za_raw)
            grid_z = -(-za["shape"][0] // za["chunks"][0])
            za_chunks, za_dtype = za["chunks"], za["dtype"]
        except (KeyError, IndexError, ValueError, TypeError,
                ZeroDivisionError) as exc:
            out["levels"].append({"level": level, "status": "unverified",
                                  "detail": f"unusable .zarray: {exc}"})
            continue
        try:
            entries, pages = collect_entries(
                fetch, bucket_url, f"{path}{level}/", grid_z, full=full,
                seed=_seed_for(seed, path, level))
        except (OSError, ValueError) as exc:
            out["levels"].append({
                "level": level, "status": "unverified",
                "detail": f"listing unavailable or unparsable: {exc}"})
            continue
        res = classify_level(za_chunks, za_dtype, za.get("compressor"),
                             za.get("filters"), entries)
        res.update(level=level, pages_listed=pages,
                   mode="full" if full else "sampled")
        out["levels"].append(res)
    return out


def bucket_volumes(index: dict, only: set[str] | None = None,
                   only_volumes: set[str] | None = None):
    for sample, rec in sorted(index.get("samples", {}).items()):
        if only and sample not in only:
            continue
        for vid, v in sorted(rec.get("volumes", {}).items()):
            if only_volumes and vid not in only_volumes:
                continue
            for item in v.get("data", []):
                if item.get("type") != "ome-zarr" or not item.get("origins"):
                    continue
                o = item["origins"][0]
                roots = o.get("access_roots") or []
                if roots and roots[0]["url"] == BUCKET_S3:
                    yield (sample, vid, o["path"],
                           v["properties"].get("pixel_size_um"))


def default_fetch():
    """HTTP fetch with the audit's contract: ``None`` only for a 404."""
    import requests
    sess = requests.Session()

    def fetch(url):
        last: str | None = None
        for _ in range(3):
            try:
                r = sess.get(url, timeout=60)
            except Exception as exc:  # network error: retry, then unavailable
                last = f"{type(exc).__name__}: {exc}"
                continue
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
        raise OSError(f"{url}: {last}")
    return fetch


def summarize(volumes: list[dict]) -> dict:
    statuses = Counter(l["status"] for v in volumes for l in v["levels"])
    return {
        "volumes": len(volumes),
        "levels_by_status": dict(sorted(statuses.items())),
        "volumes_with_mismatch": sorted(
            f"{v['sample']}:{v['volume']}" for v in volumes
            if any(l["status"] == "mismatch" for l in v["levels"])),
        "volumes_with_errors": sorted(
            f"{v['sample']}:{v['volume']}" for v in volumes if v.get("error")),
        "volumes_unavailable": sorted(
            f"{v['sample']}:{v['volume']}" for v in volumes
            if "unavailable" in str(v.get("error", ""))
            or any("unavailable" in str(l.get("detail", ""))
                   for l in v["levels"])),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="scroliq-chunk-audit",
        description="Check that stored chunk object sizes match the declared "
                    "chunk shape for uncompressed OME-Zarr v2 volumes.")
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--bucket-url", default=BUCKET_URL)
    ap.add_argument("--sample", action="append")
    ap.add_argument("--volume", action="append",
                    help="restrict to a volume id (repeatable)")
    ap.add_argument("--full", action="store_true",
                    help="enumerate every chunk object (slow on big volumes)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    index, index_sha = load_json_maybe_gz(args.index)
    fetch = default_fetch()
    targets = list(bucket_volumes(index, set(args.sample or []),
                                  set(args.volume or [])))

    def work(t):
        s, vid, path, px = t
        try:
            r = audit_volume(fetch, args.bucket_url, path, full=args.full,
                             seed=args.seed)
        except Exception as exc:  # recorded as unknown, never dropped
            r = {"path": path, "levels": [],
                 "error": f"audit failed: {type(exc).__name__}: {exc}"}
        r.update(sample=s, volume=vid, pixel_size_um=px)
        return r

    with ThreadPoolExecutor(args.workers) as ex:
        volumes = list(ex.map(work, targets))
    report = {"schema_version": SCHEMA_VERSION, "bucket_url": args.bucket_url,
              "index_sha256": index_sha, "mode": "full" if args.full
              else "sampled", "seed": args.seed,
              "summary": summarize(volumes), "volumes": volumes}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    s = report["summary"]
    print(f"{s['volumes']} volumes; levels {s['levels_by_status']}",
          file=sys.stderr)
    for v in s["volumes_with_mismatch"]:
        print(f"  MISMATCH {v}", file=sys.stderr)
    bad = (s["levels_by_status"].get("mismatch", 0)
           or s["levels_by_status"].get("unverified", 0)
           or s["volumes_with_errors"])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
