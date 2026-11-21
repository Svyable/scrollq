"""Experimental progressive E8 feature codec; no Sussman circuit or QuIP# code.

A byte indexes zero or one of the 240 E8 roots for each eight channels.
Successive bytes encode residuals. Calibration alone fits normalization and
stage radii. Optional frozen linear probes protect their scores and decisions
by storing original float32 rows or a compact score projection. This is finite numerical protection for those
probes only, never a guarantee about another head, ink, or nearest neighbors.
"""
from __future__ import annotations

import io
import itertools
from dataclasses import dataclass

import numpy as np


def roots() -> np.ndarray:
    """Zero plus 112 integer and 128 half-integer roots, in stable order."""
    out = [np.zeros(8)]
    for i, j in itertools.combinations(range(8), 2):
        for a, b in itertools.product((-1, 1), repeat=2):
            r = np.zeros(8)
            r[i], r[j] = a, b
            out.append(r)
    for s in itertools.product((-1, 1), repeat=8):
        if sum(v < 0 for v in s) % 2 == 0:
            out.append(np.array(s) / 2)
    return np.asarray(out, dtype=np.float64)


BOOK = roots()
H8 = np.array([[(-1) ** ((i & j).bit_count()) for j in range(8)]
               for i in range(8)], dtype=np.float64) / np.sqrt(8)


def features(x) -> np.ndarray:
    a = np.asarray(x)
    if a.ndim != 2 or not len(a) or not a.shape[1] or a.shape[1] % 8:
        raise ValueError("features must be nonempty N x D, D divisible by 8")
    a = np.asarray(a, dtype=np.float32)
    if not np.isfinite(a).all():
        raise ValueError("features must be finite float32-representable values")
    return a


def nearest(x, radius) -> np.ndarray:
    """Closed-form root-shell search: zero, best integer root, best half root.

    Integer roots select two largest absolute coordinates. Half roots select
    signs, repairing odd parity at the smallest absolute coordinate. Only three
    distances are evaluated; no N x 241 distance matrix. First-book ties win.
    This searches our finite shell, not the whole infinite E8 lattice.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 8 or not np.isfinite(x).all():
        raise ValueError("nearest requires finite N x 8")
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("radius must be positive")
    n = len(x)
    row = np.arange(n)
    absolute = np.abs(x)
    pair = np.sort(np.argsort(-absolute, axis=1, kind="stable")[:, :2], axis=1)
    i, j = pair.T
    a, b = (x[row, i] > 0).astype(int), (x[row, j] > 0).astype(int)
    pair_number = i * (15 - i) // 2 + j - i - 1
    integer_index = 1 + 4 * pair_number + 2 * a + b
    positive = x > 0
    odd = np.count_nonzero(positive, axis=1) % 2 == 1
    smallest = absolute == absolute.min(axis=1, keepdims=True)
    # Among equal-cost flips, lower the first positive bit if available;
    # otherwise raise the last negative bit: lexicographically first root.
    lower = smallest & positive
    flip = np.where(lower.any(axis=1), lower.argmax(axis=1),
                    7 - smallest[:, ::-1].argmax(axis=1))
    positive[row[odd], flip[odd]] ^= True
    mask = (positive * (1 << np.arange(7, -1, -1))).sum(axis=1)
    half_index = 113 + (mask >> 1)
    candidates = np.stack([np.zeros(n, dtype=int), integer_index, half_index], axis=1)
    distance = ((x[:, None, :] - BOOK[candidates] * radius) ** 2).sum(axis=2)
    return candidates[row, np.argmin(distance, axis=1)].astype(np.uint8)


@dataclass
class Codec:
    method: str
    bits: int
    mean: np.ndarray
    scale: np.ndarray
    signs: np.ndarray
    parameters: np.ndarray

    def transform(self, x):
        z = (features(x).astype(np.float64) - self.mean) / self.scale
        if z.shape[1] != len(self.mean):
            raise ValueError("channel mismatch")
        return ((z * self.signs).reshape(-1, 8) @ H8).reshape(z.shape)

    def inverse(self, z):
        x = ((z.reshape(-1, 8) @ H8).reshape(z.shape) * self.signs)
        return np.asarray(x * self.scale + self.mean, dtype=np.float32)

    def quantize(self, x):
        z = self.transform(x)
        if self.method == "e8":
            residual = z.reshape(-1, 8).copy()
            indices = []
            for radius in self.parameters:
                i = nearest(residual, radius)
                indices.append(i)
                residual -= BOOK[i] * radius
            code = np.stack(indices, axis=1)
            return code, self.inverse(z - residual.reshape(z.shape))
        levels = (1 << self.bits) - 1
        limit = self.parameters
        q = np.rint((np.clip(z, -limit, limit) / limit + 1) * levels / 2)
        q = q.astype(np.uint8)
        binary = (q.ravel()[:, None] >> np.arange(self.bits)) & 1
        code = np.packbits(binary.ravel(), bitorder="little")
        return code, self.inverse((q.astype(float) * 2 / levels - 1) * limit)


def fit(calibration, *, method="e8", bits=2, seed=1729) -> Codec:
    if method not in ("e8", "scalar") or bits not in (1, 2, 4):
        raise ValueError("method e8/scalar; bits 1, 2 or 4 per channel")
    x = features(calibration).astype(np.float64)
    mean, scale = x.mean(0), x.std(0)
    scale = np.maximum(scale, 1e-8)
    signs = np.random.default_rng(seed).choice((-1.0, 1.0), x.shape[1])
    model = Codec(method, bits, mean, scale, signs, np.array([]))
    z = model.transform(x)
    if method == "scalar":
        # Stronger than a max-range straw man: minimize calibration MSE on
        # a fixed clipping grid independently per channel. No evaluation fit.
        rms = np.maximum(np.sqrt(np.mean(z ** 2, axis=0)), 1e-8)
        best, error = rms.copy(), np.full(x.shape[1], np.inf)
        levels = (1 << bits) - 1
        for factor in np.linspace(0.5, 4.5, 41):
            limit = rms * factor
            q = np.rint((np.clip(z, -limit, limit) / limit + 1) * levels / 2)
            rec = (q * 2 / levels - 1) * limit
            mse = np.mean((z - rec) ** 2, axis=0)
            improve = mse < error
            best[improve], error[improve] = limit[improve], mse[improve]
        model.parameters = best
    else:
        residual = z.reshape(-1, 8).copy()
        radii = []
        for _ in range(bits):
            radius = max(float(np.linalg.norm(residual, axis=1).mean() / np.sqrt(2)), 1e-8)
            for _ in range(8):
                i = nearest(residual, radius)
                b = BOOK[i]
                radius = max(float((residual * b).sum() / max((b * b).sum(), 1e-12)), 1e-8)
            i = nearest(residual, radius)
            residual -= BOOK[i] * radius
            radii.append(radius)
        model.parameters = np.array(radii)
    return model


def encode(model, x, *, probes=None, bias=None, score_tolerance=0.05,
           protection="escape") -> bytes:
    """Stored NPZ (no entropy compression); includes model and exact escapes.

    At encode time only, inspect frozen probe scores, without labels. Projection
    mode stores xW and corrects with W's pseudoinverse, then both modes escape
    if any score moves by more than tolerance or changes sign at zero.
    Decoder does not need probes. Every original row is float32 by contract.
    """
    x = features(x)
    if protection not in ("escape", "projection"):
        raise ValueError("unknown protection mode")
    if not np.isfinite(score_tolerance) or score_tolerance < 0:
        raise ValueError("invalid score tolerance")
    code, restored = model.quantize(x)
    escape = np.zeros(len(x), dtype=bool)
    side = {"probe_weights": np.empty((x.shape[1], 0)),
            "probe_dual": np.empty((0, x.shape[1])), "probe_values": np.empty((len(x), 0))}
    if probes is not None:
        w = np.asarray(probes, dtype=float)
        if w.ndim == 1:
            w = w[:, None]
        b = np.zeros(w.shape[1]) if bias is None else np.asarray(bias, dtype=float)
        if w.shape[0] != x.shape[1] or not w.shape[1] or b.shape != (w.shape[1],):
            raise ValueError("probe dimensions mismatch")
        if not np.isfinite(w).all() or not np.isfinite(b).all():
            raise ValueError("probes must be finite")
        if protection == "projection":
            dual = np.linalg.pinv(w)
            if not np.allclose(dual @ w, np.eye(w.shape[1]), atol=1e-10, rtol=1e-10):
                raise ValueError("projection probes must be independent and well-conditioned")
            values = x.astype(float) @ w
            restored = np.asarray(restored.astype(float) +
                                  (values - restored.astype(float) @ w) @ dual, dtype=np.float32)
            side = {"probe_weights": w, "probe_dual": dual, "probe_values": values}
        raw, rec = x.astype(float) @ w + b, restored.astype(float) @ w + b
        if not np.isfinite(raw).all() or not np.isfinite(rec).all():
            raise ValueError("probe scores overflowed")
        escape = np.any((np.abs(raw - rec) > score_tolerance) |
                        ((raw >= 0) != (rec >= 0)), axis=1)
    buf = io.BytesIO()
    np.savez(buf, schema=np.array(1), method=np.array(model.method), bits=np.array(model.bits),
             shape=np.array(x.shape, dtype=np.int64), mean=model.mean, scale=model.scale,
             signs=model.signs, parameters=model.parameters, code=code,
             escape_rows=np.flatnonzero(escape).astype(np.int64), escape_values=x[escape], **side)
    return buf.getvalue()


def decode(payload: bytes) -> np.ndarray:
    with np.load(io.BytesIO(payload), allow_pickle=False) as p:
        if int(p["schema"]) != 1:
            raise ValueError("unsupported codec schema")
        method, bits = str(p["method"]), int(p["bits"])
        if method not in ("e8", "scalar") or bits not in (1, 2, 4):
            raise ValueError("invalid codec method/bits")
        shape = tuple(int(v) for v in p["shape"])
        if len(shape) != 2 or min(shape) <= 0 or shape[1] % 8:
            raise ValueError("invalid shape")
        n, d = shape
        for name in ("mean", "scale", "signs"):
            if p[name].shape != (d,) or not np.isfinite(p[name]).all():
                raise ValueError("invalid model arrays")
        if np.any(p["scale"] <= 0) or not np.isin(p["signs"], [-1, 1]).all():
            raise ValueError("invalid normalization")
        params = p["parameters"]
        if params.shape != ((bits,) if method == "e8" else (d,)):
            raise ValueError("invalid parameters")
        if not np.isfinite(params).all() or np.any(params <= 0):
            raise ValueError("invalid radii/ranges")
        model = Codec(method, bits, p["mean"], p["scale"], p["signs"], params)
        code = p["code"]
        if code.dtype != np.uint8:
            raise ValueError("codes must be uint8")
        if method == "e8":
            if code.shape != (n * d // 8, bits) or np.any(code >= len(BOOK)):
                raise ValueError("invalid E8 indices")
            z = sum(BOOK[code[:, k]] * params[k] for k in range(bits)).reshape(shape)
        else:
            if code.shape != ((n * d * bits + 7) // 8,):
                raise ValueError("invalid packed scalar codes")
            binary = np.unpackbits(code, bitorder="little")[:n * d * bits].reshape(-1, bits)
            q = (binary * (1 << np.arange(bits))).sum(1).reshape(shape)
            z = (q * 2 / ((1 << bits) - 1) - 1) * params
        x = model.inverse(z)
        weights, dual, scores = (p[k] for k in ("probe_weights", "probe_dual", "probe_values"))
        if weights.ndim != 2 or weights.shape[0] != d:
            raise ValueError("invalid projection weights")
        k = weights.shape[1]
        if dual.shape != (k, d) or scores.shape != (n, k):
            raise ValueError("invalid projection side channel")
        if any(not np.isfinite(a).all() for a in (weights, dual, scores)):
            raise ValueError("nonfinite projection side channel")
        if k:
            if not np.allclose(dual @ weights, np.eye(k), atol=1e-10, rtol=1e-10):
                raise ValueError("invalid projection dual")
            x = np.asarray(x.astype(float) + (scores - x.astype(float) @ weights) @ dual, dtype=np.float32)
        rows, values = p["escape_rows"], p["escape_values"]
        if rows.ndim != 1 or rows.dtype.kind not in "iu" or values.dtype != np.float32:
            raise ValueError("invalid escapes")
        if np.any(rows < 0) or np.any(rows >= n) or len(np.unique(rows)) != len(rows):
            raise ValueError("invalid escape offsets")
        if values.shape != (len(rows), d) or not np.isfinite(values).all():
            raise ValueError("invalid escape values")
        x[rows] = values
        if not np.isfinite(x).all():
            raise ValueError("nonfinite reconstruction")
        return x
