"""Reconstruction-family and acquisition-calibration sensitivity audit.

Which ink and geometry claims survive when only the reconstruction mathematics,
or a physically plausible calibration parameter, changes? The measured
projections, the acquisition geometry (except a declared perturbation), the
preprocessing and the downstream geometry/render/ink pipeline are held fixed;
only frozen outputs of each variant are read here. Nothing in this module runs a
reconstruction or imports a tomography package.

Per reference ink component the audit reports whether it is matched in every
variant, how far the inferred surface moves along the reference normal under its
footprint, how neighbouring-sheet separation, fibre orientation and the ink
response position along the normal change, and which components or
known-negative detections a variant manufactures. A component that exists only
under one reconstruction assumption is ``reconstruction_sensitive`` evidence. A
component that survives is ``reconstruction_stable``, which is not prize-grade
ink, readable text or an ink verdict.

Rules that keep the experiment controlled: variant selection must be declared
ink-blind and made before ink inference; every variant must share the family's
projections, preprocessing, coordinate convention and pipeline; a calibration
variant may differ from its baseline only by its declared perturbation, within a
preregistered plausible bound; a variant that did not change the volume proves
nothing and makes the family ``unverified``; a failed reconstruction is listed,
never dropped; and the exact dependency licences of every variant are recorded
rather than inferred from the top-level framework.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.ndimage import label as connected_components

SPEC_SCHEMA = "scroliq-reconstruction-sensitivity-spec-v1"
REPORT_SCHEMA = "scroliq-reconstruction-sensitivity-report-v1"
COORDINATE_SPACE = "level0-voxel-index-zyx"

KINDS = ("official", "lsqr", "lsqr_tikhonov", "other_inverse", "calibration_perturbation")
RECONSTRUCTION_KINDS = ("lsqr", "lsqr_tikhonov", "other_inverse")
OPTIONAL_CHANNELS = ("surface_xyz", "neighbor_xyz", "fiber_angle", "ink_depth_offset")
TOLERANCE_KEYS = ("normal_displacement_voxels", "neighbor_separation_voxels",
                  "fiber_angle_degrees", "ink_depth_offset_voxels")
CHANNEL_METRIC = {"surface_xyz": "normal_displacement", "neighbor_xyz": "neighbor_separation",
                  "fiber_angle": "fiber_orientation", "ink_depth_offset": "ink_depth_offset"}
# metric -> (arrays it needs, tolerance key)
METRICS = {
    "normal_displacement": (("surface_xyz",), "normal_displacement_voxels"),
    "neighbor_separation": (("surface_xyz", "neighbor_xyz"), "neighbor_separation_voxels"),
    "fiber_orientation": (("fiber_angle",), "fiber_angle_degrees"),
    "ink_depth_offset": (("ink_depth_offset",), "ink_depth_offset_voxels"),
}
FINGERPRINT_KEYS = ("projections_sha256", "geometry_sha256", "preprocessing_sha256",
                    "pipeline_sha256", "volume_sha256")
MAX_OVERLAP_CELLS = 50_000_000
CONTROL_SEED = 20261007


class ReconstructionSensitivityError(ValueError):
    """Raised when a spec, input or file violates the contract."""


def _fail(message: str) -> None:
    raise ReconstructionSensitivityError(message)


# --------------------------------------------------------------------------- validation


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    return value.strip()


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        _fail(f"{field} must be lowercase 64-hex")
    return text


def _number(value: Any, field: str, low: float | None = None, high: float | None = None,
            *, open_low: bool = True) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        _fail(f"{field} must be a finite number")
    number = float(value)
    if low is not None and (number <= low if open_low else number < low):
        _fail(f"{field} must be {'>' if open_low else '>='} {low}")
    if high is not None and number > high:
        _fail(f"{field} must be <= {high}")
    return number


def _count(value: Any, field: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{field} must be an integer >= {minimum}")
    return value


def _bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _fail(f"{field} must be a boolean")
    return value


_PERMISSIVE = ("mit", "bsd", "apache-2.0", "isc", "zlib", "psf-2.0", "python-2.0", "0bsd",
               "unlicense", "cc0-1.0", "bsl-1.0", "hpnd")
_WEAK = ("lgpl", "mpl", "epl", "cddl")
_STRONG = ("agpl", "gpl", "sspl", "cc-by-sa", "cc-by-nc")
_RANK = {"permissive": 0, "weak_copyleft": 1, "copyleft": 2, "unknown": 3}


def _license_class(token: str) -> str:
    token = token.strip().lower().removesuffix("+").removesuffix("-only").removesuffix("-or-later")
    if token.startswith(_STRONG):
        return "copyleft"
    if token.startswith(_WEAK):
        return "weak_copyleft"
    return "permissive" if token.startswith(_PERMISSIVE) else "unknown"


def classify_license(expression: Any) -> str:
    """Classify an SPDX-style licence string as permissive/weak_copyleft/copyleft/unknown.

    ``A AND B`` is as restrictive as its worst part, ``A OR B`` as its best part;
    parentheses and anything unrecognised are ``unknown``, never permissive.
    """
    if not isinstance(expression, str) or not expression.strip() or "(" in expression:
        return "unknown"
    worst = max(min(_RANK[_license_class(alt)] for alt in part.split(" or "))
                for part in expression.lower().split(" and "))
    return next(name for name, rank in _RANK.items() if rank == worst)


_LICENSE_ORDER = ("incomplete_manifest", "copyleft_present", "unknown_present",
                  "weak_copyleft_present")


def _overall_license(statuses: Sequence[str]) -> str:
    if not statuses:
        return "not_applicable"
    return next((s for s in _LICENSE_ORDER if s in statuses), "permissive_only")


def _dependencies(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where}.dependencies must be an object (null only for the reference)")
    packages = value.get("packages")
    if not isinstance(packages, list) or not packages:
        _fail(f"{where}.dependencies.packages must list the exact transitive packages")
    seen, rows = set(), []
    for i, row in enumerate(packages):
        if not isinstance(row, dict):
            _fail(f"{where}.dependencies.packages[{i}] must be an object")
        name = _text(row.get("name"), f"{where}.dependencies.packages[{i}].name")
        version = _text(row.get("version"), f"{where}.dependencies.packages[{i}].version")
        licence = row.get("license")
        if (name, version) in seen:
            _fail(f"{where}.dependencies lists {name} {version} twice")
        seen.add((name, version))
        rows.append({"name": name, "version": version,
                     "license": licence if isinstance(licence, str) and licence.strip() else None,
                     "class": classify_license(licence)})
    complete = _bool(value.get("complete_transitive"), f"{where}.dependencies.complete_transitive")
    classes = {r["class"] for r in rows}
    if not complete:
        status = "incomplete_manifest"
    elif "copyleft" in classes:
        status = "copyleft_present"
    elif "unknown" in classes:
        status = "unknown_present"
    elif "weak_copyleft" in classes:
        status = "weak_copyleft_present"
    else:
        status = "permissive_only"
    return {"manifest_sha256": _sha(value.get("manifest_sha256"), f"{where}.dependencies.manifest_sha256"),
            "complete_transitive": complete, "status": status, "packages": rows,
            "copyleft_packages": [f"{r['name']} {r['version']} ({r['license']})"
                                  for r in rows if r["class"] == "copyleft"],
            "unknown_packages": [f"{r['name']} {r['version']}" for r in rows if r["class"] == "unknown"]}


def _variant(row: Any, index: int, family: Mapping[str, Any], bounds: Mapping[str, Any]) -> dict[str, Any]:
    where = f"variants[{index}]"
    if not isinstance(row, dict):
        _fail(f"{where} must be an object")
    vid = _text(row.get("id"), f"{where}.id")
    where = f"variants[{vid}]"
    role, kind = row.get("role"), row.get("kind")
    if role not in ("reference", "variant") or kind not in KINDS:
        _fail(f"{where}.role must be reference|variant and kind one of {list(KINDS)}")
    if (role == "reference") != (kind == "official"):
        _fail(f"{where}: only the reference may have kind 'official', and it must")
    outcome = row.get("outcome")
    if outcome not in ("ok", "failed"):
        _fail(f"{where}.outcome must be ok|failed")
    out: dict[str, Any] = {"id": vid, "role": role, "kind": kind, "outcome": outcome}
    if outcome == "failed":
        out["failure_reason"] = _text(row.get("failure_reason"), f"{where}.failure_reason")
        out["data"] = None
    else:
        out["data"] = _text(row.get("data"), f"{where}.data")
    fingerprint = row.get("fingerprint")
    if not isinstance(fingerprint, dict):
        _fail(f"{where}.fingerprint must be an object")
    out["fingerprint"] = {k: _sha(fingerprint.get(k), f"{where}.fingerprint.{k}") for k in FINGERPRINT_KEYS}
    out["fingerprint"]["coordinate_convention"] = _text(
        fingerprint.get("coordinate_convention"), f"{where}.fingerprint.coordinate_convention")
    for key in ("projections_sha256", "preprocessing_sha256", "pipeline_sha256", "coordinate_convention"):
        if out["fingerprint"][key] != family[key]:
            _fail(f"{where}.fingerprint.{key} differs from the family: the variants would not share "
                  f"the same {key.removesuffix('_sha256')}")
    software = row.get("software")
    algorithm = row.get("algorithm")
    if not isinstance(software, dict) or not isinstance(algorithm, dict) \
            or not isinstance(algorithm.get("parameters"), dict):
        _fail(f"{where}.software and .algorithm (with a parameters object) must be declared")
    out["software"] = {"name": _text(software.get("name"), f"{where}.software.name"),
                       "version": _text(software.get("version"), f"{where}.software.version")}
    out["algorithm"] = {"name": _text(algorithm.get("name"), f"{where}.algorithm.name"),
                        "parameters": json.loads(json.dumps(algorithm["parameters"], sort_keys=True,
                                                            allow_nan=False))}
    if kind == "lsqr_tikhonov":
        _number(out["algorithm"]["parameters"].get("regularisation_strength"),
                f"{where}.algorithm.parameters.regularisation_strength", 0.0)
    if role == "reference":
        if row.get("dependencies") is not None:
            _fail(f"{where}.dependencies must be null for the reference reconstruction")
        if row.get("baseline") is not None or row.get("selection") is not None \
                or row.get("perturbation") is not None:
            _fail(f"{where}: the reference has no baseline, selection or perturbation")
        out.update(baseline=None, selection=None, perturbation=None, dependencies=None, arm=None)
        if out["fingerprint"]["geometry_sha256"] != family["geometry_sha256"]:
            _fail(f"{where}.fingerprint.geometry_sha256 differs from the family")
        return out
    out["baseline"] = _text(row.get("baseline"), f"{where}.baseline")
    selection = row.get("selection")
    if not isinstance(selection, dict):
        _fail(f"{where}.selection must record how this variant was chosen")
    criteria = selection.get("criteria")
    if not isinstance(criteria, list) or not criteria or not all(isinstance(c, str) and c for c in criteria):
        _fail(f"{where}.selection.criteria must list the selection criteria")
    if selection.get("ink_used_in_selection") is not False:
        _fail(f"{where}: ink must not be used in variant selection (ink_used_in_selection must be false)")
    if selection.get("selected_before_ink_inference") is not True:
        _fail(f"{where}: the variant must be selected before ink inference")
    residual = selection.get("projection_residual")
    out["selection"] = {"criteria": list(criteria), "ink_used_in_selection": False,
                        "selected_before_ink_inference": True,
                        "projection_residual": None if residual is None
                        else _number(residual, f"{where}.selection.projection_residual", 0.0, open_low=False),
                        "evidence_sha256": _sha(selection.get("evidence_sha256"),
                                                f"{where}.selection.evidence_sha256")}
    out["dependencies"] = _dependencies(row.get("dependencies"), where)
    if kind == "calibration_perturbation":
        out["arm"] = "calibration"
        perturbation = row.get("perturbation")
        if not isinstance(perturbation, dict):
            _fail(f"{where}.perturbation must declare the perturbed parameter and value")
        parameter = _text(perturbation.get("parameter"), f"{where}.perturbation.parameter")
        value = _number(perturbation.get("value"), f"{where}.perturbation.value")
        bound = bounds.get(parameter)
        if bound is None:
            _fail(f"{where}: no preregistered plausible bound for parameter {parameter!r}")
        if value == 0 or abs(value) > bound["max_abs"]:
            _fail(f"{where}: perturbation {value} must be nonzero and within the preregistered "
                  f"plausible bound +/-{bound['max_abs']} for {parameter}")
        out["perturbation"] = {"parameter": parameter, "value": value}
    else:
        out["arm"] = "reconstruction"
        if row.get("perturbation") is not None:
            _fail(f"{where}: only calibration_perturbation variants may declare a perturbation")
        out["perturbation"] = None
        if out["fingerprint"]["geometry_sha256"] != family["geometry_sha256"]:
            _fail(f"{where}.fingerprint.geometry_sha256 differs from the family; a changed geometry "
                  f"is a declared calibration perturbation, not a reconstruction variant")
    return out


def validate_spec(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalise a frozen sensitivity spec (no file access)."""
    if document.get("schema") != SPEC_SCHEMA:
        _fail(f"spec.schema must be {SPEC_SCHEMA}")
    roi = document.get("roi")
    if not isinstance(roi, dict) or roi.get("coordinate_space") != COORDINATE_SPACE:
        _fail(f"spec.roi must be an object with coordinate_space {COORDINATE_SPACE!r}")
    start, stop = roi.get("start"), roi.get("stop")
    if not all(isinstance(b, list) and len(b) == 3 and all(type(v) in (int, float) for v in b)
               for b in (start, stop)) or not all(a < b for a, b in zip(start, stop)):
        _fail("spec.roi.start/stop must be [z, y, x] triplets with start < stop")
    grid = document.get("grid")
    shape = grid.get("shape") if isinstance(grid, dict) else None
    if not isinstance(shape, list) or len(shape) != 2 or any(type(v) is not int or v < 8 for v in shape):
        _fail("spec.grid.shape must be [rows, cols], each an integer >= 8")
    rules = document.get("rules")
    if not isinstance(rules, dict):
        _fail("spec.rules must be an object")
    tolerances = rules.get("tolerances")
    if not isinstance(tolerances, dict) or set(tolerances) != set(TOLERANCE_KEYS):
        _fail(f"spec.rules.tolerances must define exactly {list(TOLERANCE_KEYS)}")
    required = rules.get("required_channels")
    if not isinstance(required, list) or len(set(required)) != len(required) \
            or not set(required) <= set(OPTIONAL_CHANNELS):
        _fail(f"spec.rules.required_channels must be a list drawn from {list(OPTIONAL_CHANNELS)}")
    normalized_rules = {
        "ink_threshold": _number(rules.get("ink_threshold"), "spec.rules.ink_threshold", 0.0, 1.0),
        "min_component_cells": _count(rules.get("min_component_cells"), "spec.rules.min_component_cells", 1),
        "match_iou": _number(rules.get("match_iou"), "spec.rules.match_iou", 0.0, 1.0),
        "negative_component_tolerance": _count(rules.get("negative_component_tolerance"),
                                               "spec.rules.negative_component_tolerance", 0),
        "min_reconstruction_variants": _count(rules.get("min_reconstruction_variants"),
                                              "spec.rules.min_reconstruction_variants", 1),
        "min_calibration_variants": _count(rules.get("min_calibration_variants"),
                                           "spec.rules.min_calibration_variants", 1),
        "require_calibration_arm": _bool(rules.get("require_calibration_arm"),
                                         "spec.rules.require_calibration_arm"),
        "required_channels": sorted(required),
        "tolerances": {k: _number(tolerances[k], f"spec.rules.tolerances.{k}", 0.0) for k in TOLERANCE_KEYS},
    }
    bounds_raw = document.get("calibration_bounds")
    if not isinstance(bounds_raw, dict):
        _fail("spec.calibration_bounds must be an object (it may be empty if no calibration arm runs)")
    bounds = {}
    for parameter, entry in bounds_raw.items():
        if not isinstance(entry, dict):
            _fail(f"spec.calibration_bounds.{parameter} must be an object")
        bounds[_text(parameter, "calibration parameter")] = {
            "max_abs": _number(entry.get("max_abs"), f"spec.calibration_bounds.{parameter}.max_abs", 0.0),
            "evidence": _text(entry.get("evidence"), f"spec.calibration_bounds.{parameter}.evidence")}
    family_raw = document.get("family")
    if not isinstance(family_raw, dict):
        _fail("spec.family must be an object")
    family = {k: _sha(family_raw.get(k), f"spec.family.{k}")
              for k in ("projections_sha256", "geometry_sha256", "preprocessing_sha256", "pipeline_sha256")}
    family["coordinate_convention"] = _text(family_raw.get("coordinate_convention"),
                                            "spec.family.coordinate_convention")
    raw = document.get("variants")
    if not isinstance(raw, list) or not raw:
        _fail("spec.variants must be a non-empty list")
    variants = [_variant(row, i, family, bounds) for i, row in enumerate(raw)]
    by_id = {v["id"]: v for v in variants}
    if len(by_id) != len(variants):
        _fail("duplicate variant id")
    references = [v for v in variants if v["role"] == "reference"]
    if len(references) != 1 or references[0]["outcome"] != "ok":
        _fail("exactly one reference (official) variant with outcome ok is required")
    reference = references[0]
    seen_declarations = set()
    for v in variants:
        if v["role"] == "reference":
            continue
        base = by_id.get(v["baseline"])
        if base is None or base["id"] == v["id"] or base["arm"] == "calibration":
            _fail(f"variant {v['id']}: baseline {v['baseline']!r} must be another non-calibration variant")
        if v["arm"] == "reconstruction" and base["id"] != reference["id"]:
            _fail(f"variant {v['id']}: reconstruction variants are compared with the official reference")
        if v["arm"] == "calibration":
            if v["algorithm"] != base["algorithm"] or v["software"] != base["software"]:
                _fail(f"variant {v['id']}: a calibration variant may differ from its baseline only by "
                      f"the declared perturbation (software and algorithm must match)")
            if v["fingerprint"]["geometry_sha256"] == base["fingerprint"]["geometry_sha256"]:
                _fail(f"variant {v['id']}: perturbed geometry hash equals its baseline's, so no "
                      f"perturbation was applied")
        declaration = json.dumps([v["kind"], v["algorithm"], v["perturbation"], v["baseline"]], sort_keys=True)
        if declaration in seen_declarations:
            _fail(f"variant {v['id']} duplicates another variant's declaration")
        seen_declarations.add(declaration)
    calibration = [v for v in variants if v["arm"] == "calibration"]
    if len({v["baseline"] for v in calibration}) > 1:
        _fail("all calibration variants must share one baseline")
    if normalized_rules["require_calibration_arm"] and not calibration:
        _fail("spec requires a calibration arm but declares no calibration variants")
    audit = {v["id"]: v["dependencies"] for v in variants if v["dependencies"] is not None}
    mask_path = _text(document.get("masks"), "spec.masks")
    return {"roi": {"volume_id": _text(roi.get("volume_id"), "spec.roi.volume_id"),
                    "start": [float(x) for x in start], "stop": [float(x) for x in stop],
                    "coordinate_space": COORDINATE_SPACE},
            "grid": {"shape": list(shape)}, "masks": mask_path, "rules": normalized_rules,
            "calibration_bounds": bounds, "family": family, "variants": variants,
            "license_audit": {
                "note": "dependency licences are recorded per variant from the declared exact manifest; "
                        "a framework's top-level licence is not inferred for its optional backends",
                "variants": {k: {"manifest_sha256": d["manifest_sha256"], "status": d["status"],
                                 "copyleft_packages": d["copyleft_packages"],
                                 "unknown_packages": d["unknown_packages"]} for k, d in audit.items()},
                "overall": _overall_license([d["status"] for d in audit.values()])}}


# --------------------------------------------------------------------------- analysis


def _components(ink: np.ndarray, valid: np.ndarray, rules: Mapping[str, Any]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    labels, count = connected_components((ink >= rules["ink_threshold"]) & valid, structure=np.ones((3, 3)))
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    keep = np.flatnonzero(areas[1:] >= rules["min_component_cells"]) + 1
    remap = np.zeros(count + 1, dtype=np.int64)
    remap[keep] = np.arange(1, len(keep) + 1)
    labels = remap[labels]
    info = []
    for k in range(1, len(keep) + 1):
        rows, cols = np.nonzero(labels == k)
        info.append({"label": k, "id": f"c{k:03d}", "area_cells": int(rows.size),
                     "centroid_uv": [float(rows.mean()), float(cols.mean())]})
    return labels, info


def _iou(base: np.ndarray, n_base: int, other: np.ndarray, n_other: int) -> np.ndarray:
    if (n_base + 1) * (n_other + 1) > MAX_OVERLAP_CELLS:
        _fail("too many connected components to match; raise min_component_cells")
    overlap = np.bincount((base.astype(np.int64) * (n_other + 1) + other).ravel(),
                          minlength=(n_base + 1) * (n_other + 1)).reshape(n_base + 1, n_other + 1)
    inter = overlap[1:, 1:].astype(float)
    area_base = overlap[1:, :].sum(axis=1).astype(float)[:, None]
    area_other = overlap[:, 1:].sum(axis=0).astype(float)[None, :]
    union = area_base + area_other - inter
    return np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)


def _normals(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    normal = np.cross(np.gradient(xyz, axis=1), np.gradient(xyz, axis=0))
    length = np.linalg.norm(normal, axis=-1)
    good = length > 1e-9
    return np.where(good[..., None], normal / np.where(good, length, 1.0)[..., None], 0.0), good


def channel_change(metric: str, base: Mapping[str, np.ndarray], other: Mapping[str, np.ndarray]
                   ) -> tuple[np.ndarray, np.ndarray] | None:
    """Per-cell signed change of one metric, ``other`` minus ``base``, and its validity mask.

    Normal displacement is along the *base* surface normal; fibre orientation
    differences are taken modulo pi and reported in degrees.
    """
    needs = METRICS[metric][0]
    if any(k not in base or k not in other for k in needs):
        return None
    if metric == "normal_displacement":
        normal, good = _normals(base["surface_xyz"])
        return np.sum((other["surface_xyz"] - base["surface_xyz"]) * normal, axis=-1), good
    if metric == "neighbor_separation":
        def gap(arrays):
            return np.linalg.norm(arrays["neighbor_xyz"] - arrays["surface_xyz"], axis=-1)
        change = gap(other) - gap(base)
        return change, np.ones(change.shape, bool)
    if metric == "fiber_orientation":
        delta = (other["fiber_angle"] - base["fiber_angle"] + math.pi / 2) % math.pi - math.pi / 2
        return np.degrees(delta), np.ones(delta.shape, bool)
    change = other["ink_depth_offset"] - base["ink_depth_offset"]
    return change, np.ones(change.shape, bool)


def _p95(values: np.ndarray) -> float:
    return float(np.percentile(np.abs(values), 95))


def _variant_arrays(data: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {k: v for k, v in data.items() if k in OPTIONAL_CHANNELS}


def _assess_variant(variant: Mapping[str, Any], base_variant: Mapping[str, Any],
                    data: Mapping[str, Mapping[str, np.ndarray]], comps: Mapping[str, Any],
                    masks: Mapping[str, np.ndarray], rules: Mapping[str, Any]) -> dict[str, Any]:
    vid, bid = variant["id"], base_variant["id"]
    base_labels, base_info = comps[bid]
    var_labels, var_info = comps[vid]
    reasons = []
    if variant["fingerprint"]["volume_sha256"] == base_variant["fingerprint"]["volume_sha256"]:
        reasons.append("volume-identical-to-baseline")
    if np.array_equal(data[vid]["ink"], data[bid]["ink"]):
        reasons.append("ink-prediction-bitwise-identical-to-baseline")
    iou = _iou(base_labels, len(base_info), var_labels, len(var_info)) if base_info and var_info \
        else np.zeros((len(base_info), len(var_info)))
    base_arrays, var_arrays = _variant_arrays(data[bid]), _variant_arrays(data[vid])
    valid = masks["valid"]
    record: dict[str, Any] = {"variant_id": vid, "baseline": bid, "kind": variant["kind"],
                              "effective": not reasons, "not_varied_reasons": reasons,
                              "global_change": {}, "components": {}, "variant_only_components": []}
    changes = {}
    for metric in METRICS:
        result = channel_change(metric, base_arrays, var_arrays)
        if result is None:
            record["global_change"][metric] = {"status": "not_measured"}
            continue
        change, ok = result
        changes[metric] = (change, ok & valid)
        cells = change[ok & valid]
        record["global_change"][metric] = (
            {"status": "measured", "cells": int(cells.size), "signed_median": float(np.median(cells)),
             "p95_abs": _p95(cells)} if cells.size else {"status": "not_measured"})
    tolerances = rules["tolerances"]
    for k, info in enumerate(base_info):
        best = float(iou[k].max()) if iou.shape[1] else 0.0
        entry: dict[str, Any] = {"best_iou": best, "present": best >= rules["match_iou"],
                                 "matched_component": var_info[int(iou[k].argmax())]["id"]
                                 if iou.shape[1] and best >= rules["match_iou"] else None,
                                 "geometry": {}}
        footprint = base_labels == info["label"]
        for metric, (change, ok) in changes.items():
            cells = change[footprint & ok]
            if not cells.size:
                entry["geometry"][metric] = {"status": "not_measured"}
                continue
            p95 = _p95(cells)
            entry["geometry"][metric] = {"status": "measured", "p95_abs_change": p95,
                                         "exceeds_tolerance": p95 > tolerances[METRICS[metric][1]]}
        for metric in METRICS:
            entry["geometry"].setdefault(metric, {"status": "not_measured"})
        record["components"][info["id"]] = entry
    matched = set(np.flatnonzero(iou.max(axis=0) >= rules["match_iou"]).tolist()) if iou.size else set()
    negative = masks["negative"]
    for j, info in enumerate(var_info):
        if j not in matched:
            footprint = var_labels == info["label"]
            record["variant_only_components"].append(
                {"id": info["id"], "area_cells": info["area_cells"], "centroid_uv": info["centroid_uv"],
                 "touches_negative_region": bool((footprint & negative).any())})
    if negative.any():
        def touching(labels, info):
            return len({int(v) for v in np.unique(labels[negative]) if v > 0})
        record["negative_region"] = {
            "status": "measured", "baseline_components": touching(base_labels, base_info),
            "variant_components": touching(var_labels, var_info),
            "baseline_ink_fraction": float((data[bid]["ink"][negative] >= rules["ink_threshold"]).mean()),
            "variant_ink_fraction": float((data[vid]["ink"][negative] >= rules["ink_threshold"]).mean())}
        extra = record["negative_region"]["variant_components"] - record["negative_region"]["baseline_components"]
        record["negative_region"]["extra_components"] = extra
        record["negative_region"]["manufactures_negative_components"] = \
            extra > rules["negative_component_tolerance"]
    else:
        record["negative_region"] = {"status": "not_measured", "reason": "no known-negative cells"}
    return record


def _arm_status(base_info: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]],
                declared: int, minimum: int, rules: Mapping[str, Any],
                failed: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Status of each baseline component across the variants of one arm."""
    effective = [r for r in records if r["effective"]]
    out = {}
    for info in base_info:
        cid = info["id"]
        reasons, sensitive = [], False
        for record in effective:
            entry = record["components"][cid]
            if not entry["present"]:
                sensitive = True
                reasons.append(f"absent-in:{record['variant_id']}")
            for metric, geometry in entry["geometry"].items():
                if geometry.get("exceeds_tolerance"):
                    sensitive = True
                    reasons.append(f"{metric}-exceeds-tolerance-in:{record['variant_id']}")
        if sensitive:
            out[cid] = {"status": "sensitive", "reasons": reasons}
            continue
        gaps = []
        if failed:
            gaps.append("failed-variants:" + ",".join(failed))
        if len(records) < declared or len(effective) < len(records):
            gaps.extend(f"not-varied:{r['variant_id']}" for r in records if not r["effective"])
        if len(effective) < minimum:
            gaps.append(f"fewer-than-{minimum}-effective-variants")
        for record in effective:
            for channel in rules["required_channels"]:
                if record["components"][cid]["geometry"][CHANNEL_METRIC[channel]]["status"] != "measured":
                    gaps.append(f"required-channel-not-measured:{channel}:{record['variant_id']}")
        out[cid] = ({"status": "stable", "reasons": []} if not gaps
                    else {"status": "unverified", "reasons": sorted(set(gaps))})
    return out


def assess(spec: Mapping[str, Any], data: Mapping[str, Mapping[str, np.ndarray]],
           masks: Mapping[str, np.ndarray]) -> dict[str, Any]:
    """Core analysis over already-loaded arrays (the control and ``evaluate`` share it)."""
    rules = spec["rules"]
    variants = spec["variants"]
    by_id = {v["id"]: v for v in variants}
    reference = next(v for v in variants if v["role"] == "reference")
    ok_ids = [v["id"] for v in variants if v["outcome"] == "ok"]
    comps = {vid: _components(data[vid]["ink"], masks["valid"], rules) for vid in ok_ids}
    failed = [v["id"] for v in variants if v["outcome"] == "failed"]
    records: dict[str, dict[str, Any]] = {}
    for v in variants:
        if v["role"] != "reference" and v["outcome"] == "ok" and by_id[v["baseline"]]["outcome"] == "ok":
            records[v["id"]] = _assess_variant(v, by_id[v["baseline"]], data, comps, masks, rules)
    arms: dict[str, Any] = {}
    reference_info = comps[reference["id"]][1]
    chain: dict[str, dict[str, str | None]] = {}
    for arm, minimum_key in (("reconstruction", "min_reconstruction_variants"),
                             ("calibration", "min_calibration_variants")):
        members = [v for v in variants if v["arm"] == arm]
        if not members:
            arms[arm] = {"status": "not_run", "variants": []}
            continue
        base_id = members[0]["baseline"]
        base_ok = by_id[base_id]["outcome"] == "ok"
        arm_records = [records[v["id"]] for v in members if v["id"] in records]
        failed_here = [v["id"] for v in members if v["outcome"] == "failed"] + \
            ([] if base_ok else [base_id])
        statuses = _arm_status(comps[base_id][1], arm_records, len(members), rules[minimum_key],
                               rules, failed_here) if base_ok else {}
        arms[arm] = {"status": "run", "baseline": base_id, "declared_variants": [v["id"] for v in members],
                     "failed_variants": failed_here, "component_status": statuses,
                     "variant_records": arm_records}
        # map reference components onto this arm's baseline components
        if base_id == reference["id"]:
            chain[arm] = {info["id"]: info["id"] for info in reference_info}
        elif base_ok:
            base_labels, base_info = comps[base_id]
            ref_labels = comps[reference["id"]][0]
            iou = _iou(ref_labels, len(reference_info), base_labels, len(base_info)) \
                if reference_info and base_info else np.zeros((len(reference_info), len(base_info)))
            chain[arm] = {info["id"]: (base_info[int(iou[k].argmax())]["id"]
                                       if iou.shape[1] and iou[k].max() >= rules["match_iou"] else None)
                          for k, info in enumerate(reference_info)}
        else:
            chain[arm] = None  # the arm baseline failed: its components cannot be assessed
    results = []
    for info in reference_info:
        cid = info["id"]
        row: dict[str, Any] = {"component_id": cid, "area_cells": info["area_cells"],
                               "centroid_uv": info["centroid_uv"],
                               "in_negative_region": bool(
                                   (comps[reference["id"]][0] == info["label"])[masks["negative"]].any()),
                               "arms": {}}
        sensitive, unverified = False, False
        reasons: list[str] = []
        for arm in ("reconstruction", "calibration"):
            if arms[arm]["status"] == "not_run":  # a required-but-absent arm is refused in validate_spec
                row["arms"][arm] = {"status": "not_run"}
                continue
            if chain[arm] is None:
                row["arms"][arm] = {"status": "unverified", "reasons": ["arm-baseline-failed"]}
                unverified = True
                reasons.append(f"{arm}:arm-baseline-failed")
                continue
            target = chain[arm].get(cid)
            if target is None:
                row["arms"][arm] = {"status": "not_applicable",
                                    "reasons": ["absent-from-the-arm-baseline"]}
                continue
            status = arms[arm]["component_status"][target]
            row["arms"][arm] = {"baseline_component": target, **status}
            if status["status"] == "sensitive":
                sensitive = True
                reasons.extend(f"{arm}:{r}" for r in status["reasons"])
            elif status["status"] == "unverified":
                unverified = True
                reasons.extend(f"{arm}:{r}" for r in status["reasons"])
        row["evidence_class"] = ("reconstruction_sensitive" if sensitive
                                 else "unverified" if unverified else "reconstruction_stable")
        row["reasons"] = sorted(set(reasons))
        results.append(row)
    manufactured = [{"variant_id": r["variant_id"], **c} for r in records.values()
                    for c in r["variant_only_components"]]
    return {"reference": reference["id"], "arms": arms, "components": results,
            "variant_only_components": manufactured,
            "failed_variants": failed,
            "summary": {c: sum(r["evidence_class"] == c for r in results)
                        for c in ("reconstruction_stable", "reconstruction_sensitive", "unverified")}
            | {"reference_components": len(results), "variant_only": len(manufactured)}}


# --------------------------------------------------------------------------- controls


def _disc(shape, centre, radius):
    rows, cols = np.ogrid[:shape[0], :shape[1]]
    return (rows - centre[0]) ** 2 + (cols - centre[1]) ** 2 <= radius ** 2


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _control_spec(variant_rows: Sequence[Mapping[str, Any]], *, copies: bool = False) -> dict[str, Any]:
    family = {"projections_sha256": _sha_text("projections"), "geometry_sha256": _sha_text("geometry"),
              "preprocessing_sha256": _sha_text("preprocessing"), "pipeline_sha256": _sha_text("pipeline"),
              "coordinate_convention": "ccw-positive"}
    base = {"projections_sha256": family["projections_sha256"],
            "preprocessing_sha256": family["preprocessing_sha256"],
            "pipeline_sha256": family["pipeline_sha256"],
            "coordinate_convention": family["coordinate_convention"]}
    variants = []
    for row in copy.deepcopy(list(variant_rows)):  # never alias the shared control constants
        vid, kind = row["id"], row["kind"]
        geometry = family["geometry_sha256"] if kind != "calibration_perturbation" \
            else _sha_text(f"geometry-{vid}")
        volume = _sha_text("volume-official") if copies or kind == "official" else _sha_text(f"volume-{vid}")
        record = {"id": vid, "role": "reference" if kind == "official" else "variant", "kind": kind,
                  "outcome": "ok", "data": f"{vid}.npz",
                  "fingerprint": {**base, "geometry_sha256": geometry, "volume_sha256": volume},
                  "software": {"name": "synthetic", "version": "0"},
                  "algorithm": {"name": kind if kind != "calibration_perturbation" else "lsqr",
                                "parameters": dict(row.get("parameters", {}))}}
        if kind == "official":
            record.update(dependencies=None)
        else:
            record.update(baseline=row["baseline"], selection={
                "criteria": ["projection_residual", "physical_plausibility"],
                "ink_used_in_selection": False, "selected_before_ink_inference": True,
                "projection_residual": 0.01, "evidence_sha256": _sha_text(f"evidence-{vid}")},
                dependencies={"manifest_sha256": _sha_text("manifest"), "complete_transitive": True,
                              "packages": [{"name": "cil", "version": "26.0.0", "license": "Apache-2.0"},
                                           {"name": "astra-toolbox", "version": "2.x", "license": "GPL-3.0-only"}]})
            if kind == "calibration_perturbation":
                record["perturbation"] = row["perturbation"]
                baseline = next(r for r in variants if r["id"] == row["baseline"])
                record["algorithm"] = copy.deepcopy(baseline["algorithm"])
                record["software"] = copy.deepcopy(baseline["software"])
        variants.append(record)
    return {"schema": SPEC_SCHEMA,
            "roi": {"volume_id": "synthetic", "start": [0, 0, 0], "stop": [8, 80, 80],
                    "coordinate_space": COORDINATE_SPACE},
            "grid": {"shape": [80, 80]}, "masks": "masks.npz",
            "rules": {"ink_threshold": 0.5, "min_component_cells": 12, "match_iou": 0.5,
                      "negative_component_tolerance": 0, "min_reconstruction_variants": 3,
                      "min_calibration_variants": 2, "require_calibration_arm": True,
                      "required_channels": list(OPTIONAL_CHANNELS),
                      "tolerances": {"normal_displacement_voxels": 1.0, "neighbor_separation_voxels": 1.0,
                                     "fiber_angle_degrees": 10.0, "ink_depth_offset_voxels": 1.0}},
            "calibration_bounds": {"center_of_rotation_pixels": {"max_abs": 1.0, "evidence": "synthetic bound"}},
            "family": family, "variants": variants}


CONTROL_ROWS = (
    {"id": "official", "kind": "official"},
    {"id": "lsqr", "kind": "lsqr", "baseline": "official", "parameters": {"iterations": 20}},
    {"id": "tik_weak", "kind": "lsqr_tikhonov", "baseline": "official",
     "parameters": {"regularisation_strength": 0.01}},
    {"id": "tik_strong", "kind": "lsqr_tikhonov", "baseline": "official",
     "parameters": {"regularisation_strength": 1.0}},
    {"id": "cor_plus", "kind": "calibration_perturbation", "baseline": "lsqr",
     "perturbation": {"parameter": "center_of_rotation_pixels", "value": 0.5}},
    {"id": "cor_minus", "kind": "calibration_perturbation", "baseline": "lsqr",
     "perturbation": {"parameter": "center_of_rotation_pixels", "value": -0.5}},
)
# component -> (centre, radius); the planted outcome of each is documented in `positive_control`
CONTROL_COMPONENTS = {"G": ((15, 15), 6), "H": ((65, 65), 6), "A": ((15, 45), 6), "B": ((40, 15), 6),
                      "C": ((40, 45), 6), "E": ((15, 70), 5)}


def _control_arrays(seed: int, *, plant: bool) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    shape = (80, 80)

    def ink(parts, extra=()):
        field = np.full(shape, 0.05)
        for name in parts:
            field[_disc(shape, *CONTROL_COMPONENTS[name])] = 0.9
        for disc in extra:
            field[_disc(shape, *disc)] = 0.9
        return np.clip(field + rng.uniform(-0.02, 0.02, shape), 0.0, 1.0)

    rows, cols = np.mgrid[:80, :80].astype(float)
    surface = np.stack([np.full(shape, 100.0), rows, cols], axis=-1)

    def channels(displace=None):
        xyz = surface.copy()
        if displace is not None:
            xyz[_disc(shape, *CONTROL_COMPONENTS[displace]), 0] += 2.0
        return {"surface_xyz": xyz, "neighbor_xyz": xyz + np.array([8.0, 0.0, 0.0]),
                "fiber_angle": np.full(shape, 0.3) + rng.uniform(-0.01, 0.01, shape),
                "ink_depth_offset": np.full(shape, 1.0) + rng.uniform(-0.05, 0.05, shape)}

    everything = tuple(CONTROL_COMPONENTS)
    plan = {"official": (everything, (), None),
            "lsqr": (tuple(c for c in everything if c != "C") if plant else everything,
                     ((40, 57), 6) if plant else (), None),
            "tik_weak": (everything, (), "E" if plant else None),
            "tik_strong": (tuple(c for c in everything if c != "B") if plant else everything,
                           ((68, 20), 6) if plant else (), None),
            "cor_plus": (tuple(c for c in everything if c not in ("C", "A")) if plant
                         else everything, ((40, 57), 6) if plant else (), None),
            "cor_minus": (tuple(c for c in everything if c != "C") if plant else everything,
                          ((40, 57), 6) if plant else (), None)}
    data = {}
    for vid, (parts, extra, displaced) in plan.items():
        extras = (extra,) if extra else ()
        data[vid] = {"ink": ink(parts, extras), **channels(displaced)}
    negative = np.zeros(shape, bool)
    negative[60:78, 5:40] = True
    return data, {"valid": np.ones(shape, bool), "negative": negative}


def positive_control() -> dict[str, Any]:
    """Planted outcomes must be recovered, a null must stay stable, a no-op must not pass.

    Planted: ``G`` and ``H`` survive every variant; ``B`` vanishes under strong
    regularisation; ``C`` moves under LSQR (and so reappears as a variant-only
    component); ``E`` keeps its ink but its surface shifts 2 voxels under weak
    regularisation; ``A`` vanishes under a +0.5 px centre-of-rotation change; strong
    regularisation also manufactures a component inside the known-negative region.
    """
    spec = validate_spec(_control_spec(CONTROL_ROWS))
    data, masks = _control_arrays(CONTROL_SEED, plant=True)
    result = assess(spec, data, masks)
    classes = {}
    for component in result["components"]:
        centre = component["centroid_uv"]
        name = min(CONTROL_COMPONENTS, key=lambda n: (CONTROL_COMPONENTS[n][0][0] - centre[0]) ** 2
                   + (CONTROL_COMPONENTS[n][0][1] - centre[1]) ** 2)
        classes[name] = component["evidence_class"]
    expected = {"G": "reconstruction_stable", "H": "reconstruction_stable",
                "A": "reconstruction_sensitive", "B": "reconstruction_sensitive",
                "C": "reconstruction_sensitive", "E": "reconstruction_sensitive"}
    tik_strong = next(r for r in result["arms"]["reconstruction"]["variant_records"]
                      if r["variant_id"] == "tik_strong")
    planted_ok = classes == expected
    manufactured_ok = any(v["variant_id"] == "tik_strong" and v["touches_negative_region"]
                          for v in result["variant_only_components"]) \
        and tik_strong["negative_region"]["manufactures_negative_components"] is True
    null_data, null_masks = _control_arrays(CONTROL_SEED + 1, plant=False)
    null = assess(spec, null_data, null_masks)
    null_ok = null["summary"]["reconstruction_stable"] == len(CONTROL_COMPONENTS) \
        and null["summary"]["variant_only"] == 0
    noop_spec = validate_spec(_control_spec(CONTROL_ROWS, copies=True))
    noop_data, noop_masks = _control_arrays(CONTROL_SEED + 2, plant=False)
    for vid in noop_data:
        noop_data[vid] = {k: v.copy() for k, v in noop_data["official"].items()}
    noop = assess(noop_spec, noop_data, noop_masks)
    vacuity_ok = noop["summary"]["reconstruction_stable"] == 0 and noop["summary"]["unverified"] > 0
    return {"planted_classes_recovered": bool(planted_ok), "classes": classes,
            "manufactured_negative_detected": bool(manufactured_ok),
            "null_all_stable": bool(null_ok), "no_op_variants_not_passed": bool(vacuity_ok),
            "fired": bool(planted_ok and manufactured_ok and null_ok and vacuity_ok)}


def self_test() -> dict[str, Any]:
    control = positive_control()
    checks = {
        "planted_outcomes_recovered": control["planted_classes_recovered"],
        "manufactured_negative_component_detected": control["manufactured_negative_detected"],
        "null_family_is_stable": control["null_all_stable"],
        "no_op_variants_are_not_stable": control["no_op_variants_not_passed"],
        "copyleft_backend_flagged": _copyleft_flagged(),
        "ink_selected_variant_refused": _ink_selection_refused(),
        "implausible_perturbation_refused": _implausible_perturbation_refused(),
    }
    return {"schema": "scroliq-reconstruction-sensitivity-self-test-v1", "passed": all(checks.values()),
            "checks": checks, "control": control}


def _copyleft_flagged() -> bool:
    audit = validate_spec(_control_spec(CONTROL_ROWS))["license_audit"]
    return audit["overall"] == "copyleft_present" and all(
        any("astra-toolbox" in p for p in v["copyleft_packages"]) for v in audit["variants"].values())


def _refused(mutator) -> bool:
    document = _control_spec(CONTROL_ROWS)
    mutator(document)
    try:
        validate_spec(document)
    except ReconstructionSensitivityError:
        return True
    return False


def _ink_selection_refused() -> bool:
    return _refused(lambda d: d["variants"][1]["selection"].update(ink_used_in_selection=True))


def _implausible_perturbation_refused() -> bool:
    return _refused(lambda d: d["variants"][4]["perturbation"].update(value=5.0))


# --------------------------------------------------------------------------- IO / evaluate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_under(root: Path, relative: str, field: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        _fail(f"{field} must be a relative path inside the spec directory")
    return path


def _load_npz(path: Path, allowed: Sequence[str], required: Sequence[str]) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        arrays = {k: np.asarray(archive[k]) for k in archive.files}
    unknown = sorted(set(arrays) - set(allowed))
    missing = sorted(set(required) - set(arrays))
    if unknown or missing:
        _fail(f"{path.name}: unknown arrays {unknown}, missing arrays {missing}")
    return arrays


def _load_variant(path: Path, shape: Sequence[int]) -> dict[str, np.ndarray]:
    arrays = _load_npz(path, ("ink", *OPTIONAL_CHANNELS), ("ink",))
    expected = {"ink": tuple(shape), "surface_xyz": (*shape, 3), "neighbor_xyz": (*shape, 3),
                "fiber_angle": tuple(shape), "ink_depth_offset": tuple(shape)}
    for key, value in arrays.items():
        if value.shape != expected[key] or not np.issubdtype(value.dtype, np.floating):
            _fail(f"{path.name}:{key} must be a float array of shape {expected[key]}")
        if not np.isfinite(value).all():
            _fail(f"{path.name}:{key} contains non-finite values")
    if arrays["ink"].min() < 0 or arrays["ink"].max() > 1:
        _fail(f"{path.name}:ink must be probabilities in [0, 1]")
    return arrays


def evaluate(spec_path: Path) -> dict[str, Any]:
    spec_path = Path(spec_path)
    root = spec_path.parent
    spec = validate_spec(json.loads(spec_path.read_text(encoding="utf-8")))
    shape = spec["grid"]["shape"]
    files = {"spec": _sha256_file(spec_path)}
    mask_path = _resolve_under(root, spec["masks"], "spec.masks")
    raw_masks = _load_npz(mask_path, ("valid", "negative"), ("valid", "negative"))
    masks = {}
    for key, value in raw_masks.items():
        if value.dtype != bool or value.shape != tuple(shape):
            _fail(f"masks:{key} must be a boolean array of shape {tuple(shape)}")
        masks[key] = value
    if not masks["valid"].any() or (masks["negative"] & ~masks["valid"]).any():
        _fail("masks: valid must be non-empty and contain every negative cell")
    files["masks"] = _sha256_file(mask_path)
    data = {}
    for v in spec["variants"]:
        if v["outcome"] == "ok":
            path = _resolve_under(root, v["data"], f"variant {v['id']} data")
            data[v["id"]] = _load_variant(path, shape)
            files[v["id"]] = _sha256_file(path)
    control = positive_control()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "promotional": False,
        "claim": "reconstruction and calibration sensitivity of ink and geometry claims only; "
                 "stable is not prize-grade ink, readable text or an ink verdict",
        "roi": spec["roi"], "grid": spec["grid"], "rules": spec["rules"], "family": spec["family"],
        "calibration_bounds": spec["calibration_bounds"], "sha256": files,
        "license_audit": spec["license_audit"], "positive_control": control,
        "variants": [{"id": v["id"], "role": v["role"], "kind": v["kind"], "arm": v["arm"],
                      "outcome": v["outcome"], "software": v["software"], "algorithm": v["algorithm"],
                      "baseline": v["baseline"], "perturbation": v["perturbation"],
                      "selection": v["selection"], "fingerprint": v["fingerprint"],
                      "failure_reason": v.get("failure_reason")} for v in spec["variants"]],
        "negative_region_cells": int(masks["negative"].sum()), "valid_cells": int(masks["valid"].sum()),
    }
    if not control["fired"]:
        report.update(status="unverified",
                      reason="built-in planted/null/no-op control did not fire; no verdict is issued")
        return report
    report.update(status="measured", **assess(spec, data, masks))
    return report


def _write_create_only(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scroliq-reconstruction-sensitivity", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="assess frozen per-variant outputs against a frozen spec")
    ev.add_argument("--spec", type=Path, required=True)
    ev.add_argument("--out", type=Path, required=True, help="create-only JSON report")
    sub.add_parser("self-test", help="built-in planted/null/no-op controls; exits 1 if any fails")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            result = self_test()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["passed"] else 1
        report = evaluate(args.spec)
        _write_create_only(args.out, report)
        summary = report.get("summary")
        print(f"reconstruction sensitivity {report['status']}"
              + ("" if summary is None else
                 f": {summary['reconstruction_stable']} stable, {summary['reconstruction_sensitive']} sensitive, "
                 f"{summary['unverified']} unverified of {summary['reference_components']} reference "
                 f"components; {summary['variant_only']} variant-only"))
        return 0
    except (ReconstructionSensitivityError, OSError, ValueError) as exc:
        parser.exit(2, f"reconstruction sensitivity refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
