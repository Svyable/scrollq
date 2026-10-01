"""Minimal OME-Zarr v2 reader for the Vesuvius open-data bucket.

The Challenge's open S3 bucket (``s3://vesuvius-challenge-open-data``) serves
cloud-optimized OME-Zarr **v2** volumes: ``.zgroup`` / ``.zattrs`` multiscale
metadata plus raw (uncompressed) ``uint8`` 128^3 chunks, one HTTP object per
chunk. This module reads exactly that layout with only ``numpy`` and
``requests``. It is strict on purpose: any variation it does not understand
(a compressor, filters, another dtype, Fortran order, non-zyx axes) raises
:class:`UnsupportedZarr` instead of silently decoding wrong voxels.

Missing chunks are *not* errors. Masked-background chunks are legitimately
absent from the store; they read back as the declared ``fill_value`` and are
counted in :class:`ReadStats` so callers can tell "masked" from "decoded".
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

import numpy as np

_MAX_BOX_VOXELS = 256**3


class UnsupportedZarr(ValueError):
    """The store holds a layout this reader deliberately does not decode."""


class ChunkStore(Protocol):
    def get(self, key: str) -> bytes | None:
        """Return the object bytes, or ``None`` if the key does not exist."""


class DictStore:
    """In-memory store, used by tests and for caching fixtures."""

    def __init__(self, data: dict[str, bytes]):
        self.data = dict(data)

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)


class HttpStore:
    """Read-only HTTP(S) store. 404 means absent; transient errors retry."""

    def __init__(self, base_url: str, *, timeout: float = 60.0,
                 retries: int = 3, session=None):
        import requests

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._session = session or requests.Session()

    def get(self, key: str) -> bytes | None:
        url = f"{self.base_url}/{key.lstrip('/')}"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = self._session.get(url, timeout=self.timeout)
            except Exception as exc:  # network error: retry
                last = exc
            else:
                if r.status_code == 404:
                    return None
                if r.status_code < 400:
                    return r.content
                if r.status_code < 500 and r.status_code != 429:
                    raise OSError(f"HTTP {r.status_code} for {url}")
                last = OSError(f"HTTP {r.status_code} for {url}")
            time.sleep(min(2.0 ** attempt * 0.25, 4.0))
        raise OSError(f"giving up on {url}: {last}")


@dataclass(frozen=True)
class Level:
    index: int
    path: str
    shape: tuple[int, int, int]
    chunks: tuple[int, int, int]
    scale: tuple[float, float, float]  # level-0 voxels per level voxel (z,y,x)

    @property
    def chunk_grid(self) -> tuple[int, int, int]:
        return tuple(-(-s // c) for s, c in zip(self.shape, self.chunks))


@dataclass
class ReadStats:
    chunks_present: int = 0
    chunks_missing: int = 0
    bytes_read: int = 0

    def add(self, other: "ReadStats") -> None:
        self.chunks_present += other.chunks_present
        self.chunks_missing += other.chunks_missing
        self.bytes_read += other.bytes_read

    @property
    def chunks_total(self) -> int:
        return self.chunks_present + self.chunks_missing


def _json(store: ChunkStore, key: str) -> dict:
    raw = store.get(key)
    if raw is None:
        raise UnsupportedZarr(f"{key} not found")
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise UnsupportedZarr(f"{key} is not JSON: {exc}") from exc


class OmeZarrVolume:
    """A multiscale OME-Zarr v2 volume with ``z, y, x`` axes."""

    def __init__(self, store: ChunkStore, prefix: str, levels: list[Level],
                 separators: list[str], fill_value: int,
                 cache_chunks: int = 96):
        self.store = store
        self.prefix = prefix
        self.levels = levels
        self._separators = separators
        self.fill_value = fill_value
        self._cache: OrderedDict[tuple, np.ndarray | None] = OrderedDict()
        self._cache_chunks = cache_chunks
        self._lock = threading.Lock()
        self.stats = ReadStats()

    # -- opening ----------------------------------------------------------
    @classmethod
    def open(cls, store: ChunkStore, prefix: str = "",
             cache_chunks: int = 96) -> "OmeZarrVolume":
        prefix = prefix.strip("/")
        prefix = f"{prefix}/" if prefix else ""
        zattrs = _json(store, f"{prefix}.zattrs")
        try:
            ms = zattrs["multiscales"][0]
            axes = [a["name"] for a in ms["axes"]]
            datasets = ms["datasets"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UnsupportedZarr(f"no usable multiscales metadata: {exc}")
        if axes != ["z", "y", "x"]:
            raise UnsupportedZarr(f"axes {axes} are not z,y,x")
        levels: list[Level] = []
        separators: list[str] = []
        fill_values = set()
        for i, ds in enumerate(datasets):
            path = ds["path"]
            scale = (2.0**i,) * 3
            for t in ds.get("coordinateTransformations", []):
                if t.get("type") == "scale":
                    scale = tuple(float(v) for v in t["scale"])
            za = _json(store, f"{prefix}{path}/.zarray")
            if za.get("zarr_format") != 2:
                raise UnsupportedZarr("only zarr_format 2 is supported")
            if za.get("dtype") not in ("|u1", "<u1", "u1"):
                raise UnsupportedZarr(f"dtype {za.get('dtype')!r} != uint8")
            if za.get("compressor") is not None or za.get("filters"):
                raise UnsupportedZarr("compressed/filtered chunks unsupported")
            if za.get("order", "C") != "C":
                raise UnsupportedZarr("only C order is supported")
            if len(za["shape"]) != 3 or len(za["chunks"]) != 3:
                raise UnsupportedZarr("only 3-D arrays are supported")
            fill_values.add(int(za.get("fill_value") or 0))
            separators.append(za.get("dimension_separator", "."))
            levels.append(Level(i, path, tuple(int(v) for v in za["shape"]),
                                tuple(int(v) for v in za["chunks"]), scale))
        if not levels:
            raise UnsupportedZarr("no levels")
        if len(fill_values) != 1:
            raise UnsupportedZarr("levels disagree on fill_value")
        return cls(store, prefix, levels, separators, fill_values.pop(),
                   cache_chunks)

    # -- chunks -----------------------------------------------------------
    def chunk_key(self, level: int, cidx: tuple[int, int, int]) -> str:
        lv = self.levels[level]
        sep = self._separators[level]
        return f"{self.prefix}{lv.path}/" + sep.join(str(i) for i in cidx)

    def chunk_exists(self, level: int, cidx: tuple[int, int, int]) -> bool:
        return self.read_chunk(level, cidx)[0] is not None

    def read_chunk(self, level: int, cidx: tuple[int, int, int]
                   ) -> tuple[np.ndarray | None, ReadStats]:
        """Return ``(chunk_or_None, stats_for_this_call)``."""
        lv = self.levels[level]
        if any(not 0 <= c < g for c, g in zip(cidx, lv.chunk_grid)):
            raise IndexError(f"chunk {cidx} outside grid {lv.chunk_grid}")
        key = (level, cidx)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key], ReadStats()
        raw = self.store.get(self.chunk_key(level, cidx))
        local = ReadStats()
        arr: np.ndarray | None
        if raw is None:
            local.chunks_missing = 1
            arr = None
        else:
            expect = lv.chunks[0] * lv.chunks[1] * lv.chunks[2]
            if len(raw) != expect:
                raise UnsupportedZarr(
                    f"chunk {self.chunk_key(level, cidx)} has {len(raw)} "
                    f"bytes, expected {expect} (compressed or truncated?)")
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(lv.chunks)
            local.chunks_present = 1
            local.bytes_read = len(raw)
        with self._lock:
            self._cache[key] = arr
            while len(self._cache) > self._cache_chunks:
                self._cache.popitem(last=False)
            self.stats.add(local)
        return arr, local

    # -- boxes ------------------------------------------------------------
    def read_box(self, level: int, lo, hi, workers: int = 8
                 ) -> tuple[np.ndarray, ReadStats]:
        """Read ``[lo, hi)`` (zyx level indices), clipped to the array.

        Absent chunks read as ``fill_value``. Returns the box and the stats of
        this call only.
        """
        lv = self.levels[level]
        lo = [max(0, int(v)) for v in lo]
        hi = [min(s, int(v)) for s, v in zip(lv.shape, hi)]
        if any(h <= l for l, h in zip(lo, hi)):
            return np.zeros((0, 0, 0), np.uint8), ReadStats()
        shape = tuple(h - l for l, h in zip(lo, hi))
        if shape[0] * shape[1] * shape[2] > _MAX_BOX_VOXELS:
            raise ValueError(f"box {shape} exceeds {_MAX_BOX_VOXELS} voxels")
        out = np.full(shape, self.fill_value, np.uint8)
        c0 = [l // c for l, c in zip(lo, lv.chunks)]
        c1 = [-(-h // c) for h, c in zip(hi, lv.chunks)]
        cidxs = [(a, b, c) for a in range(c0[0], c1[0])
                 for b in range(c0[1], c1[1]) for c in range(c0[2], c1[2])]
        total = ReadStats()
        if workers > 1 and len(cidxs) > 1:
            with ThreadPoolExecutor(workers) as ex:
                results = list(ex.map(lambda ci: self.read_chunk(level, ci),
                                      cidxs))
        else:
            results = [self.read_chunk(level, ci) for ci in cidxs]
        for ci, (arr, st) in zip(cidxs, results):
            total.add(st)
            if arr is None:
                continue
            clo = [c * k for c, k in zip(ci, lv.chunks)]
            a_lo = [max(l, cl) for l, cl in zip(lo, clo)]
            a_hi = [min(h, cl + k) for h, cl, k in zip(hi, clo, lv.chunks)]
            out[a_lo[0] - lo[0]:a_hi[0] - lo[0],
                a_lo[1] - lo[1]:a_hi[1] - lo[1],
                a_lo[2] - lo[2]:a_hi[2] - lo[2]] = arr[
                a_lo[0] - clo[0]:a_hi[0] - clo[0],
                a_lo[1] - clo[1]:a_hi[1] - clo[1],
                a_lo[2] - clo[2]:a_hi[2] - clo[2]]
        return out, total

    def sample_trilinear(self, level: int, coords_zyx: np.ndarray
                         ) -> tuple[np.ndarray, np.ndarray, ReadStats]:
        """Trilinearly sample ``(N, 3)`` float ``z,y,x`` level coordinates.

        Voxel ``i`` is centered at coordinate ``i``. ``valid[n]`` is False when
        any of the eight corners falls outside the array; those values are
        NaN. Returns ``(values float32, valid bool, stats)``.
        """
        lv = self.levels[level]
        pts = np.asarray(coords_zyx, dtype=np.float64).reshape(-1, 3)
        if not np.isfinite(pts).all():
            raise ValueError("non-finite sample coordinates")
        base = np.floor(pts).astype(np.int64)
        shape = np.array(lv.shape)
        valid = ((base >= 0) & (base + 1 <= shape - 1)).all(axis=1)
        values = np.full(len(pts), np.nan, np.float32)
        if not valid.any():
            return values, valid, ReadStats()
        vb = base[valid]
        lo = vb.min(axis=0)
        hi = vb.max(axis=0) + 2
        box, stats = self.read_box(level, lo, hi)
        box = box.astype(np.float32)
        f = (pts[valid] - vb).astype(np.float32)
        b = vb - lo
        acc = np.zeros(len(vb), np.float32)
        for dz in (0, 1):
            wz = f[:, 0] if dz else 1.0 - f[:, 0]
            for dy in (0, 1):
                wy = f[:, 1] if dy else 1.0 - f[:, 1]
                for dx in (0, 1):
                    wx = f[:, 2] if dx else 1.0 - f[:, 2]
                    acc += (wz * wy * wx) * box[b[:, 0] + dz, b[:, 1] + dy,
                                                b[:, 2] + dx]
        values[valid] = acc
        return values, valid, stats

    # -- convenience ------------------------------------------------------
    def nearest_level(self, spacing_um: float, level0_um: float) -> int:
        """Level whose voxel size is closest (log scale) to ``spacing_um``."""
        best, best_err = 0, float("inf")
        for lv in self.levels:
            size = level0_um * float(np.mean(lv.scale))
            err = abs(np.log(size / spacing_um))
            if err < best_err:
                best, best_err = lv.index, err
        return best
