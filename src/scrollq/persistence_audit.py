"""Threshold-persistence audit of frozen ink predictions (experimental).

Question: does the *shape of a detector's own confidence filtration* tell a
verified-ink component from a false positive, beyond what peak probability,
mean probability, area and ordinary morphology already say, on domains that were
held out whole?

Everything here is a falsification harness. It generates no ink, reads no text,
compares nothing to a character template and never chooses a threshold: the
nominal threshold of every region is declared in the manifest before anything
is measured. The frozen filtration lives in :mod:`scrollq.persistence`; this
module binds a manifest to it (``measure``), applies the frozen leave-one-domain
-out decision rule (``evaluate``) and runs the built-in positive/negative
controls (``controls``).

The verdict is four-valued and fail-closed. ``PERSISTENCE_ADDS_SIGNAL`` needs
every gate; a design or run that cannot support a verdict is ``INVALID_DESIGN``
or ``INCONCLUSIVE``; a spec that is not the preregistered one can only be
``EXPLORATORY``. None of them says a mark is ink, that text is legible, or that
a scan is readable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import ndimage

from . import persistence as ps
from .ink_validation import (
    SHA256_RE,
    _binarize_labels,
    _binarize_mask,
    _load_2d,
    _normalize_prediction,
    _roc_auc,
    _sha256_file,
)

TOOL = "scroliq-persistence"
SCHEMA_VERSION = 1
PROTOCOL = "threshold-persistence-v1"
CLASSIFICATION = "EXPERIMENT FURTHER"

ADDS_SIGNAL = "PERSISTENCE_ADDS_SIGNAL"
NO_ADDED_SIGNAL = "NO_ADDED_SIGNAL"
INCONCLUSIVE = "INCONCLUSIVE"
INVALID_DESIGN = "INVALID_DESIGN"
EXPLORATORY = "EXPLORATORY"
VERDICTS = (ADDS_SIGNAL, NO_ADDED_SIGNAL, INCONCLUSIVE, INVALID_DESIGN, EXPLORATORY)

EXIT_ADDS_SIGNAL = 0
EXIT_INCONCLUSIVE = 1
EXIT_ERROR = 2
EXIT_NO_ADDED_SIGNAL = 3

REGION_KINDS = (
    "verified_ink",
    "blank_papyrus",
    "crack",
    "fiber",
    "fold",
    "known_false_positive",
    "injected_perturbation",
)
IN_REGION_NEGATIVE = "in_region_false_positive"

BASELINE_FULL = ("peak_prob", "mean_prob", "log_area", "peak_margin_log", "elongation", "bbox_fill")
BASELINE_RANK = ("log_area", "peak_margin_log", "elongation", "bbox_fill")
PERSISTENCE_FEATURES = ps.FEATURE_NAMES

SPEC: dict[str, Any] = {
    "protocol": PROTOCOL,
    "freeze": {"date": "2026-10-05", "real_prediction_maps_read": 0},
    "filtration": {
        "direction": "superlevel",
        "foreground_connectivity": 8,
        "background_connectivity": 4,
        "parameter": "mid-rank kept fraction",
        "masked_pixels": "outside",
    },
    "sweep": {
        "min_component_pixels": 12,
        "max_components": 400,
        "significant_persistence": 0.0005,
        "window_log10": 0.5,
        "steps_per_side": 4,
        "skeleton": "zhang-suen-v1",
    },
    "region": {
        "min_valid_pixels": 4096,
        "max_pixels": 1048576,
        "invariance_remaps": ["cube", "expm1_3x"],
    },
    "labeling": {"ink_overlap_min": 0.5, "clear_margin_px": 3},
    "features": {
        "baseline_full": list(BASELINE_FULL),
        "baseline_rank": list(BASELINE_RANK),
        "persistence": list(PERSISTENCE_FEATURES),
        "baseline_expansion": "squares+pairwise",
    },
    "model": {"kind": "ridge-logistic", "l2": 1.0, "max_iter": 50, "tol": 1e-8},
    "decision": {
        "recall_target": 0.9,
        "min_domains": 3,
        "min_positives_per_domain": 20,
        "min_negatives_per_domain": 20,
        "within_region_min_positives_per_domain": 10,
        "within_region_min_negatives_per_domain": 10,
        "min_mean_gain": 0.05,
        "min_positive_domain_fraction": 0.66,
        "bootstrap_samples": 2000,
        "bootstrap_seed": 20261005,
        "permutations": 200,
        "permutation_seed": 20261006,
        "alpha": 0.05,
    },
}


def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# The preregistered spec, pinned as a literal so that editing SPEC cannot silently stay
# "preregistered" (tests assert this equals canonical_sha256(SPEC) and the committed
# artifacts/2026-10-05-threshold-persistence-prereg/spec.json). It was frozen before any
# real prediction map was read; any other spec can only yield an EXPLORATORY verdict.
FROZEN_SPEC_SHA256 = "31e22a9153463dd514dbffecfaa458a990ea331a7717a49d66326ef1e3699b26"

REMAPS = {
    "cube": lambda v: v**3,
    "expm1_3x": lambda v: np.expm1(3.0 * v),
}


class AuditError(ValueError):
    """Invalid manifest, region, spec or features document."""


def sweep_config(spec: Mapping[str, Any]) -> ps.SweepConfig:
    sweep = spec["sweep"]
    return ps.SweepConfig(
        min_component_pixels=int(sweep["min_component_pixels"]),
        max_components=int(sweep["max_components"]),
        significant_persistence=float(sweep["significant_persistence"]),
        window_log10=float(sweep["window_log10"]),
        steps_per_side=int(sweep["steps_per_side"]),
    )


# ----------------------------------------------------------------- measurement


def invariance_check(
    values: np.ndarray,
    valid: np.ndarray,
    threshold: float,
    lv: ps.Levels,
    u_nom: int | None,
    remaps: Sequence[str],
) -> dict[str, Any]:
    """Confirm the rank pipeline's inputs are unchanged by monotone recalibration.

    Every persistence feature is a function of ``(lv.levels, lv.counts, u_nom)``;
    equal inputs under a remap therefore prove invariance for the whole feature
    vector. A remap that is not injective on this region's scores (float
    saturation or collapse) merges ranks, so it is reported as ``not_injective``
    and proves nothing either way.
    """
    results: list[dict[str, str]] = []
    arr = np.asarray(values, dtype=np.float64)
    for name in remaps:
        remapped = REMAPS[name](arr)
        tau = float(REMAPS[name](np.float64(threshold)))
        lv2 = ps.dense_levels(remapped, valid)
        if lv2.n_levels != lv.n_levels:
            results.append({"remap": name, "status": "not_injective"})
            continue
        u2 = ps.nominal_level(lv2, tau)
        same = bool(np.array_equal(lv2.levels, lv.levels) and u2 == u_nom)
        results.append({"remap": name, "status": "identical" if same else "DIFFERS"})
    statuses = {r["status"] for r in results}
    return {
        "remaps": results,
        "ok": "identical" in statuses and "DIFFERS" not in statuses,
    }


def measure_region(
    values: np.ndarray,
    valid: np.ndarray,
    labels: np.ndarray | None,
    threshold: float,
    kind: str,
    spec: Mapping[str, Any] = SPEC,
) -> dict[str, Any]:
    """Features and labels for the nominal components of one region (no I/O)."""
    if kind not in REGION_KINDS:
        raise AuditError(f"unknown region kind {kind!r}")
    arr = np.asarray(values)
    mask = np.asarray(valid, dtype=bool)
    region_spec = spec["region"]
    n_valid = int(mask.sum())
    if arr.size > int(region_spec["max_pixels"]):
        raise AuditError(f"region has {arr.size} pixels > max_pixels={region_spec['max_pixels']}")
    if n_valid < int(region_spec["min_valid_pixels"]):
        raise AuditError(f"region has {n_valid} valid pixels < min_valid_pixels")
    if not 0.0 < float(threshold) < 1.0:
        raise AuditError("nominal_threshold must lie strictly inside (0, 1)")
    ink = None
    if labels is not None:
        ink = (np.asarray(labels) > 0) & mask
    if kind == "verified_ink":
        if ink is None:
            raise AuditError("verified_ink regions need labels")
    elif ink is not None and ink.any():
        raise AuditError(f"{kind} regions must not contain ink labels")

    cfg = sweep_config(spec)
    lv = ps.dense_levels(arr, mask)
    u_nom = ps.nominal_level(lv, threshold)
    invariance = invariance_check(
        arr, mask, threshold, lv, u_nom, region_spec["invariance_remaps"]
    )
    summary: dict[str, Any] = {
        "n_valid": n_valid,
        "n_levels": lv.n_levels,
        "nominal_threshold": float(threshold),
        "nominal_level": u_nom,
        "kept_fraction_nominal": None if u_nom is None else lv.kept_fraction_at(u_nom),
        "invariance": invariance,
        "n_components_total": 0,
        "n_dropped_small": 0,
        "n_ambiguous": 0,
        "n_positive": 0,
        "n_negative": 0,
    }
    if u_nom is None:
        return {"summary": summary, "components": [], "labels": None, "persistence_margin": None}

    diagram = ps.h0_diagram(lv.levels)
    holes = ps.h1_holes(lv.levels)
    analysis = ps.analyze_components(lv, u_nom, cfg, diagram, holes)
    comps = analysis["components"]
    lab = analysis["labels"]
    summary["n_components_total"] = analysis["n_components_total"]
    summary["n_dropped_small"] = analysis["n_dropped_small"]
    summary["n_h0_branches"] = int(diagram.peak_idx.size)
    summary["n_h1_holes"] = int(holes.lo.size)

    n_c = len(comps)
    flat_values = np.asarray(arr, dtype=np.float64).ravel()
    flat_lab = lab.ravel()
    if n_c:
        sizes = np.bincount(flat_lab, minlength=n_c + 1)
        sums = np.bincount(flat_lab, weights=flat_values, minlength=n_c + 1)
    labeling = spec["labeling"]
    if ink is not None:
        near = ndimage.binary_dilation(
            ink, structure=ps.STRUCT8, iterations=int(labeling["clear_margin_px"])
        ) & mask
        ink_count = np.bincount(flat_lab[ink.ravel()], minlength=n_c + 1) if n_c else None
        near_count = np.bincount(flat_lab[near.ravel()], minlength=n_c + 1) if n_c else None

    rows: list[dict[str, Any]] = []
    for comp in comps:
        c = comp["component"]
        if kind == "verified_ink":
            overlap = ink_count[c] / sizes[c]
            if overlap >= float(labeling["ink_overlap_min"]):
                label, negative_kind = 1, None
            elif near_count[c] == 0:
                label, negative_kind = 0, IN_REGION_NEGATIVE
            else:
                summary["n_ambiguous"] += 1
                continue
        else:
            label, negative_kind = 0, kind
        x = dict(comp["geometry"])
        x.update(comp["features"])
        x["peak_prob"] = float(flat_values[comp["peak_idx"]])
        x["mean_prob"] = float(sums[c] / sizes[c])
        rows.append(
            {
                "component": c,
                "label": label,
                "negative_kind": negative_kind,
                "peak_yx": comp["peak_yx"],
                "area": comp["area"],
                "essential": comp["essential"],
                "merged_in_window": comp["merged_in_window"],
                "x": x,
            }
        )
    summary["n_positive"] = sum(1 for r in rows if r["label"] == 1)
    summary["n_negative"] = len(rows) - summary["n_positive"]

    margin = np.full(arr.shape, np.nan, dtype=np.float32)
    for comp in comps:
        margin[lab == comp["component"]] = comp["features"]["down_slack_log"]
    return {"summary": summary, "components": rows, "labels": lab, "persistence_margin": margin}


# -------------------------------------------------------------------- manifest

_CONTRACT = {
    "nominal_thresholds_declared_before_measurement": True,
    "topology_used_to_choose_threshold": False,
    "ocr_or_text_used_to_choose_regions_or_thresholds": False,
    "detector_trained_on_evaluation_domains": False,
}


def _resolve_under(root: Path, relative: Any, field: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise AuditError(f"{field} must be a non-empty relative path")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise AuditError(f"{field} escapes the manifest directory") from exc
    return candidate


def _sha_field(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AuditError(f"{field} must be lowercase 64-hex SHA-256")
    return value


def validate_manifest(document: Any) -> dict[str, Any]:
    """Validate the manifest's declared structure (files are checked in ``measure``)."""
    if not isinstance(document, dict):
        raise AuditError("manifest must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise AuditError(f"manifest schema_version must equal {SCHEMA_VERSION}")
    if document.get("protocol") != PROTOCOL:
        raise AuditError(f"manifest protocol must equal {PROTOCOL!r}")

    contract = document.get("selection_contract")
    if not isinstance(contract, dict):
        raise AuditError("selection_contract is required")
    for key, expected in _CONTRACT.items():
        if contract.get(key) is not expected:
            raise AuditError(f"selection_contract.{key} must be {str(expected).lower()}")

    detector = document.get("detector")
    if not isinstance(detector, dict):
        raise AuditError("detector must be an object")
    name = detector.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AuditError("detector.name must be non-empty")
    _sha_field(detector.get("checkpoint_sha256"), "detector.checkpoint_sha256")
    _sha_field(detector.get("inference_config_sha256"), "detector.inference_config_sha256")
    training = detector.get("training_domains")
    if (
        not isinstance(training, list)
        or any(not isinstance(d, str) or not d.strip() for d in training)
    ):
        raise AuditError("detector.training_domains must be a list of domain ids")

    regions = document.get("regions")
    if not isinstance(regions, list) or not regions:
        raise AuditError("regions must be a non-empty list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for i, region in enumerate(regions):
        label = f"regions[{i}]"
        if not isinstance(region, dict):
            raise AuditError(f"{label} must be an object")
        rid = region.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise AuditError(f"{label}.id must be non-empty")
        if rid in seen:
            raise AuditError(f"duplicate region id {rid!r}")
        seen.add(rid)
        domain = region.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise AuditError(f"{label}.domain must be non-empty")
        if domain in training:
            raise AuditError(
                f"region {rid!r}: domain {domain!r} is in detector.training_domains; "
                "the detector must not have seen an evaluation domain"
            )
        kind = region.get("kind")
        if kind not in REGION_KINDS:
            raise AuditError(f"{label}.kind must be one of {list(REGION_KINDS)}")
        threshold = region.get("nominal_threshold")
        if type(threshold) not in (int, float) or not 0.0 < float(threshold) < 1.0:
            raise AuditError(f"{label}.nominal_threshold must be a number in (0, 1)")
        entry = {
            "id": rid,
            "domain": domain,
            "kind": kind,
            "nominal_threshold": float(threshold),
            "prediction": region.get("prediction"),
            "prediction_sha256": _sha_field(region.get("prediction_sha256"), f"{label}.prediction_sha256"),
            "prediction_scale": region.get("prediction_scale", "auto"),
        }
        for field in ("labels", "valid_mask"):
            if region.get(field) is not None:
                entry[field] = region[field]
                entry[f"{field}_sha256"] = _sha_field(
                    region.get(f"{field}_sha256"), f"{label}.{field}_sha256"
                )
        if kind == "verified_ink" and "labels" not in entry:
            raise AuditError(f"{label}: verified_ink regions need labels")
        normalized.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "selection_contract": {k: contract[k] for k in _CONTRACT},
        "detector": {
            "name": name,
            "checkpoint_sha256": detector["checkpoint_sha256"],
            "inference_config_sha256": detector["inference_config_sha256"],
            "training_domains": sorted(training),
        },
        "regions": normalized,
    }


def _load_checked(root: Path, relative: Any, expected: str, field: str) -> tuple[np.ndarray, str]:
    path = _resolve_under(root, relative, field)
    try:
        observed = _sha256_file(path)
    except OSError as exc:
        raise AuditError(f"{field}: cannot read {relative}: {exc}") from exc
    if observed != expected:
        raise AuditError(f"{field}: SHA-256 mismatch for {relative}")
    try:
        return _load_2d(path), observed
    except (OSError, ValueError) as exc:
        raise AuditError(f"{field}: cannot decode {relative}: {exc}") from exc


def _write_new(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")


def measure_manifest(
    manifest_path: Path,
    spec: Mapping[str, Any] = SPEC,
    overlay_dir: Path | None = None,
) -> dict[str, Any]:
    """Measure every region of a manifest; failed regions are reported, never dropped."""
    manifest_path = Path(manifest_path)
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        manifest = validate_manifest(json.loads(raw))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read manifest: {exc}") from exc
    root = manifest_path.parent
    spec_sha = canonical_sha256(spec)
    region_docs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for region in manifest["regions"]:
        doc: dict[str, Any] = {
            "id": region["id"],
            "domain": region["domain"],
            "kind": region["kind"],
            "status": "ok",
        }
        try:
            pred_raw, pred_sha = _load_checked(
                root, region["prediction"], region["prediction_sha256"], f"region {region['id']} prediction"
            )
            values = _normalize_prediction(pred_raw, str(region["prediction_scale"]))
            inputs = {"prediction_sha256": pred_sha}
            labels = None
            if "labels" in region:
                lab_raw, lab_sha = _load_checked(
                    root, region["labels"], region["labels_sha256"], f"region {region['id']} labels"
                )
                labels = _binarize_labels(lab_raw)
                inputs["labels_sha256"] = lab_sha
            valid = np.ones(values.shape, dtype=bool)
            if "valid_mask" in region:
                mask_raw, mask_sha = _load_checked(
                    root, region["valid_mask"], region["valid_mask_sha256"], f"region {region['id']} valid_mask"
                )
                valid = _binarize_mask(mask_raw) > 0
                inputs["valid_mask_sha256"] = mask_sha
            if labels is not None and labels.shape != values.shape:
                raise AuditError("labels shape differs from prediction shape")
            if valid.shape != values.shape:
                raise AuditError("valid_mask shape differs from prediction shape")
            result = measure_region(
                values, valid, labels, region["nominal_threshold"], region["kind"], spec
            )
            doc["inputs"] = inputs
            doc.update(result["summary"])
            if not result["summary"]["invariance"]["ok"]:
                doc["status"] = "failed"
                doc["reason"] = "monotone-remap invariance check did not pass"
            else:
                for comp in result["components"]:
                    rows.append(
                        {
                            "region": region["id"],
                            "domain": region["domain"],
                            "kind": region["kind"],
                            **comp,
                        }
                    )
            if overlay_dir is not None and result["persistence_margin"] is not None:
                overlay_dir = Path(overlay_dir)
                overlay_dir.mkdir(parents=True, exist_ok=True)
                target = overlay_dir / f"{region['id']}.persistence-margin.npy"
                with target.open("xb") as handle:
                    np.save(handle, result["persistence_margin"])
                doc["overlay"] = target.name
        except (AuditError, ps.PersistenceError, ValueError, OSError) as exc:
            doc["status"] = "failed"
            doc["reason"] = str(exc)
        region_docs.append(doc)
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "classification": CLASSIFICATION,
        "spec": dict(spec),
        "spec_sha256": spec_sha,
        "preregistered": spec_sha == FROZEN_SPEC_SHA256,
        "manifest_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "selection_contract": manifest["selection_contract"],
        "detector": manifest["detector"],
        "regions": region_docs,
        "components": rows,
    }


# ------------------------------------------------------------------------ model


def fit_ridge_logistic(
    x: np.ndarray, y: np.ndarray, *, l2: float, max_iter: int, tol: float
) -> dict[str, Any]:
    """Deterministic L2-regularised logistic regression (Newton / IRLS)."""
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    z = (x - mean) / std
    n, d = z.shape
    design = np.hstack([np.ones((n, 1)), z])
    penalty = np.eye(d + 1) * l2
    penalty[0, 0] = 0.0
    w = np.zeros(d + 1)
    for _ in range(max_iter):
        eta = np.clip(design @ w, -30.0, 30.0)
        p = 1.0 / (1.0 + np.exp(-eta))
        grad = design.T @ (p - y) + penalty @ w
        curv = p * (1.0 - p) + 1e-9
        hess = design.T @ (design * curv[:, None]) + penalty
        step = np.linalg.solve(hess, grad)
        w = w - step
        if float(np.max(np.abs(step))) < tol:
            break
    return {"w": w, "mean": mean, "std": std}


def model_scores(model: Mapping[str, Any], x: np.ndarray) -> np.ndarray:
    z = (x - model["mean"]) / model["std"]
    return model["w"][0] + z @ model["w"][1:]


def fpr_at_recall(pos: np.ndarray, neg: np.ndarray, recall: float) -> float:
    """False-positive rate at the highest score cut that keeps recall >= target."""
    k = max(1, math.ceil(recall * pos.size))
    cut = np.sort(pos)[::-1][k - 1]
    return float(np.mean(neg >= cut))


def quadratic_expansion(x: np.ndarray) -> np.ndarray:
    """Columns, their squares and all pairwise products (a fixed, parameter-free map)."""
    d = x.shape[1]
    cols = [x, x**2]
    cols += [x[:, [i]] * x[:, [j]] for i in range(d) for j in range(i + 1, d)]
    return np.hstack(cols)


def _arm_matrices(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Design matrices of every arm.

    The baselines get a quadratic expansion as well as the linear form so that a
    persistence "gain" cannot come merely from re-encoding baseline information
    nonlinearly; the challengers stay linear in baseline plus persistence, which
    errs toward failing the hypothesis.
    """
    feats = spec["features"]
    if feats.get("baseline_expansion") != "squares+pairwise":
        raise AuditError("unsupported baseline_expansion")
    full, rank, pers = feats["baseline_full"], feats["baseline_rank"], feats["persistence"]

    def build(names: Sequence[str]) -> np.ndarray:
        return np.array([[float(r["x"][n]) for n in names] for r in rows], dtype=np.float64)

    b_full, b_rank = build(full), build(rank)
    return {
        "B_full": b_full,
        "B_rank": b_rank,
        "Bq_full": quadratic_expansion(b_full),
        "Bq_rank": quadratic_expansion(b_rank),
        "BP_full": build(list(full) + list(pers)),
        "BP_rank": build(list(rank) + list(pers)),
        "P_only": build(pers),
    }


def lodo_scores(
    matrices: Mapping[str, np.ndarray],
    y: np.ndarray,
    domains: np.ndarray,
    included: Sequence[str],
    spec: Mapping[str, Any],
    arms: Sequence[str],
) -> dict[str, np.ndarray]:
    """Out-of-fold scores: each included domain is scored by a model fit on the others."""
    model_spec = spec["model"]
    out = {arm: np.full(y.shape, np.nan) for arm in arms}
    for held in included:
        test = domains == held
        train = np.isin(domains, [d for d in included if d != held])
        if len(set(y[train].tolist())) < 2:
            raise AuditError(f"training domains for fold {held!r} lack one class")
        for arm in arms:
            model = fit_ridge_logistic(
                matrices[arm][train],
                y[train].astype(np.float64),
                l2=float(model_spec["l2"]),
                max_iter=int(model_spec["max_iter"]),
                tol=float(model_spec["tol"]),
            )
            out[arm][test] = model_scores(model, matrices[arm][test])
    return out


GATING_ARMS = ("B_full", "B_rank", "Bq_full", "Bq_rank", "BP_full", "BP_rank")


def domain_fprs(
    scores: Mapping[str, np.ndarray],
    y: np.ndarray,
    domains: np.ndarray,
    included: Sequence[str],
    recall: float,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {arm: {} for arm in scores}
    for d in included:
        sel = domains == d
        for arm, s in scores.items():
            out[arm][d] = fpr_at_recall(s[sel & (y == 1)], s[sel & (y == 0)], recall)
    return out


def domain_gains(fprs: Mapping[str, Mapping[str, float]], included: Sequence[str]) -> dict[str, float]:
    """Per-domain gain over the *better* baseline of each matched pair.

    For each pair (full, rank) the reference is the lower FPR of the linear and the
    quadratic baseline; the gain is the smaller of the two pairs' reference-minus-
    challenger FPR drops. Taking the best baseline and the worse pair is deliberately
    conservative: it can only make the hypothesis harder to confirm.
    """
    return {
        d: min(
            min(fprs["B_full"][d], fprs["Bq_full"][d]) - fprs["BP_full"][d],
            min(fprs["B_rank"][d], fprs["Bq_rank"][d]) - fprs["BP_rank"][d],
        )
        for d in included
    }


def bootstrap_domains(values: Sequence[float], *, seed: int, samples: int) -> tuple[float, float]:
    array = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, array.size, size=(samples, array.size))
    means = array[idx].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def permutation_test(
    matrices: Mapping[str, np.ndarray],
    y: np.ndarray,
    domains: np.ndarray,
    included: Sequence[str],
    spec: Mapping[str, Any],
    observed: float,
) -> dict[str, Any]:
    """Permute labels within each domain, rerun the whole leave-one-domain-out pipeline."""
    dec = spec["decision"]
    rng = np.random.default_rng(int(dec["permutation_seed"]))
    null: list[float] = []
    for _ in range(int(dec["permutations"])):
        permuted = y.copy()
        for d in included:
            idx = np.flatnonzero(domains == d)
            permuted[idx] = y[idx][rng.permutation(idx.size)]
        scores = lodo_scores(matrices, permuted, domains, included, spec, GATING_ARMS)
        fprs = domain_fprs(scores, permuted, domains, included, float(dec["recall_target"]))
        null.append(float(np.mean(list(domain_gains(fprs, included).values()))))
    exceed = sum(1 for v in null if v >= observed)
    return {
        "n": len(null),
        "p_value": (1 + exceed) / (1 + len(null)),
        "null_mean": float(np.mean(null)),
        "null_q95": float(np.quantile(null, 0.95)),
    }


SCOPES = ("all", "within_region")


def _scope_gates(analysis: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, bool]:
    dec = spec["decision"]
    n_dom = int(analysis["n_included_domains"])
    return {
        "mean_gain": analysis["mean_gain"] >= float(dec["min_mean_gain"]),
        "ci_lower_positive": analysis["ci95"][0] > 0.0,
        "positive_domain_fraction": (
            analysis["n_positive_domains"] / n_dom >= float(dec["min_positive_domain_fraction"])
        ),
        "permutation": analysis["permutation_p"] <= float(dec["alpha"]),
    }


def decide(stats: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    """Frozen decision rule (a pure function of the summary statistics).

    Every gate must pass on *both* scopes: ``all`` (every labelled component) and
    ``within_region`` (verified-ink regions only, where true ink and false positives
    share a region). The second scope exists because negatives from other regions
    can differ from ink regions in texture or noise alone; a gain that vanishes
    within a region is not evidence about ink.
    """
    invalid = list(stats.get("invalid_reasons", []))
    if invalid:
        return {"verdict": INVALID_DESIGN, "reasons": invalid, "gates": {}}
    incomplete = list(stats.get("incomplete_reasons", []))
    analyses = stats.get("analyses", {})
    for scope in SCOPES:
        analysis = analyses.get(scope)
        if analysis is None or not analysis.get("feasible"):
            reason = (analysis or {}).get("reason", "not analysed")
            incomplete.append(f"{scope}: {reason}")
    if incomplete:
        return {"verdict": INCONCLUSIVE, "reasons": incomplete, "gates": {}}
    gates = {scope: _scope_gates(analyses[scope], spec) for scope in SCOPES}
    failed = [
        f"gate not met: {scope}/{name}"
        for scope, scope_gates in gates.items()
        for name, ok in scope_gates.items()
        if not ok
    ]
    if not stats["preregistered"]:
        return {
            "verdict": EXPLORATORY,
            "reasons": ["spec is not the preregistered spec; no verdict can be drawn"] + failed,
            "gates": gates,
        }
    if failed:
        return {"verdict": NO_ADDED_SIGNAL, "reasons": failed, "gates": gates}
    return {"verdict": ADDS_SIGNAL, "reasons": [], "gates": gates}


def _scope_rows(rows: Sequence[Mapping[str, Any]], scope: str) -> list[Mapping[str, Any]]:
    if scope == "all":
        return list(rows)
    return [r for r in rows if r["kind"] == "verified_ink"]


def _domain_table(
    rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any], scope: str
) -> list[dict[str, Any]]:
    dec = spec["decision"]
    prefix = "within_region_" if scope == "within_region" else ""
    need_pos = int(dec[f"{prefix}min_positives_per_domain"])
    need_neg = int(dec[f"{prefix}min_negatives_per_domain"])
    table: dict[str, dict[str, int]] = {}
    for r in rows:
        entry = table.setdefault(r["domain"], {"n_positive": 0, "n_negative": 0})
        entry["n_positive" if r["label"] == 1 else "n_negative"] += 1
    out = []
    for d in sorted(table):
        e = table[d]
        reason = None
        if e["n_positive"] < need_pos:
            reason = f"{e['n_positive']} positives < {need_pos}"
        elif e["n_negative"] < need_neg:
            reason = f"{e['n_negative']} negatives < {need_neg}"
        out.append({"domain": d, **e, "included": reason is None, "excluded_reason": reason})
    return out


def _analyse_scope(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any], scope: str) -> dict[str, Any]:
    """Leave-one-domain-out analysis of one scope."""
    dec = spec["decision"]
    scoped = _scope_rows(rows, scope)
    table = _domain_table(scoped, spec, scope)
    included = [t["domain"] for t in table if t["included"]]
    out: dict[str, Any] = {
        "scope": scope,
        "domains": table,
        "n_components": len(scoped),
        "n_included_domains": len(included),
        "feasible": len(included) >= int(dec["min_domains"]),
    }
    if not out["feasible"]:
        out["reason"] = (
            f"{len(included)} usable held-out domain(s) < required {dec['min_domains']}"
            + (
                "; the cross-region confound cannot be tested"
                if scope == "within_region"
                else ""
            )
        )
        return out
    kept = [r for r in scoped if r["domain"] in set(included)]
    y = np.array([r["label"] for r in kept], dtype=np.int64)
    domains = np.array([r["domain"] for r in kept])
    matrices = _arm_matrices(kept, spec)
    arms = list(GATING_ARMS) + ["P_only"]
    scores = lodo_scores(matrices, y, domains, included, spec, arms)
    recall = float(dec["recall_target"])
    fprs = domain_fprs(scores, y, domains, included, recall)
    gains = domain_gains(fprs, included)
    values = [gains[d] for d in included]
    mean_gain = float(np.mean(values))
    ci = bootstrap_domains(values, seed=int(dec["bootstrap_seed"]), samples=int(dec["bootstrap_samples"]))
    perm = permutation_test(matrices, y, domains, included, spec, mean_gain)
    out.update(
        {
            "mean_gain": mean_gain,
            "ci95": list(ci),
            "n_positive_domains": sum(1 for v in values if v > 0.0),
            "permutation_p": perm["p_value"],
            "fpr_at_recall": {
                "recall_target": recall,
                "per_domain": fprs,
                "per_domain_gain": gains,
                "refuted_minimal_effect": bool(ci[1] < float(dec["min_mean_gain"])),
            },
            "permutation": perm,
            "negative_kinds": _negative_kind_table(kept, scores, y, domains, included, recall),
            "feature_auroc_by_domain": _feature_auroc(kept, domains, included, spec),
        }
    )
    return out


def evaluate_features(document: Mapping[str, Any], spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Apply the frozen leave-one-domain-out decision rule to a ``measure`` document."""
    spec = dict(spec if spec is not None else document.get("spec", SPEC))
    spec_sha = canonical_sha256(spec)
    rows = list(document.get("components", []))
    regions = list(document.get("regions", []))

    invalid: list[str] = []
    incomplete: list[str] = []
    if document.get("tool") != TOOL or document.get("protocol") != PROTOCOL:
        invalid.append("features document is not a threshold-persistence-v1 measurement")
    if document.get("spec_sha256") != spec_sha:
        invalid.append("features were measured under a different spec than the one evaluated")
    contract = document.get("selection_contract")
    if not isinstance(contract, dict) or any(contract.get(k) is not v for k, v in _CONTRACT.items()):
        invalid.append("selection contract is missing or not satisfied")
    failed_regions = [r["id"] for r in regions if r.get("status") != "ok"]
    if failed_regions:
        incomplete.append(
            f"{len(failed_regions)} region(s) failed measurement and cannot be dropped: "
            + ", ".join(sorted(failed_regions)[:10])
        )
    if not rows:
        incomplete.append("no labelled components")

    report: dict[str, Any] = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "classification": CLASSIFICATION,
        "spec_sha256": spec_sha,
        "frozen_spec_sha256": FROZEN_SPEC_SHA256,
        "preregistered": spec_sha == FROZEN_SPEC_SHA256,
        "features_manifest_sha256": document.get("manifest_sha256"),
        "n_regions": len(regions),
        "n_components": len(rows),
        "limitation": (
            "A positive verdict means these persistence features added held-out false-positive "
            "rejection beyond the stated baselines, across regions and within verified-ink "
            "regions, on the evaluated domains. It does not show that any mark is ink, that "
            "text is legible, or that a scan is readable, and it cannot reject false positives "
            "whose confidence filtration is as stable as ink's. The baselines are regularised "
            "logistic models (linear and quadratic); a stronger learner on the baseline features "
            "could absorb a gain that this comparison credits."
        ),
    }
    stats: dict[str, Any] = {
        "invalid_reasons": invalid,
        "incomplete_reasons": incomplete,
        "preregistered": report["preregistered"],
        "analyses": {},
    }
    if not invalid and not incomplete:
        stats["analyses"] = {scope: _analyse_scope(rows, spec, scope) for scope in SCOPES}
    report["analyses"] = stats["analyses"]
    outcome = decide(stats, spec)
    report["verdict"] = outcome["verdict"]
    report["reasons"] = outcome["reasons"]
    report["gates"] = outcome["gates"]
    return report


def _negative_kind_table(
    rows: Sequence[Mapping[str, Any]],
    scores: Mapping[str, np.ndarray],
    y: np.ndarray,
    domains: np.ndarray,
    included: Sequence[str],
    recall: float,
) -> dict[str, Any]:
    kinds = np.array([r["negative_kind"] or "" for r in rows])
    cuts: dict[str, dict[str, float]] = {arm: {} for arm in scores}
    for d in included:
        pos = domains == d
        for arm, s in scores.items():
            vals = s[pos & (y == 1)]
            cuts[arm][d] = float(np.sort(vals)[::-1][max(1, math.ceil(recall * vals.size)) - 1])
    table: dict[str, Any] = {}
    for kind in sorted({k for k in kinds.tolist() if k}):
        entry: dict[str, Any] = {"n": int(np.count_nonzero(kinds == kind)), "flagged": {}}
        for arm, s in scores.items():
            flagged = 0
            for d in included:
                sel = (domains == d) & (kinds == kind)
                flagged += int(np.count_nonzero(s[sel] >= cuts[arm][d]))
            entry["flagged"][arm] = flagged
        table[kind] = entry
    return table


def _feature_auroc(
    rows: Sequence[Mapping[str, Any]],
    domains: np.ndarray,
    included: Sequence[str],
    spec: Mapping[str, Any],
) -> dict[str, dict[str, float | None]]:
    y = np.array([r["label"] for r in rows])
    names = list(spec["features"]["persistence"])
    out: dict[str, dict[str, float | None]] = {}
    for name in names:
        x = np.array([float(r["x"][name]) for r in rows])
        out[name] = {d: _roc_auc(x[domains == d], y[domains == d]) for d in included}
    return out


# -------------------------------------------------------------------------- CLI


def _load_spec(path: str | None) -> dict[str, Any]:
    if path is None:
        return json.loads(json.dumps(SPEC))
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read spec: {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("protocol") != PROTOCOL:
        raise AuditError(f"spec must be a JSON object with protocol {PROTOCOL!r}")
    return loaded


def _cmd_measure(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {out}", file=sys.stderr)
        return EXIT_ERROR
    try:
        spec = _load_spec(args.spec)
        document = measure_manifest(
            Path(args.manifest), spec, Path(args.overlay_dir) if args.overlay_dir else None
        )
        _write_new(out, document)
    except (AuditError, OSError, FileExistsError) as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return EXIT_ERROR
    failed = [r["id"] for r in document["regions"] if r["status"] != "ok"]
    print(
        f"{TOOL}: measured {len(document['regions'])} region(s), "
        f"{len(document['components'])} labelled component(s), {len(failed)} failed; "
        f"preregistered={document['preregistered']}"
    )
    return EXIT_INCONCLUSIVE if failed else 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {out}", file=sys.stderr)
        return EXIT_ERROR
    try:
        document = json.loads(Path(args.features).read_text(encoding="utf-8"))
        spec = _load_spec(args.spec) if args.spec else None
        report = evaluate_features(document, spec)
        _write_new(out, report)
    except (AuditError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, FileExistsError) as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return EXIT_ERROR
    parts = []
    for scope, analysis in report["analyses"].items():
        if analysis.get("feasible"):
            lo, hi = analysis["ci95"]
            parts.append(
                f"{scope}: gain {analysis['mean_gain']:+.3f} FPR@recall "
                f"{analysis['fpr_at_recall']['recall_target']:.2f}, CI95 [{lo:+.3f}, {hi:+.3f}], "
                f"p={analysis['permutation_p']:.3f}"
            )
    print(f"{TOOL}: {report['verdict']}: " + ("; ".join(parts) if parts else "; ".join(report["reasons"])))
    return {
        ADDS_SIGNAL: EXIT_ADDS_SIGNAL,
        NO_ADDED_SIGNAL: EXIT_NO_ADDED_SIGNAL,
        INCONCLUSIVE: EXIT_INCONCLUSIVE,
        EXPLORATORY: EXIT_INCONCLUSIVE,
        INVALID_DESIGN: EXIT_ERROR,
    }[report["verdict"]]


def _cmd_controls(args: argparse.Namespace) -> int:
    from . import persistence_controls as pc

    out = Path(args.out)
    if out.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {out}", file=sys.stderr)
        return EXIT_ERROR
    try:
        report = pc.run_controls(seed_base=args.seed_base, n=args.n, quick=args.quick)
        _write_new(out, report)
    except (AuditError, ps.PersistenceError, OSError, FileExistsError) as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for gate in report["gates"]:
        print(f"  {gate['name']:42s} {'ok' if gate['pass'] else 'FAIL'}  {gate['detail']}")
    print(f"{TOOL}: controls gate: {report['gate_status'].upper()}")
    return 0 if report["gate_status"] == "pass" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Threshold-persistence audit of frozen ink predictions: does the topology of a "
            "detector's confidence filtration separate verified ink from false positives "
            "beyond peak/mean probability, area and morphology, on held-out domains? "
            "Experimental falsification harness; generates no ink and reads no text."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    measure = sub.add_parser("measure", help="measure every region of a frozen manifest")
    measure.add_argument("--manifest", required=True, help="region manifest (see docs/threshold-persistence.md)")
    measure.add_argument("--out", required=True, help="new features JSON path")
    measure.add_argument("--spec", default=None, help="spec JSON; omit for the preregistered spec")
    measure.add_argument("--overlay-dir", default=None,
                         help="write a per-region float32 .npy of each component's down-slack (create-only)")
    measure.set_defaults(func=_cmd_measure)

    evaluate = sub.add_parser("evaluate", help="apply the frozen leave-one-domain-out decision rule")
    evaluate.add_argument("--features", required=True, help="features JSON from `measure`")
    evaluate.add_argument("--out", required=True, help="new report JSON path")
    evaluate.add_argument("--spec", default=None, help="spec JSON; omit to use the one the features were measured with")
    evaluate.set_defaults(func=_cmd_evaluate)

    controls = sub.add_parser("controls", help="run the deterministic synthetic control suite")
    controls.add_argument("--out", required=True, help="new JSON report path")
    controls.add_argument("--seed-base", type=int, default=700_000)
    controls.add_argument("--n", type=int, default=24, help="seeds per decision-rule scenario")
    controls.add_argument("--quick", action="store_true", help="smaller engine oracles (for smoke tests)")
    controls.set_defaults(func=_cmd_controls)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
