"""Geometry-stratified, label-coverage-conditioned surface evaluation.

Held-out evaluation can be optimistic even when it is clean: if the labeled
regions over-represent easy geometry (gentle curvature, wide sheet spacing) and
under-represent hard geometry, an aggregate improvement can come entirely from
the easy strata while the model is no better, or worse, where the scroll is
hard. This module is the smallest experiment that exposes that, and it is not a
model.

Everything that decides the verdict is frozen *before* any performance is read:

* the covariates, bin edges and which bins are designated *hard*;
* the minimum evaluation counts and target share a stratum needs;
* the practical-improvement margin and the bootstrap budget and seed.

The frozen spec is hash-pinned (``spec-hash``). Covariates describe geometry
only. They are measured identically for the committed ROIs and for the actual
target scroll (the *inventory*), so each bin reports both how much of the
target it is and how much of it the labels cover.

A candidate passes a covariate only if every required stratum was adequately
evaluated, nothing regressed significantly, the improvement re-weighted to the
actual target scroll (not the labeled-set mean, which over-weights easy strata)
cleared the margin, and improvement was *demonstrated* (CI lower bound above
the margin) in every evaluable stratum that is hard or materially
under-represented by the labels. Well-covered easy strata only need to show no
regression, since a saturated baseline there should not block. Failed and
missing regions keep the preregistered failure value in the denominator, as in
``scroliq-eval``.

Limitations that are deliberately not hidden: strata are marginal (one
covariate at a time), so a joint hard corner such as high curvature *and*
compressed spacing can still be unevaluated; passing says nothing about sheet
identity, topology or readability; and the covariates must come from a surface
that does not depend on the models being compared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from bisect import bisect_right
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .model_eval import ValidationError, bootstrap_mean_ci
from .tifxyz_audit import load_valid_vertices

SCHEMA_VERSION = 1
TOOL = "scroliq-geometry-strata"
MEASURE_METHOD = "scroliq-geometry-strata-measure-v1"
VERDICT_PASS = "STRATA_PASS"
VERDICT_BLOCKED = "STRATA_BLOCKED"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MIN_ROIS_FLOOR = 3  # a bootstrap CI over fewer regions is degenerate
CONTAINMENT_EPS = 1e-6

# Reason codes in precedence order (the first present becomes the verdict).
REASONS = (
    "UNMEASURED_TARGET",
    "UNMEASURED_ROI",
    "INVENTORY_DOES_NOT_CONTAIN_ROIS",
    "UNDER_EVALUATED_STRATUM",
    "REGRESSION_IN_STRATUM",
    "TARGET_WEIGHTED_NOT_IMPROVED",
    "HARD_STRATUM_NOT_IMPROVED",
    "UNDER_REPRESENTED_STRATUM_NOT_IMPROVED",
)


class StrataError(ValueError):
    """Raised when an input document violates the contract."""


# --------------------------------------------------------------------------
# small validators
# --------------------------------------------------------------------------
def _canonical(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(document)).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrataError(f"{field} must be a non-empty string")
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise StrataError(f"{field} must be an identifier-like string")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrataError(f"{field} must be a number")
    if not math.isfinite(float(value)):
        raise StrataError(f"{field} must be finite")
    return float(value)


def _positive(value: Any, field: str) -> float:
    number = _finite(value, field)
    if number <= 0:
        raise StrataError(f"{field} must be > 0")
    return number


def _fraction(value: Any, field: str, *, open_low: bool = False) -> float:
    number = _finite(value, field)
    if not (0 < number <= 1 if open_low else 0 <= number <= 1):
        raise StrataError(f"{field} must be in {'(0, 1]' if open_low else '[0, 1]'}")
    return number


def _int_at_least(value: Any, field: str, floor: int) -> int:
    if type(value) is not int or value < floor:
        raise StrataError(f"{field} must be an integer >= {floor}")
    return value


def _schema_v1(document: Any, label: str) -> None:
    if not isinstance(document, Mapping):
        raise StrataError(f"{label} must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise StrataError(f"{label}.schema_version must be {SCHEMA_VERSION}")


def _measurement(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise StrataError(f"{label}.measurement must be an object")
    return {
        "method": _text(value.get("method"), f"{label}.measurement.method"),
        "reference": _text(value.get("reference"), f"{label}.measurement.reference"),
    }


# --------------------------------------------------------------------------
# spec
# --------------------------------------------------------------------------
def validate_spec(document: Any) -> dict[str, Any]:
    """Validate the frozen, preregistered stratification contract."""
    _schema_v1(document, "spec")
    metric = document.get("metric")
    if not isinstance(metric, Mapping) or type(metric.get("higher_is_better")) is not bool:
        raise StrataError("spec.metric must declare a boolean higher_is_better")
    bootstrap = document.get("bootstrap")
    if not isinstance(bootstrap, Mapping):
        raise StrataError("spec.bootstrap must be an object")
    samples = _int_at_least(bootstrap.get("samples"), "spec.bootstrap.samples", 100)
    seed = _int_at_least(bootstrap.get("seed"), "spec.bootstrap.seed", 0)

    rows = document.get("covariates")
    if not isinstance(rows, list) or not rows:
        raise StrataError("spec.covariates must be a non-empty list")
    covariates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"spec.covariates[{index}]"
        if not isinstance(row, Mapping):
            raise StrataError(f"{where} must be an object")
        name = _name(row.get("name"), f"{where}.name")
        if name in seen:
            raise StrataError(f"duplicate covariate: {name}")
        seen.add(name)
        edges_raw = row.get("edges")
        if not isinstance(edges_raw, list) or not edges_raw:
            raise StrataError(f"{where}.edges must be a non-empty list")
        edges = [_finite(e, f"{where}.edges[]") for e in edges_raw]
        if any(b <= a for a, b in zip(edges, edges[1:])):
            raise StrataError(f"{where}.edges must be strictly increasing")
        bin_count = len(edges) + 1
        hard = row.get("hard_bins")
        if (
            not isinstance(hard, list)
            or not hard
            or any(type(h) is not int or not 0 <= h < bin_count for h in hard)
            or len(set(hard)) != len(hard)
        ):
            raise StrataError(
                f"{where}.hard_bins must list at least one distinct bin index in "
                f"[0, {bin_count - 1}]; designating hard geometry is the point"
            )
        covariates.append(
            {
                "name": name,
                "unit": row.get("unit") if isinstance(row.get("unit"), str) else None,
                "edges": edges,
                "hard_bins": sorted(hard),
                "min_rois_per_bin": _int_at_least(
                    row.get("min_rois_per_bin"), f"{where}.min_rois_per_bin", MIN_ROIS_FLOOR
                ),
                "min_target_fraction": _fraction(
                    row.get("min_target_fraction"), f"{where}.min_target_fraction", open_low=True
                ),
                "low_coverage_ratio": _fraction(
                    row.get("low_coverage_ratio"), f"{where}.low_coverage_ratio", open_low=True
                ),
                "max_unmeasured_fraction": _fraction(
                    row.get("max_unmeasured_fraction"), f"{where}.max_unmeasured_fraction"
                ),
                "margin": _finite(row.get("margin"), f"{where}.margin"),
            }
        )
        if covariates[-1]["margin"] < 0:
            raise StrataError(f"{where}.margin must be >= 0")

    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": _text(document.get("dataset"), "spec.dataset"),
        "target": _text(document.get("target"), "spec.target"),
        "measurement": _measurement(document.get("measurement"), "spec"),
        "metric": {
            "name": _name(metric.get("name"), "spec.metric.name"),
            "higher_is_better": metric["higher_is_better"],
            "failure_value": _finite(metric.get("failure_value"), "spec.metric.failure_value"),
        },
        "bootstrap": {"samples": samples, "seed": seed},
        "covariates": covariates,
    }


# --------------------------------------------------------------------------
# data documents
# --------------------------------------------------------------------------
def _units(rows: Any, label: str, covariate_names: Sequence[str]) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise StrataError(f"{label} must be a non-empty list")
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"{label}[{index}]"
        if not isinstance(row, Mapping):
            raise StrataError(f"{where} must be an object")
        uid = _text(row.get("id"), f"{where}.id")
        if uid in seen:
            raise StrataError(f"duplicate id in {label}: {uid}")
        seen.add(uid)
        raw = row.get("covariates")
        if not isinstance(raw, Mapping):
            raise StrataError(f"{where}.covariates must be an object")
        values: dict[str, float | None] = {}
        for name in covariate_names:
            value = raw.get(name)
            if value is None:
                values[name] = None  # explicitly unmeasured
            else:
                values[name] = _finite(value, f"{where}.covariates.{name}")
        units.append({"id": uid, "weight": _positive(row.get("weight"), f"{where}.weight"),
                      "covariates": values})
    return units


def _arm_results(
    document: Any,
    *,
    label: str,
    spec: Mapping[str, Any],
    roi_ids: Sequence[str],
) -> dict[str, Any]:
    """Per-ROI metric under the preregistered failure value (never dropped)."""
    _schema_v1(document, label)
    model = _text(document.get("model"), f"{label}.model")
    if document.get("dataset") != spec["dataset"]:
        raise StrataError(f"{label}.dataset does not match spec.dataset")
    rows = document.get("regions")
    if not isinstance(rows, list):
        raise StrataError(f"{label}.regions must be a list")
    metric = spec["metric"]["name"]
    failure_value = spec["metric"]["failure_value"]
    expected = set(roi_ids)
    found: dict[str, float] = {}
    failed: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise StrataError(f"{label}.regions entries must be objects")
        rid = _text(row.get("id"), f"{label}.regions[].id")
        if rid not in expected:
            raise StrataError(f"{label} contains a region outside the committed ROI set: {rid}")
        if rid in found or rid in failed:
            raise StrataError(f"{label} repeats region {rid}")
        status = row.get("status")
        if status == "ok":
            metrics = row.get("metrics")
            if not isinstance(metrics, Mapping) or metric not in metrics:
                raise StrataError(f"{label} region {rid}: primary metric {metric!r} is missing")
            found[rid] = _finite(metrics[metric], f"{label} region {rid}.{metric}")
        elif status == "failed":
            failed.add(rid)
        else:
            raise StrataError(f"{label} region {rid}: status must be ok or failed")
    missing = sorted(expected - set(found) - failed)
    values = {rid: found.get(rid, failure_value) for rid in roi_ids}
    return {
        "model": model,
        "values": values,
        "failed": sorted(failed),
        "missing": missing,
    }


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def _derived_seed(base: int, *parts: str) -> int:
    raw = hashlib.sha256("|".join([str(base), *parts]).encode("utf-8")).digest()
    return int.from_bytes(raw[:4], "big")


def _ci(values: Sequence[float], *, samples: int, seed: int, need: int) -> dict[str, Any]:
    n = len(values)
    out: dict[str, Any] = {
        "n": n,
        "mean": float(np.mean(values)) if n else None,
        "ci_low": None,
        "ci_high": None,
    }
    if n >= need:
        low, high = bootstrap_mean_ci(values, seed=seed, samples=samples)
        out["ci_low"], out["ci_high"] = low, high
    return out


def _poststratified(
    strata: Sequence[tuple[float, np.ndarray]], *, samples: int, seed: int
) -> dict[str, Any]:
    """Target-weighted improvement over supported strata with a stratified bootstrap."""
    if not strata:
        return {"estimate": None, "ci_low": None, "ci_high": None}
    weights = np.asarray([w for w, _ in strata], dtype=np.float64)
    weights = weights / weights.sum()
    means = np.asarray([float(v.mean()) for _, v in strata])
    rng = np.random.default_rng(seed)
    draws = np.zeros(samples)
    for weight, (_, values) in zip(weights, strata):
        idx = rng.integers(0, values.size, size=(samples, values.size))
        draws += weight * values[idx].mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975])
    return {"estimate": float((weights * means).sum()), "ci_low": float(low), "ci_high": float(high)}


def _bin_index(value: float | None, edges: Sequence[float]) -> int | None:
    if value is None:
        return None
    return bisect_right(edges, value)  # [e_i, e_{i+1}) with open outer bins


def _bin_label(edges: Sequence[float], index: int) -> str:
    if index == 0:
        return f"(-inf,{edges[0]:g})"
    if index == len(edges):
        return f"[{edges[-1]:g},+inf)"
    return f"[{edges[index - 1]:g},{edges[index]:g})"


# --------------------------------------------------------------------------
# per-covariate analysis
# --------------------------------------------------------------------------
def _analyse_covariate(
    cov: Mapping[str, Any],
    *,
    inventory: Sequence[Mapping[str, Any]],
    rois: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    higher_is_better: bool,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    name, edges = cov["name"], cov["edges"]
    bin_count = len(edges) + 1
    need = cov["min_rois_per_bin"]
    total_target = sum(u["weight"] for u in inventory)

    target_w = [0.0] * bin_count
    target_n = [0] * bin_count
    unmeasured_w = 0.0
    unmeasured_n = 0
    for unit in inventory:
        index = _bin_index(unit["covariates"].get(name), edges)
        if index is None:
            unmeasured_w += unit["weight"]
            unmeasured_n += 1
        else:
            target_w[index] += unit["weight"]
            target_n[index] += 1

    roi_in_bin: list[list[str]] = [[] for _ in range(bin_count)]
    roi_w = [0.0] * bin_count
    unmeasured_rois: list[str] = []
    for roi in rois:
        index = _bin_index(roi["covariates"].get(name), edges)
        if index is None:
            unmeasured_rois.append(roi["id"])
        else:
            roi_in_bin[index].append(roi["id"])
            roi_w[index] += roi["weight"]

    sign = 1.0 if higher_is_better else -1.0
    delta = {r["id"]: sign * (candidate[r["id"]] - baseline[r["id"]]) for r in rois}
    overall_labeled = sum(roi_w) / total_target if total_target else 0.0

    reasons: list[dict[str, str]] = []
    bins: list[dict[str, Any]] = []
    supported: list[tuple[float, np.ndarray]] = []
    for i in range(bin_count):
        ids = roi_in_bin[i]
        fraction = target_w[i] / total_target
        labeled_of_bin = roi_w[i] / target_w[i] if target_w[i] > 0 else None
        ratio = (
            labeled_of_bin / overall_labeled
            if labeled_of_bin is not None and overall_labeled > 0
            else None
        )
        required = fraction >= cov["min_target_fraction"]
        evaluable = len(ids) >= need
        under_represented = ratio is not None and ratio <= cov["low_coverage_ratio"]
        if required and not evaluable:
            state = "under-evaluated"
        elif evaluable:
            state = "evaluated"
        else:
            state = "negligible" if target_n[i] else "empty"
        values = [delta[r] for r in ids]
        stats = _ci(
            values, samples=samples, seed=_derived_seed(seed, name, str(i)), need=need
        )
        bins.append(
            {
                "index": i,
                "label": _bin_label(edges, i),
                "hard": i in cov["hard_bins"],
                "under_represented": under_represented,
                "state": state,
                "target": {"units": target_n[i], "weight": target_w[i], "fraction": fraction},
                "labeled": {
                    "rois": len(ids),
                    "weight": roi_w[i],
                    "fraction_of_bin": labeled_of_bin,
                    "representation_ratio": ratio,
                },
                "baseline_mean": float(np.mean([baseline[r] for r in ids])) if ids else None,
                "candidate_mean": float(np.mean([candidate[r] for r in ids])) if ids else None,
                "improvement": stats,
            }
        )
        if labeled_of_bin is not None and labeled_of_bin > 1 + CONTAINMENT_EPS:
            reasons.append(
                {
                    "code": "INVENTORY_DOES_NOT_CONTAIN_ROIS",
                    "detail": f"bin {i} labeled weight exceeds the target weight "
                    f"({labeled_of_bin:.3g}x); the ROIs are not a subset of the inventory",
                }
            )
        if state == "under-evaluated":
            reasons.append(
                {
                    "code": "UNDER_EVALUATED_STRATUM",
                    "detail": f"bin {i} {_bin_label(edges, i)} is {fraction:.3g} of the target "
                    f"but has {len(ids)} ROI(s); need {need}",
                }
            )
        if evaluable:
            if stats["ci_high"] is not None and stats["ci_high"] < 0:
                reasons.append(
                    {
                        "code": "REGRESSION_IN_STRATUM",
                        "detail": f"bin {i} {_bin_label(edges, i)} improvement CI "
                        f"[{stats['ci_low']:.4g}, {stats['ci_high']:.4g}] is entirely below 0",
                    }
                )
            demonstrated = stats["ci_low"] is not None and stats["ci_low"] > cov["margin"]
            if not demonstrated and (i in cov["hard_bins"] or under_represented):
                hard = i in cov["hard_bins"]
                why = (
                    f"hard bin {i}" if hard
                    else f"under-represented bin {i} (labels cover {ratio:.2g}x the "
                    f"average; threshold {cov['low_coverage_ratio']:g})"
                )
                reasons.append(
                    {
                        "code": (
                            "HARD_STRATUM_NOT_IMPROVED" if hard
                            else "UNDER_REPRESENTED_STRATUM_NOT_IMPROVED"
                        ),
                        "detail": f"{why} {_bin_label(edges, i)}: improvement CI lower "
                        f"bound {stats['ci_low']:.4g} does not exceed margin {cov['margin']:g}",
                    }
                )
            if required:
                supported.append((fraction, np.asarray(values, dtype=np.float64)))

    unmeasured_fraction = unmeasured_w / total_target
    if unmeasured_fraction > cov["max_unmeasured_fraction"]:
        reasons.append(
            {
                "code": "UNMEASURED_TARGET",
                "detail": f"{unmeasured_fraction:.3g} of the target has no {name} measurement; "
                f"allowed {cov['max_unmeasured_fraction']:g}",
            }
        )
    if unmeasured_rois:
        reasons.append(
            {
                "code": "UNMEASURED_ROI",
                "detail": f"{len(unmeasured_rois)} committed ROI(s) lack a {name} value and "
                "cannot be assigned to a stratum: " + ", ".join(sorted(unmeasured_rois)[:5]),
            }
        )

    all_delta = list(delta.values())
    overall = _ci(all_delta, samples=samples, seed=_derived_seed(seed, name, "overall"), need=need)
    weighted = _poststratified(
        supported, samples=samples, seed=_derived_seed(seed, name, "poststratified")
    )
    if not (weighted["ci_low"] is not None and weighted["ci_low"] > cov["margin"]):
        reasons.append(
            {
                "code": "TARGET_WEIGHTED_NOT_IMPROVED",
                "detail": f"improvement re-weighted to the target scroll has CI lower bound "
                f"{weighted['ci_low']} (labeled-set mean {overall['mean']}); required > "
                f"{cov['margin']:g}",
            }
        )

    reasons.sort(key=lambda r: REASONS.index(r["code"]))
    supported_fraction = sum(w for w, _ in supported)
    return {
        "name": name,
        "unit": cov["unit"],
        "edges": edges,
        "hard_bins": cov["hard_bins"],
        "thresholds": {
            "min_rois_per_bin": need,
            "min_target_fraction": cov["min_target_fraction"],
            "low_coverage_ratio": cov["low_coverage_ratio"],
            "max_unmeasured_fraction": cov["max_unmeasured_fraction"],
            "margin": cov["margin"],
        },
        "bins": bins,
        "unmeasured": {
            "target_units": unmeasured_n,
            "target_fraction": unmeasured_fraction,
            "rois": sorted(unmeasured_rois),
        },
        "labeled_fraction_of_target": overall_labeled,
        "overall_improvement": overall,
        "target_weighted_improvement": {
            "supported_target_fraction": supported_fraction,
            **weighted,
        },
        "reasons": reasons,
        "verdict": "BLOCKED" if reasons else "GENERALIZES",
        "primary_reason": reasons[0]["code"] if reasons else None,
    }


# --------------------------------------------------------------------------
# public evaluation
# --------------------------------------------------------------------------
def evaluate_strata(
    spec_document: Any,
    inventory_document: Any,
    regions_document: Any,
    baseline_document: Any,
    candidate_document: Any,
) -> dict[str, Any]:
    spec = validate_spec(spec_document)
    names = [c["name"] for c in spec["covariates"]]

    _schema_v1(inventory_document, "inventory")
    if inventory_document.get("target") != spec["target"]:
        raise StrataError("inventory.target does not match spec.target")
    if _measurement(inventory_document.get("measurement"), "inventory") != spec["measurement"]:
        raise StrataError(
            "inventory.measurement differs from spec.measurement; covariates must be "
            "measured with one method on one reference surface"
        )
    inventory = _units(inventory_document.get("units"), "inventory.units", names)

    _schema_v1(regions_document, "regions")
    if regions_document.get("dataset") != spec["dataset"]:
        raise StrataError("regions.dataset does not match spec.dataset")
    if _measurement(regions_document.get("measurement"), "regions") != spec["measurement"]:
        raise StrataError("regions.measurement differs from spec.measurement")
    rois = _units(regions_document.get("regions"), "regions.regions", names)
    if len(rois) < MIN_ROIS_FLOOR:
        raise StrataError(f"at least {MIN_ROIS_FLOOR} committed ROIs are required")
    roi_ids = [r["id"] for r in rois]

    base = _arm_results(baseline_document, label="baseline", spec=spec, roi_ids=roi_ids)
    cand = _arm_results(candidate_document, label="candidate", spec=spec, roi_ids=roi_ids)
    if base["model"] == cand["model"]:
        raise StrataError("baseline and candidate must be different models")

    boot = spec["bootstrap"]
    covariates = [
        _analyse_covariate(
            cov,
            inventory=inventory,
            rois=rois,
            baseline=base["values"],
            candidate=cand["values"],
            higher_is_better=spec["metric"]["higher_is_better"],
            samples=boot["samples"],
            seed=boot["seed"],
        )
        for cov in spec["covariates"]
    ]
    blocked = [c["name"] for c in covariates if c["verdict"] == "BLOCKED"]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "verdict": VERDICT_BLOCKED if blocked else VERDICT_PASS,
        "blocked_covariates": blocked,
        "spec_sha256": digest(spec_document),
        "inputs_sha256": {
            "inventory": digest(inventory_document),
            "regions": digest(regions_document),
            "baseline": digest(baseline_document),
            "candidate": digest(candidate_document),
        },
        "dataset": spec["dataset"],
        "target": spec["target"],
        "measurement": spec["measurement"],
        "metric": spec["metric"],
        "bootstrap": boot,
        "models": {"baseline": base["model"], "candidate": cand["model"]},
        "arm_failures": {
            "baseline": {"failed": base["failed"], "missing": base["missing"]},
            "candidate": {"failed": cand["failed"], "missing": cand["missing"]},
        },
        "rois": len(rois),
        "target_units": len(inventory),
        "covariates": covariates,
        "limitation": (
            "A pass means: on these committed ROIs, every required stratum of every "
            "preregistered covariate was adequately evaluated, nothing regressed "
            "significantly, and the improvement, re-weighted to the actual target scroll, "
            "cleared the margin and did so in every hard or under-represented stratum. Strata are marginal "
            "(one covariate at a time), so joint hard geometry can still be unevaluated. "
            "It does not establish sheet identity, topology, CT support, or readability."
        ),
    }


# --------------------------------------------------------------------------
# geometry measurement (curvature and axis tilt only)
# --------------------------------------------------------------------------
def _quad_geometry(xyz: np.ndarray, valid: np.ndarray) -> dict[str, np.ndarray]:
    p00, p01 = xyz[:-1, :-1], xyz[:-1, 1:]
    p10, p11 = xyz[1:, :-1], xyz[1:, 1:]
    vq = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    c1 = np.cross(p01 - p00, p10 - p00)
    c2 = np.cross(p11 - p01, p10 - p01)
    area = 0.5 * (np.linalg.norm(c1, axis=-1) + np.linalg.norm(c2, axis=-1))
    normal = c1 + c2
    norm = np.linalg.norm(normal, axis=-1)
    ok = vq & np.isfinite(norm) & (norm > 1e-8) & np.isfinite(area)
    unit = np.zeros_like(normal)
    unit[ok] = normal[ok] / norm[ok, None]
    return {
        "ok": ok,
        "area": np.where(ok, area, 0.0),
        "unit": unit,
        "centroid": (p00 + p01 + p10 + p11) / 4.0,
    }


def _pair_curvature(
    unit_a: np.ndarray, unit_b: np.ndarray, cen_a: np.ndarray, cen_b: np.ndarray
) -> np.ndarray:
    """Rotation rate of the normal between adjacent quads: 2 sin(theta/2) / chord."""
    cos = np.clip((unit_a * unit_b).sum(axis=-1), -1.0, 1.0)
    chord = np.linalg.norm(cen_b - cen_a, axis=-1)
    theta = np.arccos(cos)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(chord > 1e-8, 2.0 * np.sin(theta / 2.0) / chord, np.nan)


def measure_surface(path: str | Path) -> dict[str, np.ndarray]:
    """Per-quad weight (area), mean-curvature proxy and axis tilt of one TIFXYZ.

    ``curvature`` is the average, over the two grid directions, of the normal's
    rotation rate between adjacent quads. It is a mean-curvature-magnitude
    proxy: a cylinder of radius R reads 1/(2R) and a sphere 1/R (voxel^-1).
    ``tilt_deg`` is the angle between the sheet and the z axis,
    ``degrees(arcsin(|n_z|))`` (0 when the normal is perpendicular to z).
    """
    xyz, valid, _ = load_valid_vertices(path)
    q = _quad_geometry(xyz, valid)
    ok, unit, cen = q["ok"], q["unit"], q["centroid"]
    h, w = ok.shape
    horizontal = ok[:, :-1] & ok[:, 1:]
    vertical = ok[:-1] & ok[1:]
    ch = np.where(
        horizontal, _pair_curvature(unit[:, :-1], unit[:, 1:], cen[:, :-1], cen[:, 1:]), np.nan
    )
    cv = np.where(
        vertical, _pair_curvature(unit[:-1], unit[1:], cen[:-1], cen[1:]), np.nan
    )
    # direction-wise means first, so a cylinder is not diluted by the flat direction
    rate_h = np.zeros((h, w))
    n_h = np.zeros((h, w))
    rate_v = np.zeros((h, w))
    n_v = np.zeros((h, w))
    for arr, sl_a, sl_b, rate, n in (
        (ch, (slice(None), slice(None, -1)), (slice(None), slice(1, None)), rate_h, n_h),
        (cv, (slice(None, -1), slice(None)), (slice(1, None), slice(None)), rate_v, n_v),
    ):
        finite = np.isfinite(arr)
        safe = np.where(finite, arr, 0.0)
        rate[sl_a] += safe
        rate[sl_b] += safe
        n[sl_a] += finite
        n[sl_b] += finite
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_h = np.where(n_h > 0, rate_h / n_h, np.nan)
        mean_v = np.where(n_v > 0, rate_v / n_v, np.nan)
    both = np.stack([mean_h, mean_v])
    curvature = np.where(
        np.isfinite(both).all(axis=0), both.mean(axis=0), np.nan
    )  # needs both directions; borders and 1-wide strips stay unmeasured
    tilt = np.degrees(np.arcsin(np.clip(np.abs(unit[..., 2]), 0.0, 1.0)))
    return {
        "ok": ok,
        "area": q["area"],
        "curvature": np.where(ok, curvature, np.nan),
        "tilt_deg": np.where(ok, tilt, np.nan),
    }


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float | None:
    mask = np.isfinite(values) & (weights > 0)
    if not mask.any():
        return None
    return float((values[mask] * weights[mask]).sum() / weights[mask].sum())


def measure_units(
    surfaces: Mapping[str, str | Path], *, tile: int = 0
) -> list[dict[str, Any]]:
    """Units for each surface: one per surface (tile=0) or one per tile."""
    if type(tile) is not int or tile < 0:
        raise StrataError("tile must be an integer >= 0")
    units: list[dict[str, Any]] = []
    for sid, path in surfaces.items():
        m = measure_surface(path)
        h, w = m["ok"].shape
        step_r = h if tile == 0 else tile
        step_c = w if tile == 0 else tile
        for r0 in range(0, h, step_r):
            for c0 in range(0, w, step_c):
                sl = (slice(r0, r0 + step_r), slice(c0, c0 + step_c))
                area = m["area"][sl]
                weight = float(area.sum())
                if weight <= 0:
                    continue
                units.append(
                    {
                        "id": sid if tile == 0 else f"{sid}:r{r0}c{c0}",
                        "weight": weight,
                        "covariates": {
                            "mean_abs_curvature": _weighted_mean(m["curvature"][sl], area),
                            "axis_tilt_deg": _weighted_mean(m["tilt_deg"][sl], area),
                        },
                    }
                )
    if not units:
        raise StrataError("no surface contributed a valid quad; nothing was measured")
    return units


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _load(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StrataError(f"cannot read {label}: {exc}") from exc


def _write_create_only(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_hash = sub.add_parser("spec-hash", help="print the binding SHA-256 of a frozen spec")
    p_hash.add_argument("--spec", required=True)

    p_measure = sub.add_parser(
        "measure", help="measure curvature/tilt of TIFXYZ surfaces into an inventory or ROI file"
    )
    p_measure.add_argument("--surface", action="append", required=True, metavar="ID=PATH")
    p_measure.add_argument("--as", dest="kind", choices=("inventory", "regions"), required=True)
    p_measure.add_argument("--target", help="target scroll id (inventory)")
    p_measure.add_argument("--dataset", help="dataset id (regions)")
    p_measure.add_argument("--reference", required=True,
                           help="identity of the reference surface the covariates describe")
    p_measure.add_argument("--tile", type=int, default=0,
                           help="tile edge in grid vertices; 0 = one unit per surface")
    p_measure.add_argument("--out", required=True)

    p_eval = sub.add_parser("evaluate", help="apply the frozen stratification gate")
    for flag in ("spec", "inventory", "regions", "baseline", "candidate"):
        p_eval.add_argument(f"--{flag}", required=True)
    p_eval.add_argument("--expect-spec-sha256", help="refuse unless the spec hashes to this")
    p_eval.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "spec-hash":
            spec_document = _load(args.spec, "spec")
            validate_spec(spec_document)
            print(digest(spec_document))
            return 0

        out = Path(args.out)
        if out.exists():
            parser.error(f"output already exists: {out}")

        if args.command == "measure":
            surfaces: dict[str, str] = {}
            for item in args.surface:
                sid, sep, path = item.partition("=")
                if not sep or not sid or not path or sid in surfaces:
                    raise StrataError(f"--surface must be unique ID=PATH, got {item!r}")
                surfaces[sid] = path
            scope = args.target if args.kind == "inventory" else args.dataset
            if not scope:
                raise StrataError(
                    "--target is required for inventory" if args.kind == "inventory"
                    else "--dataset is required for regions"
                )
            try:
                units = measure_units(surfaces, tile=args.tile)
            except ValueError as exc:  # unreadable TIFXYZ
                raise StrataError(str(exc)) from exc
            document: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "measurement": {"method": MEASURE_METHOD, "reference": args.reference},
            }
            if args.kind == "inventory":
                document.update(target=scope, units=units)
            else:
                document.update(dataset=scope, regions=units)
            _write_create_only(out, document)
            print(f"measured {len(units)} unit(s) from {len(surfaces)} surface(s)")
            return 0

        spec_document = _load(args.spec, "spec")
        if args.expect_spec_sha256 and digest(spec_document) != args.expect_spec_sha256:
            raise StrataError("spec hash differs from --expect-spec-sha256; the spec was edited")
        report = evaluate_strata(
            spec_document,
            _load(args.inventory, "inventory"),
            _load(args.regions, "regions"),
            _load(args.baseline, "baseline results"),
            _load(args.candidate, "candidate results"),
        )
        _write_create_only(out, report)
        print(
            f"{report['verdict']}: "
            + (f"blocked on {', '.join(report['blocked_covariates'])}"
               if report["blocked_covariates"] else "all covariates generalize")
        )
        return 0 if report["verdict"] == VERDICT_PASS else 1
    except (StrataError, ValidationError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
