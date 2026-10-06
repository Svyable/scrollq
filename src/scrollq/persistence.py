"""Exact threshold persistence of a 2-D ink score field.

A frozen detector's probability map is treated as a scalar field ``f``. For the
superlevel filtration ``F_t = {f >= t}`` this module computes, exactly and
deterministically, how connected components (H0) and enclosed holes (H1)
are born and die as the threshold sweeps from the top of the field to the
bottom, plus a few geometric measurements of each component along that sweep.

Conventions (fixed; they are part of the frozen protocol):

* foreground is 8-connected and background 4-connected, so
  ``beta0 - beta1`` equals the Euler characteristic of the union of closed
  foreground pixel squares at every threshold (checked by the control suite);
* the filtration parameter is the mid-rank *kept fraction* ``s(u)`` of a dense
  level ``u``, never the absolute probability. Every quantity returned by
  :func:`analyze_components` is a function of the integer level image and the
  nominal level only, so it is exactly invariant to any strictly monotone
  recalibration of the scores. The raw values are carried in :class:`Levels`
  only so the value-parameterised *control* can show that the naive
  parameterisation is not invariant;
* invalid pixels (outside the validation mask) are treated as "outside": a
  region enclosed only by masked pixels is never reported as a hole;
* ties are broken by flat pixel index, so a diagram is reproducible; spatial
  attributes of exactly tied peaks follow that rule, while the diagram's
  off-diagonal multiset does not depend on it.

Nothing here reads ink labels, text, or a character template, and nothing
chooses a threshold: the nominal threshold is an input.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np
from scipy import ndimage

STRUCT8 = np.ones((3, 3), dtype=bool)
ESSENTIAL = -1


class PersistenceError(ValueError):
    """Invalid field, mask, configuration, or an internal consistency failure."""


@dataclasses.dataclass(frozen=True)
class SweepConfig:
    """Constants of the component sweep (a subset of the frozen protocol spec)."""

    min_component_pixels: int = 12
    max_components: int = 400
    significant_persistence: float = 5e-4
    window_log10: float = 0.5
    steps_per_side: int = 4

    def validate(self) -> None:
        if self.min_component_pixels < 1:
            raise PersistenceError("min_component_pixels must be >= 1")
        if self.max_components < 1:
            raise PersistenceError("max_components must be >= 1")
        if not 0 < self.significant_persistence < 1:
            raise PersistenceError("significant_persistence must be in (0, 1)")
        if not 0 < self.window_log10 <= 2:
            raise PersistenceError("window_log10 must be in (0, 2]")
        if self.steps_per_side < 1:
            raise PersistenceError("steps_per_side must be >= 1")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------------------- levels


@dataclasses.dataclass(frozen=True)
class Levels:
    """Dense-rank view of a score field.

    ``levels`` is int32 with ``-1`` at invalid pixels; ``counts[u]`` is the
    number of valid pixels at dense level ``u`` (ascending in value);
    ``values[u]`` is that level's score. Equal scores share a level.
    """

    levels: np.ndarray
    counts: np.ndarray
    values: np.ndarray

    @property
    def n_valid(self) -> int:
        return int(self.counts.sum())

    @property
    def n_levels(self) -> int:
        return int(self.counts.size)

    def mid_rank(self) -> np.ndarray:
        """Kept fraction ``s(u)``: mid-rank from the top, strictly decreasing in ``u``."""
        above = np.cumsum(self.counts[::-1])[::-1] - self.counts
        return (above + self.counts / 2.0) / float(self.n_valid)

    def kept_fraction_at(self, level: int) -> float:
        """Fraction of valid pixels with level >= ``level`` (the nominal mask)."""
        return float(self.counts[level:].sum()) / float(self.n_valid)


def dense_levels(values: Any, valid: Any) -> Levels:
    arr = np.asarray(values)
    mask = np.asarray(valid, dtype=bool)
    if arr.ndim != 2 or arr.shape != mask.shape:
        raise PersistenceError("values and valid mask must be 2-D arrays of one shape")
    if not mask.any():
        raise PersistenceError("valid mask selects no pixels")
    selected = arr[mask]
    if not np.all(np.isfinite(selected)):
        raise PersistenceError("score field contains NaN or infinite values")
    uniq, inverse, counts = np.unique(
        selected.astype(np.float64), return_inverse=True, return_counts=True
    )
    levels = np.full(arr.shape, -1, dtype=np.int32)
    levels[mask] = inverse.reshape(-1).astype(np.int32)
    return Levels(levels=levels, counts=counts.astype(np.int64), values=uniq)


def nominal_level(lv: Levels, threshold: float) -> int | None:
    """Lowest dense level whose score is >= ``threshold``; None if no pixel reaches it."""
    if not math.isfinite(float(threshold)):
        raise PersistenceError("nominal threshold must be finite")
    index = int(np.searchsorted(lv.values, float(threshold), side="left"))
    return None if index >= lv.n_levels else index


# ----------------------------------------------------------------------- diagrams


@dataclasses.dataclass(frozen=True)
class Diagram:
    """H0 pairs of the superlevel filtration (levels, not scores).

    One row per component branch with positive persistence. ``death`` is
    :data:`ESSENTIAL` (-1) for a branch that is never absorbed by a stronger one.
    """

    peak_idx: np.ndarray
    birth: np.ndarray
    death: np.ndarray
    elder_idx: np.ndarray


@dataclasses.dataclass(frozen=True)
class Holes:
    """H1 pairs: a hole is alive at levels ``u`` with ``lo < u <= hi``."""

    lo: np.ndarray
    hi: np.ndarray
    rep_idx: np.ndarray
    closing_idx: np.ndarray


def _edges8(levels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h, w = levels.shape
    flat = np.arange(h * w, dtype=np.int64).reshape(h, w)
    parts_a: list[np.ndarray] = []
    parts_b: list[np.ndarray] = []
    parts_w: list[np.ndarray] = []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        if w - abs(dx) <= 0 or h - dy <= 0:
            continue
        xa = slice(0, w - dx) if dx >= 0 else slice(-dx, w)
        xb = slice(dx, w) if dx >= 0 else slice(0, w + dx)
        la = levels[0 : h - dy, xa]
        lb = levels[dy:h, xb]
        ok = (la >= 0) & (lb >= 0)
        parts_a.append(flat[0 : h - dy, xa][ok])
        parts_b.append(flat[dy:h, xb][ok])
        parts_w.append(np.minimum(la, lb)[ok].astype(np.int64))
    if not parts_a:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, empty
    return np.concatenate(parts_a), np.concatenate(parts_b), np.concatenate(parts_w)


def h0_diagram(levels: np.ndarray) -> Diagram:
    """Exact H0 persistence by Kruskal-style union-find with the elder rule."""
    lev = np.asarray(levels)
    h, w = lev.shape
    n = h * w
    a, b, wgt = _edges8(lev)
    order = np.lexsort((b, a, -wgt))
    a_l = a[order].tolist()
    b_l = b[order].tolist()
    w_l = wgt[order].tolist()

    parent = list(range(n))
    peak_lvl = lev.ravel().tolist()
    peak_idx = list(range(n))

    rec_peak: list[int] = []
    rec_birth: list[int] = []
    rec_death: list[int] = []
    rec_elder: list[int] = []

    for e in range(len(a_l)):
        ra = a_l[e]
        while parent[ra] != ra:
            parent[ra] = parent[parent[ra]]
            ra = parent[ra]
        rb = b_l[e]
        while parent[rb] != rb:
            parent[rb] = parent[parent[rb]]
            rb = parent[rb]
        if ra == rb:
            continue
        la, lb = peak_lvl[ra], peak_lvl[rb]
        if la > lb or (la == lb and peak_idx[ra] < peak_idx[rb]):
            win, lose = ra, rb
        else:
            win, lose = rb, ra
        birth = peak_lvl[lose]
        if birth > w_l[e]:
            rec_peak.append(peak_idx[lose])
            rec_birth.append(birth)
            rec_death.append(w_l[e])
            rec_elder.append(peak_idx[win])
        parent[lose] = win

    flat = lev.ravel()
    for x in np.flatnonzero(flat >= 0).tolist():
        if parent[x] == x:
            rec_peak.append(peak_idx[x])
            rec_birth.append(peak_lvl[x])
            rec_death.append(ESSENTIAL)
            rec_elder.append(-1)

    return Diagram(
        peak_idx=np.asarray(rec_peak, dtype=np.int64),
        birth=np.asarray(rec_birth, dtype=np.int32),
        death=np.asarray(rec_death, dtype=np.int32),
        elder_idx=np.asarray(rec_elder, dtype=np.int64),
    )


def h1_holes(levels: np.ndarray) -> Holes:
    """Exact H1 persistence from the dual (4-connected background) filtration.

    The background ``{f < t}`` is grown in ascending order inside a padded
    grid. Every invalid pixel and the padding collapse into one "outside"
    component that is older than any valid pixel, so only regions enclosed by
    valid foreground become holes.
    """
    lev0 = np.asarray(levels)
    h, w = lev0.shape
    lev = np.full((h + 2, w + 2), -1, dtype=np.int32)
    lev[1:-1, 1:-1] = lev0
    hp, wp = lev.shape
    n = hp * wp
    flat = np.arange(n, dtype=np.int64).reshape(hp, wp)

    parts_a: list[np.ndarray] = []
    parts_b: list[np.ndarray] = []
    parts_w: list[np.ndarray] = []
    for dy, dx in ((0, 1), (1, 0)):
        la = lev[0 : hp - dy, 0 : wp - dx]
        lb = lev[dy:hp, dx:wp]
        ok = (la >= 0) | (lb >= 0)
        parts_a.append(flat[0 : hp - dy, 0 : wp - dx][ok])
        parts_b.append(flat[dy:hp, dx:wp][ok])
        parts_w.append(np.maximum(la, lb)[ok].astype(np.int64))
    a = np.concatenate(parts_a)
    b = np.concatenate(parts_b)
    wgt = np.concatenate(parts_w)
    order = np.lexsort((b, a, wgt))
    a_l = a[order].tolist()
    b_l = b[order].tolist()
    w_l = wgt[order].tolist()

    lev_flat = lev.ravel()
    parent_arr = np.arange(n, dtype=np.int64)
    parent_arr[lev_flat < 0] = 0
    parent = parent_arr.tolist()
    birth = lev_flat.astype(np.int64).tolist()
    birth[0] = -2
    low_idx = list(range(n))
    lev_l = lev_flat.tolist()

    rec_lo: list[int] = []
    rec_hi: list[int] = []
    rec_rep: list[int] = []
    rec_close: list[int] = []

    def unpad(p: int) -> int:
        y, x = divmod(p, wp)
        return (y - 1) * w + (x - 1)

    for e in range(len(a_l)):
        ra = a_l[e]
        while parent[ra] != ra:
            parent[ra] = parent[parent[ra]]
            ra = parent[ra]
        rb = b_l[e]
        while parent[rb] != rb:
            parent[rb] = parent[parent[rb]]
            rb = parent[rb]
        if ra == rb:
            continue
        if (birth[ra], low_idx[ra]) < (birth[rb], low_idx[rb]):
            win, lose = ra, rb
        else:
            win, lose = rb, ra
        merge = w_l[e]
        if merge > birth[lose]:
            pa, pb = a_l[e], b_l[e]
            if lev_l[pa] == merge and lev_l[pb] == merge:
                closing = min(pa, pb)
            else:
                closing = pa if lev_l[pa] == merge else pb
            rec_lo.append(birth[lose])
            rec_hi.append(merge)
            rec_rep.append(unpad(low_idx[lose]))
            rec_close.append(unpad(closing))
        parent[lose] = win

    return Holes(
        lo=np.asarray(rec_lo, dtype=np.int32),
        hi=np.asarray(rec_hi, dtype=np.int32),
        rep_idx=np.asarray(rec_rep, dtype=np.int64),
        closing_idx=np.asarray(rec_close, dtype=np.int64),
    )


def betti_at(diagram: Diagram, holes: Holes, level: int) -> tuple[int, int]:
    """(beta0, beta1) of ``{level_image >= level}`` read off the diagrams."""
    b0 = int(np.count_nonzero((diagram.death < level) & (level <= diagram.birth)))
    b1 = int(np.count_nonzero((holes.lo < level) & (level <= holes.hi)))
    return b0, b1


def diagram_persistence(lv: Levels, diagram: Diagram, parameter: str = "rank") -> np.ndarray:
    """Sorted persistence of non-essential H0 pairs under a named parameterisation.

    ``rank`` uses the kept fraction (monotone-invariant); ``value`` uses the
    absolute score and exists only so a control can show it is *not* invariant.
    """
    keep = diagram.death >= 0
    if parameter == "rank":
        s = lv.mid_rank()
        out = s[diagram.death[keep]] - s[diagram.birth[keep]]
    elif parameter == "value":
        out = lv.values[diagram.birth[keep]] - lv.values[diagram.death[keep]]
    else:
        raise PersistenceError("parameter must be 'rank' or 'value'")
    return np.sort(out)


def euler_characteristic(mask: np.ndarray) -> int:
    """Euler characteristic of the union of closed unit squares of ``mask`` pixels.

    Independent of the persistence code: ``V - E + F`` over the vertex, edge and
    face sets of the cubical complex. With 8-connected foreground and
    4-connected background this equals ``beta0 - beta1``.
    """
    m = np.asarray(mask, dtype=bool)
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), dtype=bool)
    pad[1:-1, 1:-1] = m
    faces = int(m.sum())
    vert = (pad[:-1, :-1] | pad[:-1, 1:] | pad[1:, :-1] | pad[1:, 1:])
    horiz = pad[:-1, 1:-1] | pad[1:, 1:-1]
    vertical = pad[1:-1, :-1] | pad[1:-1, 1:]
    return int(vert.sum()) - int(horiz.sum()) - int(vertical.sum()) + faces


# ---------------------------------------------------------------------- skeleton


def skeleton(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning (vectorised; deterministic)."""
    img = np.pad(np.asarray(mask, dtype=bool), 1)
    while True:
        changed = False
        for step in (0, 1):
            p2 = img[:-2, 1:-1]
            p3 = img[:-2, 2:]
            p4 = img[1:-1, 2:]
            p5 = img[2:, 2:]
            p6 = img[2:, 1:-1]
            p7 = img[2:, :-2]
            p8 = img[1:-1, :-2]
            p9 = img[:-2, :-2]
            centre = img[1:-1, 1:-1]
            neighbours = (
                p2.astype(np.int8) + p3 + p4 + p5 + p6 + p7 + p8 + p9
            )
            transitions = (
                ((~p2) & p3).astype(np.int8)
                + ((~p3) & p4)
                + ((~p4) & p5)
                + ((~p5) & p6)
                + ((~p6) & p7)
                + ((~p7) & p8)
                + ((~p8) & p9)
                + ((~p9) & p2)
            )
            if step == 0:
                gate = ~(p2 & p4 & p6) & ~(p4 & p6 & p8)
            else:
                gate = ~(p2 & p4 & p8) & ~(p2 & p6 & p8)
            remove = centre & (neighbours >= 2) & (neighbours <= 6) & (transitions == 1) & gate
            if remove.any():
                img[1:-1, 1:-1] = centre & ~remove
                changed = True
        if not changed:
            return img[1:-1, 1:-1]


# ------------------------------------------------------------ component analysis

FEATURE_NAMES = (
    "down_slack_log",
    "area_growth_log",
    "area_retention_tight",
    "centroid_drift_norm",
    "skeleton_log_change",
    "hole_life_log",
    "n_significant_peaks",
)
GEOMETRY_NAMES = ("log_area", "peak_margin_log", "elongation", "bbox_fill")


def _grid_levels(lv: Levels, u_nom: int, window_log10: float, steps: int) -> list[int]:
    """Dense levels at log-spaced kept fractions around the nominal one."""
    s = lv.mid_rank()
    s_nom = float(s[u_nom])
    neg_s = -s
    out: list[int] = []
    for offset in np.linspace(-window_log10, window_log10, 2 * steps + 1):
        if abs(offset) < 1e-12:
            out.append(u_nom)
            continue
        target = min(max(s_nom * 10.0 ** float(offset), float(s.min())), float(s.max()))
        j = int(np.searchsorted(neg_s, -target, side="left"))
        candidates = [c for c in (j - 1, j) if 0 <= c < s.size]
        best = min(candidates, key=lambda c: (abs(math.log(s[c]) - math.log(target)), c))
        out.append(best)
    return out


def _label_stats(levels: np.ndarray, fg: np.ndarray, key: np.ndarray, yy: np.ndarray, xx: np.ndarray):
    lab, n = ndimage.label(fg, structure=STRUCT8)
    if n == 0:
        return lab, 0, None, None, None, None
    ids = np.arange(1, n + 1)
    flat = lab.ravel()
    sizes = np.bincount(flat, minlength=n + 1)
    kmax = np.concatenate(([0], np.asarray(ndimage.maximum(key, lab, index=ids), dtype=np.int64)))
    cy = np.bincount(flat, weights=yy.ravel(), minlength=n + 1)
    cx = np.bincount(flat, weights=xx.ravel(), minlength=n + 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cy = cy / np.maximum(sizes, 1)
        cx = cx / np.maximum(sizes, 1)
    return lab, n, sizes, kmax, cy, cx


def _crop_skeleton_pixels(lab: np.ndarray, objects: list, label: int) -> int:
    sl = objects[label - 1]
    return int(skeleton(lab[sl] == label).sum())


def analyze_components(
    lv: Levels,
    u_nom: int,
    cfg: SweepConfig,
    diagram: Diagram,
    holes: Holes,
) -> dict[str, Any]:
    """Persistence and sweep features of the nominal components.

    Depends only on ``lv.levels``, ``lv.counts`` and ``u_nom`` (never on
    ``lv.values``), so the result is invariant to strictly monotone
    recalibration of the scores. Returns the per-component rows in a
    deterministic order (descending peak level, then ascending peak index) and
    the nominal label image restricted to the kept components.
    """
    cfg.validate()
    levels = lv.levels
    h, w = levels.shape
    n_pix = h * w
    if not 0 <= u_nom < lv.n_levels:
        raise PersistenceError("nominal level out of range")
    s = lv.mid_rank()
    s_nom = float(s[u_nom])

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    flat_idx = np.arange(n_pix, dtype=np.int64).reshape(h, w)
    key = levels.astype(np.int64) * n_pix + (n_pix - 1 - flat_idx)

    lab0, n0, size0, kmax0, cy0, cx0 = _label_stats(levels, levels >= u_nom, key, yy, xx)
    empty = {
        "components": [],
        "labels": np.zeros((h, w), dtype=np.int32),
        "n_components_total": int(n0),
        "n_dropped_small": int(n0),
        "nominal_level": int(u_nom),
        "s_nominal": s_nom,
    }
    if n0 == 0:
        return empty
    keep = [int(c) for c in np.flatnonzero(size0 >= cfg.min_component_pixels) if c > 0]
    n_dropped = int(n0 - len(keep))
    if not keep:
        out = dict(empty)
        out["n_dropped_small"] = n_dropped
        return out
    if len(keep) > cfg.max_components:
        raise PersistenceError(
            f"{len(keep)} nominal components exceed max_components={cfg.max_components}"
        )

    pk_key = kmax0[np.asarray(keep)]
    pk_lvl = pk_key // n_pix
    pk_idx = n_pix - 1 - (pk_key % n_pix)
    order = np.lexsort((pk_idx, -pk_lvl))
    keep = [keep[i] for i in order]
    pk_lvl = pk_lvl[order]
    pk_idx = pk_idx[order]
    n_c = len(keep)

    death_at = np.full(n_pix, -3, dtype=np.int64)
    death_at[diagram.peak_idx] = diagram.death
    peak_death = death_at[pk_idx]
    if np.any(peak_death == -3):
        raise PersistenceError("nominal component peak missing from the H0 diagram")
    s_birth = s[pk_lvl]
    s_death = np.where(peak_death == ESSENTIAL, 1.0, s[np.maximum(peak_death, 0)])
    down_slack = np.log10(s_death / s_nom)
    peak_margin = np.log10(s_nom / s_birth)

    lab_flat = lab0.ravel()
    comp_of_label = np.zeros(n0 + 1, dtype=np.int64)
    for i, c in enumerate(keep):
        comp_of_label[c] = i + 1

    sub = (diagram.death >= u_nom) & (diagram.death != ESSENTIAL)
    sub &= (s[np.maximum(diagram.death, 0)] - s[diagram.birth]) >= cfg.significant_persistence
    sub_comp = comp_of_label[lab_flat[diagram.peak_idx[sub]]]
    n_sig = np.bincount(sub_comp, minlength=n_c + 1)[1:]

    hole_life = np.zeros(n_c, dtype=np.float64)
    alive = (holes.lo < u_nom) & (u_nom <= holes.hi)
    if alive.any():
        hl = s[holes.lo[alive]] - s[holes.hi[alive]]
        hc = comp_of_label[lab_flat[holes.closing_idx[alive]]]
        for life, comp in zip(hl.tolist(), hc.tolist()):
            if comp > 0:
                hole_life[comp - 1] = max(hole_life[comp - 1], life)
    hole_life_log = np.log10(1.0 + hole_life * lv.n_valid)

    grid = _grid_levels(lv, u_nom, cfg.window_log10, cfg.steps_per_side)
    n_k = len(grid)
    mid = cfg.steps_per_side
    area = np.zeros((n_c, n_k), dtype=np.float64)
    cyk = np.zeros((n_c, n_k), dtype=np.float64)
    cxk = np.zeros((n_c, n_k), dtype=np.float64)
    ok = np.zeros((n_c, n_k), dtype=bool)
    label_at: list[np.ndarray] = []
    own_label = np.zeros((n_c, n_k), dtype=np.int64)
    peak_key = levels.ravel()[pk_idx].astype(np.int64) * n_pix + (n_pix - 1 - pk_idx)
    cache: dict[int, tuple] = {}
    for k, u in enumerate(grid):
        if k == mid:
            stats = (lab0, n0, size0, kmax0, cy0, cx0)
        elif u in cache:
            stats = cache[u]
        else:
            stats = _label_stats(levels, levels >= u, key, yy, xx)
            cache[u] = stats
        lab, n, sizes, kmax, cy, cx = stats
        label_at.append(lab)
        if n == 0:
            continue
        lbl = lab.ravel()[pk_idx]
        valid_lineage = (lbl > 0) & (kmax[lbl] == peak_key)
        ok[:, k] = valid_lineage
        own_label[:, k] = np.where(valid_lineage, lbl, 0)
        area[:, k] = np.where(valid_lineage, sizes[lbl], 0)
        cyk[:, k] = np.where(valid_lineage, cy[lbl], 0.0)
        cxk[:, k] = np.where(valid_lineage, cx[lbl], 0.0)
    if not ok[:, mid].all():
        raise PersistenceError("nominal lineage inconsistent with the nominal labeling")

    a_nom = area[:, mid]
    retention = np.where(ok[:, 0], area[:, 0] / a_nom, 0.0)
    last = np.zeros(n_c, dtype=np.int64)
    for k in range(mid, n_k):
        last = np.where(ok[:, k], k, last)
    area_last = area[np.arange(n_c), last]
    growth = np.log10(area_last / a_nom)
    dist = np.hypot(cyk - cyk[:, [mid]], cxk - cxk[:, [mid]]) / np.sqrt(a_nom)[:, None]
    drift = np.where(ok, dist, 0.0).max(axis=1)

    objects: dict[int, list] = {}

    def objs(k: int) -> list:
        if k not in objects:
            objects[k] = ndimage.find_objects(label_at[k])
        return objects[k]

    sk_nom = np.zeros(n_c, dtype=np.int64)
    sk_last = np.zeros(n_c, dtype=np.int64)
    for i in range(n_c):
        sk_nom[i] = _crop_skeleton_pixels(label_at[mid], objs(mid), int(own_label[i, mid]))
        k = int(last[i])
        if k == mid:
            sk_last[i] = sk_nom[i]
        else:
            sk_last[i] = _crop_skeleton_pixels(label_at[k], objs(k), int(own_label[i, k]))
    skel_change = np.log10(np.maximum(sk_last, 1) / np.maximum(sk_nom, 1))

    rows: list[dict[str, Any]] = []
    labels_out = np.zeros((h, w), dtype=np.int32)
    nominal_objects = objs(mid)
    for i, c in enumerate(keep):
        sl = nominal_objects[c - 1]
        member = lab0[sl] == c
        labels_out[sl][member] = i + 1
        ys, xs = np.nonzero(member)
        n_px = ys.size
        cov = np.cov(np.vstack([ys, xs]), bias=True) if n_px > 1 else np.zeros((2, 2))
        eig = np.sort(np.linalg.eigvalsh(cov + np.eye(2) / 12.0))
        elong = float(math.sqrt(eig[1] / eig[0]))
        bbox_area = (sl[0].stop - sl[0].start) * (sl[1].stop - sl[1].start)
        peak_y, peak_x = divmod(int(pk_idx[i]), w)
        rows.append(
            {
                "component": i + 1,
                "peak_yx": [peak_y, peak_x],
                "peak_idx": int(pk_idx[i]),
                "peak_level": int(pk_lvl[i]),
                "area": int(a_nom[i]),
                "centroid_yx": [float(cy0[c]), float(cx0[c])],
                "s_birth": float(s_birth[i]),
                "s_death": float(s_death[i]),
                "essential": bool(peak_death[i] == ESSENTIAL),
                "merged_in_window": bool(not ok[i, n_k - 1]),
                "geometry": {
                    "log_area": float(np.log10(a_nom[i])),
                    "peak_margin_log": float(peak_margin[i]),
                    "elongation": elong,
                    "bbox_fill": float(n_px / bbox_area),
                },
                "features": {
                    "down_slack_log": float(down_slack[i]),
                    "area_growth_log": float(growth[i]),
                    "area_retention_tight": float(retention[i]),
                    "centroid_drift_norm": float(drift[i]),
                    "skeleton_log_change": float(skel_change[i]),
                    "hole_life_log": float(hole_life_log[i]),
                    "n_significant_peaks": float(n_sig[i]),
                },
            }
        )
    return {
        "components": rows,
        "labels": labels_out,
        "n_components_total": int(n0),
        "n_dropped_small": n_dropped,
        "nominal_level": int(u_nom),
        "s_nominal": s_nom,
        "grid_levels": [int(g) for g in grid],
    }
