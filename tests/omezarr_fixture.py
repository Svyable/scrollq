"""Synthetic OME-Zarr v2 stores in the layout the Vesuvius S3 bucket serves.

Raw uint8 chunks, ``dimension_separator`` ``/``, edge chunks padded to the
full chunk shape, all-zero chunks optionally *absent* (masked background).
"""

from __future__ import annotations

import json

import numpy as np

from scrollq.omezarr import DictStore


def build_store(vol: np.ndarray, *, chunks=(8, 8, 8), levels: int = 2,
                prefix: str = "vol.zarr", drop_zero_chunks: bool = True,
                level_arrays: list[np.ndarray] | None = None) -> DictStore:
    """Build a multiscale store; level i is ``vol[::2**i, ::2**i, ::2**i]``."""
    prefix = prefix.strip("/")
    data: dict[str, bytes] = {f"{prefix}/.zgroup": b'{"zarr_format": 2}'}
    arrays = level_arrays or [vol[::2**i, ::2**i, ::2**i]
                              for i in range(levels)]
    datasets = []
    for i, arr in enumerate(arrays):
        arr = np.ascontiguousarray(arr, dtype=np.uint8)
        datasets.append({
            "path": str(i),
            "coordinateTransformations": [
                {"scale": [float(2**i)] * 3, "type": "scale"}],
        })
        data[f"{prefix}/{i}/.zarray"] = json.dumps({
            "shape": list(arr.shape), "chunks": list(chunks), "dtype": "|u1",
            "fill_value": 0, "order": "C", "filters": None,
            "dimension_separator": "/", "compressor": None,
            "zarr_format": 2}).encode()
        grid = [-(-s // c) for s, c in zip(arr.shape, chunks)]
        for cz in range(grid[0]):
            for cy in range(grid[1]):
                for cx in range(grid[2]):
                    block = np.zeros(chunks, np.uint8)
                    src = arr[cz * chunks[0]:(cz + 1) * chunks[0],
                              cy * chunks[1]:(cy + 1) * chunks[1],
                              cx * chunks[2]:(cx + 1) * chunks[2]]
                    block[:src.shape[0], :src.shape[1], :src.shape[2]] = src
                    if drop_zero_chunks and not block.any():
                        continue
                    data[f"{prefix}/{i}/{cz}/{cy}/{cx}"] = block.tobytes()
    data[f"{prefix}/.zattrs"] = json.dumps({"multiscales": [{
        "axes": [{"name": n, "type": "space"} for n in "zyx"],
        "datasets": datasets, "version": "0.4"}]}).encode()
    return DictStore(data)


def layered_volume(shape=(48, 48, 48), period: float = 8.0,
                   blur: float = 0.0, seed: int = 0,
                   noise: float = 0.0) -> np.ndarray:
    """Papyrus-like sheets: smooth bright layers on a dark background.

    ``blur`` adds a haze floor that fills the gaps between layers, the way
    decohesion degrades layer separability; ``blur=0`` is crisp.
    """
    z = np.arange(shape[0], dtype=np.float32)[:, None, None]
    y = np.arange(shape[1], dtype=np.float32)[None, :, None]
    x = np.arange(shape[2], dtype=np.float32)[None, None, :]
    phase = (x + 0.3 * y) / period * 2 * np.pi
    sheet = (np.sin(phase) > 0.35).astype(np.float32)
    base = 40.0 + 170.0 * sheet + 0 * z
    haze = 60.0 * blur
    out = base * (1.0 - blur) + haze
    if noise:
        rng = np.random.default_rng(seed)
        out = out + rng.normal(0.0, noise, shape).astype(np.float32)
    return np.clip(np.rint(out), 1, 255).astype(np.uint8)
