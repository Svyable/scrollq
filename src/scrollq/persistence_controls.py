"""Deterministic control suite for the threshold-persistence audit.

Nothing here is evidence about real scrolls. It checks that the instrument
does what the protocol says, and that the frozen decision rule behaves:

* **engine oracles** - persistence-derived Betti numbers equal an independent
  connected-component count at every level, ``beta0 - beta1`` equals an
  independent Euler characteristic, diagrams are symmetric under the eight
  grid symmetries, and the oracle itself fails when given the wrong
  connectivity convention (it has teeth);
* **invariance controls** - every rank feature is bitwise identical under
  strictly monotone recalibration while a value-parameterised persistence is
  not (the control can fail);
* **decision-rule scenarios** - on synthetic regions with per-domain
  calibration shift: a persistence-only planted effect must be found
  (sensitivity), identical class generators must not (specificity), and a class
  difference that peak probability already explains must not be credited to
  persistence.

The planted effect is a sub-nominal "skirt": it is invisible at the nominal
threshold by construction, so a positive result shows the pipeline can detect a
difference that exists only in the sweep. That is a statement about the
instrument, not about papyrus. Seeds ``100000+`` were used while developing the
generators and are not held-out; the reported run uses ``700000+``.
"""

from __future__ import annotations

import hashlib
import platform
from typing import Any, Sequence

import numpy as np
from scipy import ndimage

from . import persistence as ps
from . import persistence_audit as pa

DEV_SEED_BASE = 100_000
DEFAULT_SEED_BASE = 700_000

H = W = 64
TAU = 0.5
N_DOMAINS = 4
INK_REGIONS = 8
BLANK_REGIONS = 5
INK_STROKES = 3
INREGION_FP_STROKES = 3
BLANK_STROKES = 6

# Stroke styles. ``core`` is the plateau-amplitude range; ``skirt`` is (amplitude,
# sigma_px) of the sub-nominal skirt that only a threshold sweep can see.
INK_STYLE = {"core": (0.62, 0.90), "skirt": (0.12, 8.0)}
SKIRTED_STYLE = {"core": (0.62, 0.90), "skirt": (0.45, 5.0)}
LOW_CORE_STYLE = {"core": (0.52, 0.80), "skirt": (0.12, 8.0)}
SCENARIOS: dict[str, dict[str, Any]] = {
    "planted_sweep_effect": {
        "inregion": SKIRTED_STYLE, "blank": SKIRTED_STYLE,
        "expected": "adds_signal",
    },
    "null_no_effect": {
        "inregion": INK_STYLE, "blank": INK_STYLE,
        "expected": "no_signal",
    },
    "baseline_explained": {
        "inregion": LOW_CORE_STYLE, "blank": LOW_CORE_STYLE,
        "expected": "no_signal",
    },
    # a region-level property: blank regions carry the sweep-visible skirt, while false
    # positives inside an ink region are drawn like ink
    "region_confound_only": {
        "inregion": INK_STYLE, "blank": SKIRTED_STYLE,
        "expected": "no_signal",
    },
}
MIN_SENSITIVITY = 0.75
MAX_FALSE_ALARM = 0.17
MIN_CONFOUND_EXERCISED = 0.5

REMAP_POOL = {
    "identity": lambda v: v,
    "cube": lambda v: v**3,
    "sqrt": lambda v: np.sqrt(v),
    "expm1": lambda v: np.expm1(3.0 * v) / np.expm1(3.0),
}


# ---------------------------------------------------------------- engine oracles


def _oracle_betti(levels: np.ndarray, u: int, connectivity8: bool = True) -> tuple[int, int]:
    fg = levels >= u
    structure = ps.STRUCT8 if connectivity8 else None
    _, b0 = ndimage.label(fg, structure=structure)
    h, w = levels.shape
    bg = np.ones((h + 2, w + 2), dtype=bool)
    bg[1:-1, 1:-1] = ~fg | (levels < 0)
    lab, n = ndimage.label(bg)
    outside = np.zeros(n + 1, dtype=bool)
    for edge in (lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]):
        outside[np.unique(edge)] = True
    invalid = np.zeros((h + 2, w + 2), dtype=bool)
    invalid[1:-1, 1:-1] = levels < 0
    outside[np.unique(lab[invalid])] = True
    outside[0] = True
    return int(b0), int(sum(1 for i in range(1, n + 1) if not outside[i]))


def _random_field(rng: np.random.Generator, trial: int) -> tuple[np.ndarray, np.ndarray]:
    h, w = (int(v) for v in rng.integers(8, 28, size=2))
    kind = trial % 4
    if kind == 0:
        f = rng.random((h, w))
    elif kind == 1:
        f = ndimage.gaussian_filter(rng.random((h, w)), 1.2)
    elif kind == 2:
        f = rng.integers(0, 5, size=(h, w)).astype(np.float64)
    else:
        f = np.floor(ndimage.gaussian_filter(rng.random((h, w)), 1.0) * 255.0)
    valid = np.ones((h, w), dtype=bool)
    if trial % 3 == 0:
        valid = rng.random((h, w)) > 0.15
        if not valid.any():
            valid[0, 0] = True
    return f, valid


def _diagram_signature(f: np.ndarray) -> tuple:
    lv = ps.dense_levels(f, np.ones(f.shape, dtype=bool))
    d = ps.h0_diagram(lv.levels)
    h = ps.h1_holes(lv.levels)
    return (
        sorted(zip(d.birth.tolist(), d.death.tolist())),
        sorted(zip(h.lo.tolist(), h.hi.tolist())),
    )


def engine_oracles(seed: int, n_fields: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    checked = mismatches = euler_checked = euler_mismatches = 0
    wrong_checked = wrong_disagree = 0
    for trial in range(n_fields):
        f, valid = _random_field(rng, trial)
        lv = ps.dense_levels(f, valid)
        d = ps.h0_diagram(lv.levels)
        holes = ps.h1_holes(lv.levels)
        for u in range(lv.n_levels):
            got = ps.betti_at(d, holes, u)
            checked += 1
            if got != _oracle_betti(lv.levels, u):
                mismatches += 1
            if valid.all():
                euler_checked += 1
                if ps.euler_characteristic(lv.levels >= u) != got[0] - got[1]:
                    euler_mismatches += 1
            if u % 5 == 0:
                wrong_checked += 1
                wrong_disagree += int(got[0] != _oracle_betti(lv.levels, u, connectivity8=False)[0])
    sym_rng = np.random.default_rng(seed + 1)
    sym_fields = 6
    sym_ok = 0
    for _ in range(sym_fields):
        f = ndimage.gaussian_filter(sym_rng.random((24, 31)), 1.3)
        base = _diagram_signature(f)
        same = True
        for k in range(4):
            for flip in (False, True):
                g = np.rot90(f, k)
                g = g.T if flip else g
                same &= _diagram_signature(np.ascontiguousarray(g)) == base
        sym_ok += int(same)
    return {
        "levels_checked": checked,
        "betti_mismatches": mismatches,
        "euler_checked": euler_checked,
        "euler_mismatches": euler_mismatches,
        "dihedral_fields": sym_fields,
        "dihedral_invariant": sym_ok,
        "wrong_convention_checked": wrong_checked,
        "wrong_convention_disagreements": wrong_disagree,
    }


# ------------------------------------------------------------ synthetic regions


def _stroke_distance(rng: np.random.Generator, cy: float, cx: float) -> np.ndarray:
    length = rng.uniform(12.0, 18.0)
    angle = rng.uniform(0.0, np.pi)
    bend = rng.uniform(-3.0, 3.0)
    t = np.linspace(-0.5, 0.5, 48)
    ys = cy + t * length * np.sin(angle) + bend * (1 - 4 * t**2) * np.cos(angle)
    xs = cx + t * length * np.cos(angle) - bend * (1 - 4 * t**2) * np.sin(angle)
    mask = np.zeros((H, W), dtype=bool)
    mask[np.clip(np.rint(ys).astype(int), 0, H - 1), np.clip(np.rint(xs).astype(int), 0, W - 1)] = True
    return ndimage.distance_transform_edt(~mask)


def synth_region(
    rng: np.random.Generator,
    strokes: Sequence[tuple[dict[str, Any], bool]],
    noise: float,
) -> tuple[np.ndarray, np.ndarray]:
    """One region in calibrated space (nominal threshold 0.5) and its ink labels.

    ``strokes`` lists ``(style, is_ink)``; only ink strokes enter the label mask, so a
    non-ink stroke in the same region is a within-region false positive.
    """
    cells = rng.permutation(9)[: len(strokes)]
    field = np.zeros((H, W))
    ink = np.zeros((H, W), dtype=bool)
    for cell, (style, is_ink) in zip(cells.tolist(), strokes):
        cy = 10.5 + 21.0 * (cell // 3) + rng.uniform(-3.0, 3.0)
        cx = 10.5 + 21.0 * (cell % 3) + rng.uniform(-3.0, 3.0)
        d = _stroke_distance(rng, cy, cx)
        amp = rng.uniform(*style["core"])
        half = rng.uniform(1.8, 2.6)
        core = amp / (1.0 + np.exp((d - half) / 0.35))
        skirt_amp, skirt_sigma = style["skirt"]
        skirt = skirt_amp * np.exp(-(d**2) / (2.0 * skirt_sigma**2))
        field = np.maximum(field, np.maximum(core, skirt))
        if is_ink:
            ink |= d < half + 1.5
    background = ndimage.gaussian_filter(rng.normal(0.0, 1.0, (H, W)), 1.0) * noise
    return np.clip(field + background, 0.0, 1.0), ink


def _domain_regions(
    rng: np.random.Generator, scenario: dict[str, Any], domain: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    noise = rng.uniform(0.15, 0.30)
    remap_name = list(REMAP_POOL)[int(rng.integers(0, len(REMAP_POOL)))]
    remap = REMAP_POOL[remap_name]
    threshold = float(remap(np.float64(TAU)))
    ink_strokes = [(INK_STYLE, True)] * INK_STROKES + [(scenario["inregion"], False)] * INREGION_FP_STROKES
    specs = [("verified_ink", ink_strokes, noise)] * INK_REGIONS + [
        ("known_false_positive", [(scenario["blank"], False)] * BLANK_STROKES, noise)
    ] * BLANK_REGIONS
    regions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for i, (kind, strokes, region_noise) in enumerate(specs):
        field, ink = synth_region(rng, strokes, region_noise)
        values = remap(field)
        result = pa.measure_region(
            values, np.ones((H, W), dtype=bool),
            ink.astype(np.uint8) if kind == "verified_ink" else None,
            threshold, kind,
        )
        rid = f"{domain}-{kind}-{i}"
        regions.append(
            {"id": rid, "domain": domain, "kind": kind, "status": "ok", "remap": remap_name,
             **result["summary"]}
        )
        for comp in result["components"]:
            rows.append({"region": rid, "domain": domain, "kind": kind, **comp})
    return regions, rows


def synthetic_document(seed: int, scenario: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    regions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for d in range(N_DOMAINS):
        r, c = _domain_regions(rng, scenario, f"synthetic-domain-{d}")
        regions += r
        rows += c
    return {
        "tool": pa.TOOL,
        "protocol": pa.PROTOCOL,
        "spec_sha256": pa.canonical_sha256(pa.SPEC),
        "manifest_sha256": hashlib.sha256(f"synthetic:{seed}".encode()).hexdigest(),
        "selection_contract": dict(pa._CONTRACT),
        "regions": regions,
        "components": rows,
    }


# --------------------------------------------------------- invariance controls


def invariance_controls(seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    field, _ = synth_region(rng, [(INK_STYLE, True)] * 6, 0.2)
    valid = np.ones(field.shape, dtype=bool)
    cfg = pa.sweep_config(pa.SPEC)

    def analyse(values: np.ndarray, tau: float) -> tuple[ps.Levels, int | None, Any, Any, dict[str, Any] | None]:
        lv = ps.dense_levels(values, valid)
        u = ps.nominal_level(lv, tau)
        d = ps.h0_diagram(lv.levels)
        h = ps.h1_holes(lv.levels)
        res = ps.analyze_components(lv, u, cfg, d, h) if u is not None else None
        return lv, u, d, h, res

    lv0, u0, d0, _, res0 = analyse(field.astype(np.float64), TAU)
    base_rank = ps.diagram_persistence(lv0, d0, "rank")
    base_value = ps.diagram_persistence(lv0, d0, "value")
    outcomes = []
    for name in ("cube", "expm1_3x", "sqrt", "scale"):
        g = {
            "cube": pa.REMAPS["cube"],
            "expm1_3x": pa.REMAPS["expm1_3x"],
            "sqrt": np.sqrt,
            "scale": lambda v: 7.0 * v,
        }[name]
        values = g(field.astype(np.float64))
        lv, u, d, _, res = analyse(values, float(g(np.float64(TAU))))
        injective = lv.n_levels == lv0.n_levels
        outcomes.append(
            {
                "remap": name,
                "injective": bool(injective),
                "levels_identical": bool(np.array_equal(lv.levels, lv0.levels) and u == u0),
                "rank_features_identical": bool(
                    res is not None
                    and [c["features"] for c in res["components"]] == [c["features"] for c in res0["components"]]
                    and [c["geometry"] for c in res["components"]] == [c["geometry"] for c in res0["components"]]
                ),
                "rank_persistence_identical": bool(
                    np.array_equal(ps.diagram_persistence(lv, d, "rank"), base_rank)
                ),
                "value_persistence_identical": bool(
                    np.array_equal(ps.diagram_persistence(lv, d, "value"), base_value)
                ),
            }
        )
    return {"n_components": len(res0["components"]), "remaps": outcomes}



# ---------------------------------------------------------- decision scenarios


def run_scenario(name: str, seeds: Sequence[int]) -> dict[str, Any]:
    scenario = SCENARIOS[name]
    runs = []
    for seed in seeds:
        report = pa.evaluate_features(synthetic_document(seed, scenario))
        a_all = report["analyses"]["all"]
        a_in = report["analyses"]["within_region"]
        gates = report["gates"]
        runs.append(
            {
                "seed": seed,
                "verdict": report["verdict"],
                "all": {k: a_all.get(k) for k in ("mean_gain", "ci95", "permutation_p", "n_positive_domains")},
                "within_region": {k: a_in.get(k) for k in ("mean_gain", "ci95", "permutation_p", "n_positive_domains")},
                "all_scope_gates_pass": bool(gates) and all(gates["all"].values()),
                "within_region_gates_pass": bool(gates) and all(gates["within_region"].values()),
                "n_components": report["n_components"],
            }
        )
    hits = sum(1 for r in runs if r["verdict"] == pa.ADDS_SIGNAL)
    gains = [r["all"]["mean_gain"] for r in runs if r["all"]["mean_gain"] is not None]
    return {
        "name": name,
        "expected": scenario["expected"],
        "n": len(runs),
        "adds_signal": hits,
        "all_scope_alone_passes": sum(1 for r in runs if r["all_scope_gates_pass"]),
        "within_region_alone_passes": sum(1 for r in runs if r["within_region_gates_pass"]),
        "verdict_counts": {v: sum(1 for r in runs if r["verdict"] == v) for v in pa.VERDICTS},
        "mean_gain_median": float(np.median(gains)) if gains else None,
        "runs": runs,
    }


# ---------------------------------------------------------------------- suite


def _gate(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "pass": bool(ok), "detail": detail}


def run_controls(*, seed_base: int = DEFAULT_SEED_BASE, n: int = 24, quick: bool = False) -> dict[str, Any]:
    if n < 1:
        raise pa.AuditError("n must be >= 1")
    oracle = engine_oracles(seed_base, 24 if quick else 120)
    inv = invariance_controls(seed_base + 7)
    scenarios = [run_scenario(name, [seed_base + 1000 * (i + 1) + k for k in range(n)])
                 for i, name in enumerate(SCENARIOS)]
    gates: list[dict[str, Any]] = [
        _gate(
            "engine betti == independent label count",
            oracle["betti_mismatches"] == 0 and oracle["levels_checked"] > 0,
            f"{oracle['betti_mismatches']} mismatches over {oracle['levels_checked']} levels",
        ),
        _gate(
            "engine beta0-beta1 == independent Euler count",
            oracle["euler_mismatches"] == 0 and oracle["euler_checked"] > 0,
            f"{oracle['euler_mismatches']} mismatches over {oracle['euler_checked']} levels",
        ),
        _gate(
            "diagrams symmetric under 8 grid symmetries",
            oracle["dihedral_invariant"] == oracle["dihedral_fields"],
            f"{oracle['dihedral_invariant']}/{oracle['dihedral_fields']} fields",
        ),
        _gate(
            "oracle has teeth (wrong connectivity is detected)",
            oracle["wrong_convention_disagreements"] > 0,
            f"{oracle['wrong_convention_disagreements']}/{oracle['wrong_convention_checked']} disagree",
        ),
    ]
    conclusive = [r for r in inv["remaps"] if r["injective"]]
    gates.append(
        _gate(
            "rank features bitwise-invariant to monotone remaps",
            bool(conclusive) and all(r["rank_features_identical"] and r["levels_identical"] for r in conclusive),
            f"{len(conclusive)} injective remaps over {inv['n_components']} components",
        )
    )
    gates.append(
        _gate(
            "invariance control has teeth (value persistence changes)",
            any(not r["value_persistence_identical"] for r in conclusive if r["remap"] in ("cube", "expm1_3x", "sqrt")),
            "value-parameterised persistence differs under a non-affine monotone remap",
        )
    )
    for sc in scenarios:
        rate = sc["adds_signal"] / sc["n"]
        if sc["expected"] == "adds_signal":
            gates.append(
                _gate(
                    f"{sc['name']}: planted persistence-only effect found",
                    rate >= MIN_SENSITIVITY,
                    f"{sc['adds_signal']}/{sc['n']} seeds {pa.ADDS_SIGNAL} (need >= {MIN_SENSITIVITY:.2f})",
                )
            )
        else:
            gates.append(
                _gate(
                    f"{sc['name']}: no signal credited to persistence",
                    rate <= MAX_FALSE_ALARM,
                    f"{sc['adds_signal']}/{sc['n']} seeds {pa.ADDS_SIGNAL} (allowed <= {MAX_FALSE_ALARM:.2f})",
                )
            )
        if sc["name"] == "region_confound_only":
            exercised = sc["all_scope_alone_passes"] / sc["n"]
            gates.append(
                _gate(
                    "region_confound_only: confound is real (cross-region scope alone passes)",
                    exercised >= MIN_CONFOUND_EXERCISED,
                    f"{sc['all_scope_alone_passes']}/{sc['n']} seeds pass the cross-region scope "
                    f"alone (need >= {MIN_CONFOUND_EXERCISED:.2f}); the within-region scope "
                    f"passes {sc['within_region_alone_passes']}/{sc['n']}",
                )
            )
    return {
        "tool": pa.TOOL,
        "schema_version": pa.SCHEMA_VERSION,
        "protocol": pa.PROTOCOL,
        "classification": pa.CLASSIFICATION,
        "synthetic": True,
        "spec_sha256": pa.canonical_sha256(pa.SPEC),
        "seed_base": seed_base,
        "n_per_scenario": n,
        "environment": {"numpy": np.__version__, "python": platform.python_version()},
        "engine_oracles": oracle,
        "invariance": inv,
        "scenarios": scenarios,
        "gates": gates,
        "gate_status": "pass" if all(g["pass"] for g in gates) else "fail",
        "limitation": (
            "Synthetic only. The planted effect is constructed to be invisible at the nominal "
            "threshold, so this shows the pipeline can detect a sweep-only difference and does not "
            "credit one that peak probability explains; it says nothing about whether real ink and "
            "real false positives differ in persistence."
        ),
    }
