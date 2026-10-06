"""Ensemble-independence gate: training ancestry and failure-ranking validity.

Two evidence layers, neither an ink or surface verdict:

* ``ancestry`` records each ensemble member's declared training inventory,
  initialization/ordering seeds and lineage, computes pairwise supervision
  overlap, detects whether the members form a cross-validation partition, and
  reports how many members can be counted as independent witnesses. Five
  agreeing models that share most of their supervision are not five witnesses.
* ``evaluate`` asks, on a frozen scroll-disjoint set, whether ensemble
  disagreement (mutual information) ranks real failures better than chance and
  better than ordinary confidence, for a cross-validation ensemble and a
  same-size independent ensemble, with a physical-block bootstrap. A built-in
  planted-signal and shuffled-null control must fire first, or the result is
  ``unverified``.

Ancestry is declared, not extracted from checkpoint bytes, and overlap is
computed on declared unit IDs, so differently named but geometrically
overlapping units are not detected; supply a geometric overlap audit upstream
(``scroliq-provenance``). Nothing here ranks readability, selects a model, or
makes a result promotional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.special import xlogy
from scipy.stats import rankdata

ANCESTRY_SCHEMA = "scroliq-ensemble-ancestry-v1"
SPEC_SCHEMA = "scroliq-ensemble-evaluation-spec-v1"
ANCESTRY_REPORT_SCHEMA = "scroliq-ensemble-ancestry-report-v1"
EVALUATION_REPORT_SCHEMA = "scroliq-ensemble-evaluation-report-v1"

PURPOSES = ("deep_ensemble_uncertainty", "independent_witnesses")
KINDS = ("cv_fold", "deep_ensemble", "independent_subsets", "other")
REGIMES = ("identical_full_set", "disjoint_subsets", "cv_partition", "partial_overlap")
KIND_REGIMES = {
    "cv_fold": {"cv_partition"},
    "deep_ensemble": {"identical_full_set"},
    "independent_subsets": {"disjoint_subsets"},
}
MAX_MEMBERS = 24
CONTROL_SEED = 20261006
CONTROL_REPLICATES = 300
CONTROL_NULL_TRIALS = 8
MAX_NULL_FALSE_DETECTION_RATE = 0.2
MI_NOISE_FLOOR = 1e-12
POOLED = "pooled"
PROOF_QUESTION = "does disagreement rank real failures, or merely reflect fold membership?"


class EnsembleIndependenceError(ValueError):
    """Raised when a manifest, spec or input violates the contract."""


def _fail(message: str) -> None:
    raise EnsembleIndependenceError(message)


# --------------------------------------------------------------------------- validation


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    return value.strip()


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail(f"{field} must be a non-empty list")
    result = [_text(v, field) for v in value]
    if len(result) != len(set(result)):
        _fail(f"{field} contains duplicates")
    return result


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        _fail(f"{field} must be lowercase 64-hex")
    return text


def _seed_or_none(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        _fail(f"{field} must be a nonnegative integer or null (unknown)")
    return value


def _number(value: Any, field: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) \
            or not low < float(value) < high:
        _fail(f"{field} must be a finite number in ({low}, {high})")
    return float(value)


def _member(row: Any, index: int) -> dict[str, Any]:
    where = f"members[{index}]"
    if not isinstance(row, dict):
        _fail(f"{where} must be an object")
    for key in ("init_seed", "data_order_seed", "parents", "config_sha256"):
        if key not in row:
            _fail(f"{where}.{key} must be declared explicitly (null means unknown)")
    parents = row["parents"]
    if parents is not None:
        if not isinstance(parents, list):
            _fail(f"{where}.parents must be a list of checkpoint hashes or null (unknown)")
        parents = [_sha(p, f"{where}.parents") for p in parents]
    config = row["config_sha256"]
    calibration = row.get("calibration_units")
    return {
        "member_id": _text(row.get("member_id"), f"{where}.member_id"),
        "checkpoint_sha256": _sha(row.get("checkpoint_sha256"), f"{where}.checkpoint_sha256"),
        "training_units": _ids(row.get("training_units"), f"{where}.training_units"),
        "training_scroll_ids": _ids(row.get("training_scroll_ids"), f"{where}.training_scroll_ids"),
        "init_seed": _seed_or_none(row["init_seed"], f"{where}.init_seed"),
        "data_order_seed": _seed_or_none(row["data_order_seed"], f"{where}.data_order_seed"),
        "parents": parents,
        "config_sha256": None if config is None else _sha(config, f"{where}.config_sha256"),
        "calibration_units": None if calibration is None
        else _ids(calibration, f"{where}.calibration_units"),
    }


def validate_ancestry(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("schema") != ANCESTRY_SCHEMA:
        _fail(f"manifest.schema must be {ANCESTRY_SCHEMA}")
    purpose = document.get("purpose")
    if purpose not in PURPOSES:
        _fail(f"manifest.purpose must be one of {list(PURPOSES)}")
    kind = document.get("declared_kind")
    if kind not in KINDS:
        _fail(f"manifest.declared_kind must be one of {list(KINDS)}")
    raw = document.get("members")
    if not isinstance(raw, list) or not raw:
        _fail("manifest.members must be a non-empty list")
    if len(raw) > MAX_MEMBERS:
        _fail(f"at most {MAX_MEMBERS} members are supported")
    members = [_member(row, i) for i, row in enumerate(raw)]
    if len({m["member_id"] for m in members}) != len(members):
        _fail("duplicate member_id")
    max_overlap = document.get("max_overlap", 0.0)
    if type(max_overlap) not in (int, float) or not math.isfinite(float(max_overlap)) \
            or not 0.0 <= float(max_overlap) < 1.0:
        _fail("manifest.max_overlap must be a finite number in [0, 1)")
    weights = document.get("unit_weights")
    if weights is not None:
        if not isinstance(weights, dict):
            _fail("manifest.unit_weights must be an object of unit_id -> positive weight")
        for key, value in weights.items():
            if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
                _fail(f"unit_weights[{key!r}] must be a positive finite number")
        missing = sorted({u for m in members for u in m["training_units"]} - set(weights))
        if missing:
            _fail(f"unit_weights does not cover training units: {missing[:3]}")
    return {
        "ensemble_id": _text(document.get("ensemble_id"), "manifest.ensemble_id"),
        "purpose": purpose,
        "declared_kind": kind,
        "max_overlap": float(max_overlap),
        "unit_weights": None if weights is None else {k: float(v) for k, v in weights.items()},
        "members": members,
    }


# --------------------------------------------------------------------------- ancestry


def _ancestors(members: Sequence[dict[str, Any]]) -> list[set[str]]:
    by_sha: dict[str, list[int]] = {}
    for i, m in enumerate(members):
        by_sha.setdefault(m["checkpoint_sha256"], []).append(i)
    memo: dict[int, set[str]] = {}

    def walk(i: int, stack: frozenset[int]) -> set[str]:
        if i in memo:
            return memo[i]
        if i in stack:
            _fail("checkpoint lineage contains a cycle")
        out: set[str] = set()
        for parent in members[i]["parents"] or ():
            out.add(parent)
            for j in by_sha.get(parent, ()):
                out |= walk(j, stack | {i})
        memo[i] = out
        return out

    return [walk(i, frozenset()) for i in range(len(members))]


def _regime(sets: Sequence[frozenset[str]]) -> str | None:
    if len(sets) < 2:
        return None
    if all(s == sets[0] for s in sets):
        return "identical_full_set"
    if all(not (a & b) for a, b in combinations(sets, 2)):
        return "disjoint_subsets"
    union = frozenset().union(*sets)
    held_out = [union - s for s in sets]
    if all(held_out) and all(not (a & b) for a, b in combinations(held_out, 2)):
        return "cv_partition"
    return "partial_overlap"


def _supervision(a: frozenset[str], b: frozenset[str], weight) -> dict[str, Any]:
    shared = sorted(a & b)
    w_a = sum(weight(u) for u in sorted(a))
    w_b = sum(weight(u) for u in sorted(b))
    w_i = sum(weight(u) for u in shared)
    return {"shared_units": len(shared),
            "overlap_coefficient": w_i / min(w_a, w_b),
            "jaccard": w_i / (w_a + w_b - w_i)}


def _axis(a: Any, b: Any) -> str:
    if a is None or b is None:
        return "unknown"
    return "shared" if a == b else "distinct"


def _combine(dependent: bool, unknown: bool) -> str:
    return "dependent" if dependent else ("unverified" if unknown else "independent")


def _max_clique(compatible: list[int]) -> int:
    best = 0

    def grow(size: int, candidates: int) -> None:
        nonlocal best
        best = max(best, size)
        while candidates:
            if size + candidates.bit_count() <= best:
                return
            low = candidates & -candidates
            i = low.bit_length() - 1
            candidates &= ~low
            grow(size + 1, candidates & compatible[i])

    grow(0, (1 << len(compatible)) - 1)
    return best


def _witness_counts(n: int, pairs: Sequence[dict[str, Any]], index: Mapping[str, int]) -> dict[str, int]:
    def count(accept: set[str]) -> int:
        compatible = [0] * n
        for pair in pairs:
            if pair["witness_independence"] in accept:
                i, j = index[pair["a"]], index[pair["b"]]
                compatible[i] |= 1 << j
                compatible[j] |= 1 << i
        return _max_clique(compatible)

    return {"certified": count({"independent"}), "upper_bound": count({"independent", "unverified"})}


def audit_ancestry(document: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the ancestry report for one ensemble manifest."""
    spec = validate_ancestry(document)
    members = spec["members"]
    n = len(members)
    index = {m["member_id"]: i for i, m in enumerate(members)}
    weights = spec["unit_weights"]
    weight = (lambda u: weights[u]) if weights is not None else (lambda u: 1.0)
    sets = [frozenset(m["training_units"]) for m in members]
    ancestors = _ancestors(members)
    regime = _regime(sets)

    pairs = []
    for i, j in combinations(range(n), 2):
        a, b = members[i], members[j]
        supervision = _supervision(sets[i], sets[j], weight)
        lineage_a = ancestors[i] | {a["checkpoint_sha256"]}
        lineage_b = ancestors[j] | {b["checkpoint_sha256"]}
        if lineage_a & lineage_b:
            lineage = "shared"
        elif a["parents"] is None or b["parents"] is None:
            lineage = "unknown"
        else:
            lineage = "distinct"
        identical = a["checkpoint_sha256"] == b["checkpoint_sha256"]
        # Equal seeds do not imply equal initialization across different architectures.
        if a["config_sha256"] and b["config_sha256"] and a["config_sha256"] != b["config_sha256"]:
            init = "distinct"
        else:
            init = _axis(a["init_seed"], b["init_seed"])
        order = _axis(a["data_order_seed"], b["data_order_seed"])
        nuisance = [lineage, init, order]
        dependent_nuisance = identical or "shared" in nuisance
        unknown = "unknown" in nuisance
        pairs.append({
            "a": a["member_id"], "b": b["member_id"], "supervision": supervision,
            "lineage": lineage, "init_seed": init, "data_order_seed": order,
            "identical_checkpoint": identical,
            "witness_independence": _combine(
                dependent_nuisance or supervision["overlap_coefficient"] > spec["max_overlap"],
                unknown),
            "deep_ensemble_independence": _combine(dependent_nuisance, unknown),
        })

    configs = [m["config_sha256"] for m in members]
    if n < 2:
        deep = {"status": "unverified", "reasons": ["need at least two members"]}
        witnesses = {"status": "unverified", "reasons": ["need at least two members"],
                     "certified_count": min(n, 1), "upper_bound_count": min(n, 1)}
    else:
        reasons: list[str] = []
        if regime != "identical_full_set":
            reasons.append("cross-validation-folds-share-supervision" if regime == "cv_partition"
                           else f"regime-{regime}-is-not-a-same-data-deep-ensemble")
        if None not in configs and len(set(configs)) > 1:
            reasons.append("architecture-config-differs")
        pair_states = [p["deep_ensemble_independence"] for p in pairs]
        if "dependent" in pair_states:
            reasons.append("shared-lineage-seed-or-checkpoint")
        if reasons:
            deep = {"status": "dependent", "reasons": reasons}
        elif "unverified" in pair_states or None in configs:
            deep = {"status": "unverified",
                    "reasons": ["undeclared seed, lineage or architecture for at least one pair"]}
        else:
            deep = {"status": "independent", "reasons": []}

        counts = _witness_counts(n, pairs, index)
        states = [p["witness_independence"] for p in pairs]
        if counts["certified"] == n:
            status, why = "independent", []
        elif counts["upper_bound"] < n:
            status = "dependent"
            why = [f"{sum(s == 'dependent' for s in states)} of {len(states)} member pairs share "
                   f"supervision above max_overlap={spec['max_overlap']} or share lineage/seeds"]
        else:
            status, why = "unverified", ["undeclared seed or lineage for at least one pair"]
        witnesses = {"status": status, "reasons": why, "certified_count": counts["certified"],
                     "upper_bound_count": counts["upper_bound"]}

    consistent = (spec["declared_kind"] == "other" or regime is None
                  or regime in KIND_REGIMES[spec["declared_kind"]])
    status = (deep if spec["purpose"] == "deep_ensemble_uncertainty" else witnesses)["status"]
    reasons = list((deep if spec["purpose"] == "deep_ensemble_uncertainty" else witnesses)["reasons"])
    if not consistent:
        reasons.append("declared-kind-contradicts-inventory")
        if status == "independent":
            status = "unverified"
    overlaps = [p["supervision"]["overlap_coefficient"] for p in pairs]
    return {
        "schema": ANCESTRY_REPORT_SCHEMA,
        "promotional": False,
        "claim": "declared training ancestry only; not an ink, surface or readability verdict",
        "ensemble_id": spec["ensemble_id"],
        "purpose": spec["purpose"],
        "status": status,
        "reasons": reasons,
        "declared_kind": spec["declared_kind"],
        "detected_regime": regime,
        "declared_kind_consistent": consistent,
        "max_overlap": spec["max_overlap"],
        "weighted_overlap": weights is not None,
        "members": [{"member_id": m["member_id"], "checkpoint_sha256": m["checkpoint_sha256"],
                     "training_units": len(m["training_units"]), "init_seed": m["init_seed"],
                     "data_order_seed": m["data_order_seed"]} for m in members],
        "member_count": n,
        "mean_overlap_coefficient": float(np.mean(overlaps)) if overlaps else None,
        "pairs": pairs,
        "deep_ensemble_uncertainty": deep,
        "independent_witnesses": witnesses,
        "limits": [
            "ancestry is declared, not extracted from checkpoint bytes",
            "overlap is computed on declared unit IDs; geometric overlap of differently "
            "named units is not detected",
            "agreement among members is never evidence of independence",
        ],
    }


# --------------------------------------------------------------------------- metrics


def _binary_entropy_bits(p: np.ndarray) -> np.ndarray:
    return -(xlogy(p, p) + xlogy(1.0 - p, 1.0 - p)) / math.log(2.0)


def disagreement(probabilities: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (mutual information, predictive entropy) in bits for (members, units)."""
    mean = probabilities.mean(axis=0)
    total = _binary_entropy_bits(mean)
    expected = _binary_entropy_bits(probabilities).mean(axis=0)
    gap = total - expected
    # Exactly agreeing members leave float residue of either sign; it must not order units.
    return np.where(gap > MI_NOISE_FLOOR, gap, 0.0), total


def _auroc(score: np.ndarray, failure: np.ndarray) -> float:
    positive = failure == 1
    n1 = int(positive.sum())
    n0 = len(failure) - n1
    if n1 == 0 or n0 == 0:
        return math.nan
    ranks = rankdata(score)
    return float((ranks[positive].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _aurc(score: np.ndarray, failure: np.ndarray) -> float:
    """Area under the risk-coverage curve, lowest uncertainty retained first.

    Ties are resolved at block ends, so the value does not depend on unit order.
    """
    n = len(failure)
    if n == 0:
        return math.nan
    order = np.argsort(score, kind="stable")
    s, f = score[order], failure[order]
    cumulative = np.cumsum(f)
    ends = np.flatnonzero(np.r_[s[1:] != s[:-1], True])
    starts = np.r_[0, ends[:-1] + 1]
    return float(np.sum((ends - starts + 1) * cumulative[ends] / (ends + 1)) / n)


_METRICS = ("auroc_mutual_information", "auroc_predictive_entropy",
            "aurc_mutual_information", "aurc_predictive_entropy")


def _metric_vector(mi: np.ndarray, entropy: np.ndarray, failure: np.ndarray) -> list[float]:
    return [_auroc(mi, failure), _auroc(entropy, failure), _aurc(mi, failure), _aurc(entropy, failure)]


def _interval(samples: np.ndarray, alpha: float) -> tuple[float, float]:
    low, high = np.nanquantile(samples, [alpha / 2.0, 1.0 - alpha / 2.0])
    return float(low), float(high)


def _decision(low: float, high: float) -> str:
    if low > 0.5:
        return "ranks_failures"
    if high < 0.5:
        return "inverted"
    return "not_distinguished_from_chance"


def rank_failures(units: Sequence[Mapping[str, Any]], probabilities: Mapping[str, np.ndarray],
                  *, threshold: float, strata: Sequence[str], min_class_count: int,
                  seed: int, replicates: int, alpha: float) -> dict[str, Any]:
    """Block-bootstrap failure ranking for ensembles over the same units.

    ``probabilities[name]`` is (members, units). A unit fails for an ensemble when
    its mean probability is on the wrong side of ``threshold`` for the sealed truth.
    """
    n = len(units)
    truth = np.array([u["truth"] for u in units])
    stratum = np.array([u["stratum"] for u in units])
    labels = [POOLED, *strata]
    in_label = {label: (np.ones(n, bool) if label == POOLED else stratum == label) for label in labels}
    per: dict[str, dict[str, np.ndarray]] = {}
    for name, p in probabilities.items():
        mi, entropy = disagreement(p)
        failure = ((p.mean(axis=0) >= threshold).astype(int) != truth).astype(int)
        per[name] = {"mi": mi, "entropy": entropy, "failure": failure}

    def vectors(index: np.ndarray) -> dict[tuple[str, str], list[float]]:
        out = {}
        for name, d in per.items():
            for label in labels:
                sel = index[in_label[label][index]]
                out[name, label] = _metric_vector(d["mi"][sel], d["entropy"][sel], d["failure"][sel])
        return out

    point = vectors(np.arange(n))
    group_index: dict[str, list[int]] = {}
    for i, u in enumerate(units):
        group_index.setdefault(u["group_id"], []).append(i)
    blocks = [np.array(v) for _, v in sorted(group_index.items())]
    rng = np.random.default_rng(seed)
    keys = list(point)
    draws = {k: np.full((replicates, len(_METRICS)), math.nan) for k in keys}
    for r in range(replicates):
        picks = rng.integers(0, len(blocks), len(blocks))
        for key, vector in vectors(np.concatenate([blocks[k] for k in picks])).items():
            draws[key][r] = vector

    def summarize(key: tuple[str, str], column: int, difference: np.ndarray | None = None) -> dict[str, Any]:
        samples = draws[key][:, column] if difference is None else difference
        valid = int(np.isfinite(samples).sum())
        return {"valid_replicates": valid} if valid < 0.9 * replicates else {
            "valid_replicates": valid, "ci": list(_interval(samples, alpha))}

    result: dict[str, Any] = {"ensembles": {}}
    for name, d in per.items():
        out: dict[str, Any] = {}
        for label in labels:
            key = (name, label)
            mask = in_label[label]
            fails = int(d["failure"][mask].sum())
            n_label = int(mask.sum())
            entry: dict[str, Any] = {"n": n_label, "n_failure": fails, "n_non_failure": n_label - fails}
            if min(fails, n_label - fails) < min_class_count:
                entry.update(status="unverified",
                             reason=f"fewer than {min_class_count} units in a failure class")
                out[label] = entry
                continue
            for column, metric in enumerate(_METRICS):
                entry[metric] = {"estimate": point[key][column], **summarize(key, column)}
            gain = draws[key][:, 0] - draws[key][:, 1]
            entry["auroc_mi_minus_entropy"] = {"estimate": point[key][0] - point[key][1],
                                               **summarize(key, 0, gain)}
            mi_ci = entry["auroc_mutual_information"].get("ci")
            gain_ci = entry["auroc_mi_minus_entropy"].get("ci")
            if mi_ci is None or gain_ci is None:
                entry.update(status="unverified", reason="too few valid bootstrap replicates")
            else:
                entry.update(status="measured", decision=_decision(*mi_ci),
                             incremental_over_confidence=gain_ci[0] > 0.0)
            out[label] = entry
        result["ensembles"][name] = out

    if len(per) == 2:
        a, b = sorted(per)
        comparison = {}
        for label in labels:
            ka, kb = (a, label), (b, label)
            ea, eb = result["ensembles"][a][label], result["ensembles"][b][label]
            if ea["status"] != "measured" or eb["status"] != "measured":
                comparison[label] = {"status": "unverified"}
                continue
            diff = draws[ka][:, 0] - draws[kb][:, 0]
            summary = summarize(ka, 0, diff)
            entry = {"status": "measured", "auroc_mi_a_minus_b": {
                "estimate": point[ka][0] - point[kb][0], **summary}}
            if "ci" not in summary:
                entry["status"] = "unverified"
            else:
                low, high = summary["ci"]
                entry["decision"] = ("a_exceeds_b" if low > 0 else "b_exceeds_a" if high < 0
                                     else "not_distinguished")
            comparison[label] = entry
        result["comparison_a_minus_b"] = comparison
    return result


def _pair_agreement(report: Mapping[str, Any], member_ids: Sequence[str],
                    probabilities: np.ndarray) -> dict[str, Any]:
    index = {m: i for i, m in enumerate(member_ids)}
    overlap, gap = [], []
    for pair in report["pairs"]:
        overlap.append(pair["supervision"]["overlap_coefficient"])
        gap.append(float(np.mean(np.abs(probabilities[index[pair["a"]]] - probabilities[index[pair["b"]]]))))
    overlap, gap = np.array(overlap), np.array(gap)
    if len(gap) < 3 or np.ptp(overlap) == 0 or np.ptp(gap) == 0:
        return {"status": "unverified", "pairs": len(gap),
                "reason": "needs three or more member pairs with varying supervision overlap "
                          "and varying disagreement; a symmetric CV partition cannot test this"}
    ranked_o, ranked_g = rankdata(overlap), rankdata(gap)
    return {"status": "measured_descriptive_only", "pairs": len(gap),
            "spearman_overlap_vs_mean_abs_difference": float(np.corrcoef(ranked_o, ranked_g)[0, 1])}


# --------------------------------------------------------------------------- controls


def _synthetic_panel(seed: int, members: int = 5, groups: int = 60, per_group: int = 4):
    """Planted ensembles: ``b`` disagrees where it errs, ``a`` errs in agreement."""
    rng = np.random.default_rng(seed)
    n = groups * per_group
    group = np.arange(n) // per_group
    truth = (group % 2).astype(int)
    units = [{"unit_id": f"u{i:04d}", "group_id": f"g{group[i]:03d}", "scroll_id": "heldout",
              "stratum": "supported_ink" if truth[i] else "negative_papyrus", "truth": int(truth[i])}
             for i in range(n)]
    hard = rng.random(n) < 0.3
    sign = np.where(truth == 1, 1.0, -1.0)
    center = np.where(hard, -2.5 * sign, 2.5 * sign)
    spread = np.where(hard, 2.0, 0.3)
    deep = center + rng.normal(size=(members, n)) * spread
    offsets = rng.normal(size=(members, 1))
    offsets -= offsets.mean()  # a nonzero mean would shift every unit's mean logit asymmetrically
    folds = center + offsets + rng.normal(size=(members, n)) * 0.3
    sigmoid = lambda z: 1.0 / (1.0 + np.exp(-z))  # noqa: E731
    return units, {"a": sigmoid(folds), "b": sigmoid(deep)}


def positive_control(*, alpha: float) -> dict[str, Any]:
    """Planted disagreement must be detected; agreeing errors and permuted units must not.

    The seed and replicate count are code constants, not spec fields: a control
    that depended on the spec's seed could be shopped for a passing draw. The
    permuted null is a calibration of the CI rule, so it is judged as a
    false-detection rate over several permutations rather than one draw.
    """
    units, panel = _synthetic_panel(CONTROL_SEED)
    kwargs = dict(threshold=0.5, strata=["negative_papyrus", "supported_ink"], min_class_count=5,
                  seed=CONTROL_SEED, replicates=CONTROL_REPLICATES, alpha=alpha)
    planted = rank_failures(units, panel, **kwargs)
    deep, folds = planted["ensembles"]["b"][POOLED], planted["ensembles"]["a"][POOLED]
    detected = (deep.get("decision") == "ranks_failures"
                and deep["auroc_mutual_information"]["estimate"] > 0.9)
    agreeing_missed = (folds.get("status") == "measured"
                       and folds["auroc_mutual_information"]["estimate"] < 0.65)
    false = trials = 0
    for trial in range(CONTROL_NULL_TRIALS):
        permutation = np.random.default_rng(CONTROL_SEED + 1 + trial).permutation(len(units))
        null = rank_failures(units, {k: v[:, permutation] for k, v in panel.items()}, **kwargs)
        for entry in null["ensembles"].values():
            trials += 1
            false += entry[POOLED].get("decision") == "ranks_failures"
    rate = false / trials
    return {"planted_disagreement_detected": bool(detected),
            "agreeing_errors_not_ranked": bool(agreeing_missed),
            "independent_auroc_mutual_information": deep.get("auroc_mutual_information", {}).get("estimate"),
            "agreeing_auroc_mutual_information": folds.get("auroc_mutual_information", {}).get("estimate"),
            "null_false_detection_rate": rate, "null_trials": trials,
            "fired": bool(detected and agreeing_missed and rate <= MAX_NULL_FALSE_DETECTION_RATE)}


def _synthetic_ancestry(kind: str) -> dict[str, Any]:
    pool = [f"block-{i:03d}" for i in range(100)]
    members = []
    for k in range(5):
        if kind == "cv_fold":
            units, init, order = [u for i, u in enumerate(pool) if i % 5 != k], 7, 7
        elif kind == "deep_ensemble":
            units, init, order = pool, k, 100 + k
        else:
            units, init, order = pool[k * 20:(k + 1) * 20], k, 100 + k
        members.append({"member_id": f"{kind}-{k}",
                        "checkpoint_sha256": hashlib.sha256(f"{kind}-{k}".encode()).hexdigest(),
                        "training_units": units, "training_scroll_ids": ["train-scroll"],
                        "init_seed": init, "data_order_seed": order, "parents": [],
                        "config_sha256": hashlib.sha256(b"architecture").hexdigest()})
    return {"schema": ANCESTRY_SCHEMA, "ensemble_id": f"synthetic-{kind}", "declared_kind": kind,
            "purpose": "independent_witnesses", "max_overlap": 0.0, "members": members}


def self_test(*, alpha: float = 0.05) -> dict[str, Any]:
    cv = audit_ancestry(_synthetic_ancestry("cv_fold"))
    deep = audit_ancestry(_synthetic_ancestry("deep_ensemble"))
    disjoint = audit_ancestry(_synthetic_ancestry("independent_subsets"))
    control = positive_control(alpha=alpha)
    checks = {
        "cv_partition_detected": cv["detected_regime"] == "cv_partition",
        "cv_overlap_is_three_quarters": abs(cv["mean_overlap_coefficient"] - 0.75) < 1e-12,
        "cv_is_one_witness": cv["independent_witnesses"]["certified_count"] == 1,
        "cv_is_not_a_deep_ensemble": cv["deep_ensemble_uncertainty"]["status"] == "dependent",
        "deep_ensemble_recognized": deep["deep_ensemble_uncertainty"]["status"] == "independent",
        "deep_ensemble_is_one_witness": deep["independent_witnesses"]["certified_count"] == 1,
        "disjoint_subsets_are_five_witnesses": disjoint["independent_witnesses"]["certified_count"] == 5,
        "failure_ranking_control_fired": control["fired"],
    }
    return {"schema": "scroliq-ensemble-self-test-v1", "passed": all(checks.values()),
            "checks": checks, "control": control}


# --------------------------------------------------------------------------- evaluation


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_under(root: Path, relative: Any, field: str) -> Path:
    text = _text(relative, field)
    path = (root / text).resolve()
    if Path(text).is_absolute() or not path.is_relative_to(root.resolve()):
        _fail(f"{field} must be a relative path inside the spec directory")
    return path


def validate_spec(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("schema") != SPEC_SCHEMA:
        _fail(f"spec.schema must be {SPEC_SCHEMA}")
    strata = _ids(document.get("strata"), "spec.strata")
    if POOLED in strata:
        _fail(f"spec.strata may not use the reserved name {POOLED!r}")
    bootstrap = document.get("bootstrap")
    if not isinstance(bootstrap, dict):
        _fail("spec.bootstrap must be an object")
    seed = _seed_or_none(bootstrap.get("seed"), "spec.bootstrap.seed")
    replicates = bootstrap.get("replicates")
    if seed is None or type(replicates) is not int or replicates < 100:
        _fail("spec.bootstrap needs an integer seed and replicates >= 100")
    min_class = document.get("min_class_count")
    if type(min_class) is not int or min_class < 1:
        _fail("spec.min_class_count must be a positive integer")
    ensembles = document.get("ensembles")
    if not isinstance(ensembles, dict) or set(ensembles) != {"a", "b"}:
        _fail("spec.ensembles must define exactly 'a' and 'b'")
    parsed = {}
    for name, entry in ensembles.items():
        if not isinstance(entry, dict):
            _fail(f"spec.ensembles.{name} must be an object")
        expected = entry.get("expected_regime")
        if expected is not None and expected not in REGIMES:
            _fail(f"spec.ensembles.{name}.expected_regime must be one of {list(REGIMES)} or omitted")
        parsed[name] = {"label": _text(entry.get("label"), f"spec.ensembles.{name}.label"),
                        "ancestry": _text(entry.get("ancestry"), f"spec.ensembles.{name}.ancestry"),
                        "expected_regime": expected}
    raw_units = document.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        _fail("spec.units must be a non-empty list")
    units, seen = [], set()
    for i, row in enumerate(raw_units):
        if not isinstance(row, dict):
            _fail(f"spec.units[{i}] must be an object")
        unit = {k: _text(row.get(k), f"spec.units[{i}].{k}")
                for k in ("unit_id", "group_id", "scroll_id", "stratum")}
        if unit["unit_id"] in seen:
            _fail(f"duplicate unit_id {unit['unit_id']!r}")
        seen.add(unit["unit_id"])
        if unit["stratum"] not in strata:
            _fail(f"unit {unit['unit_id']!r} has stratum outside spec.strata")
        if type(row.get("truth")) is not int or row["truth"] not in (0, 1):
            _fail(f"unit {unit['unit_id']!r} needs integer truth 0 (physical negative) or 1 (supported ink)")
        unit["truth"] = row["truth"]
        units.append(unit)
    return {"strata": strata, "bootstrap": {"seed": seed, "replicates": replicates},
            "alpha": _number(document.get("alpha"), "spec.alpha", 0.0, 1.0),
            "threshold": _number(document.get("decision_threshold"), "spec.decision_threshold", 0.0, 1.0),
            "min_class_count": min_class, "ensembles": parsed, "units": units}


def _check_heldout(units: Sequence[Mapping[str, Any]], manifests: Mapping[str, Mapping[str, Any]]) -> None:
    eval_ids = {u["unit_id"] for u in units} | {u["group_id"] for u in units}
    eval_scrolls = {u["scroll_id"] for u in units}
    for name, manifest in manifests.items():
        for member in manifest["members"]:
            seen = set(member["training_units"]) | set(member["calibration_units"] or ())
            if seen & eval_ids:
                _fail(f"evaluation unit overlaps training/calibration ancestry of "
                      f"{name}:{member['member_id']}: {sorted(seen & eval_ids)[:3]}")
            if set(member["training_scroll_ids"]) & eval_scrolls:
                _fail(f"evaluation scroll is in the training scrolls of {name}:{member['member_id']}")


def _load_probabilities(path: Path, name: str, member_ids: Sequence[str], unit_ids: Sequence[str]) -> np.ndarray:
    with np.load(path, allow_pickle=False) as data:
        for key in ("unit_ids", name, f"{name}_members"):
            if key not in data:
                _fail(f"predictions are missing array {key!r}")
        stored_units = [str(u) for u in data["unit_ids"]]
        stored_members = [str(m) for m in data[f"{name}_members"]]
        values = np.asarray(data[name], dtype=float)
    if sorted(stored_units) != sorted(unit_ids) or len(set(stored_units)) != len(stored_units):
        _fail("predictions unit_ids must equal the spec unit IDs exactly")
    if sorted(stored_members) != sorted(member_ids):
        _fail(f"predictions {name}_members must equal the ancestry member IDs exactly")
    if values.shape != (len(stored_members), len(stored_units)):
        _fail(f"predictions {name} must have shape (members, units)")
    if not np.isfinite(values).all() or values.min() < 0 or values.max() > 1:
        _fail(f"predictions {name} must be finite probabilities in [0, 1]")
    rows = [stored_members.index(m) for m in member_ids]
    cols = [stored_units.index(u) for u in unit_ids]
    return values[np.ix_(rows, cols)]


def evaluate(spec_path: Path) -> dict[str, Any]:
    spec_path = Path(spec_path)
    root = spec_path.parent
    document = json.loads(spec_path.read_text(encoding="utf-8"))
    spec = validate_spec(document)
    predictions_path = _resolve_under(root, document.get("predictions"), "spec.predictions")
    manifests, reports, files = {}, {}, {"spec": _sha256_file(spec_path),
                                         "predictions": _sha256_file(predictions_path)}
    for name, entry in spec["ensembles"].items():
        path = _resolve_under(root, entry["ancestry"], f"spec.ensembles.{name}.ancestry")
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifests[name] = validate_ancestry(raw)
        reports[name] = audit_ancestry(raw)
        files[f"ancestry_{name}"] = _sha256_file(path)
        expected = entry["expected_regime"]
        if expected is not None and reports[name]["detected_regime"] != expected:
            _fail(f"ensemble {name!r} is {reports[name]['detected_regime']}, spec requires {expected}")
    if len(manifests["a"]["members"]) != len(manifests["b"]["members"]):
        _fail("ensembles must have equal size for a matched comparison")
    _check_heldout(spec["units"], manifests)

    unit_ids = [u["unit_id"] for u in spec["units"]]
    probabilities, agreement = {}, {}
    for name, manifest in manifests.items():
        member_ids = [m["member_id"] for m in manifest["members"]]
        probabilities[name] = _load_probabilities(predictions_path, name, member_ids, unit_ids)
        agreement[name] = _pair_agreement(reports[name], member_ids, probabilities[name])

    boot = spec["bootstrap"]
    control = positive_control(alpha=spec["alpha"])
    configs = {m["config_sha256"] for manifest in manifests.values() for m in manifest["members"]}
    matched = None if None in configs else len(configs) == 1
    report: dict[str, Any] = {
        "schema": EVALUATION_REPORT_SCHEMA,
        "promotional": False,
        "claim": "failure-ranking validity of ensemble disagreement on a frozen scroll-disjoint set; "
                 "not an ink, surface or readability verdict",
        "proof_question": PROOF_QUESTION,
        "sha256": files,
        "decision_threshold": spec["threshold"],
        "alpha": spec["alpha"],
        "bootstrap": boot,
        "units": len(spec["units"]),
        "groups": len({u["group_id"] for u in spec["units"]}),
        "design": {"ensemble_size": len(manifests["a"]["members"]), "same_architecture": matched,
                   "labels": {k: v["label"] for k, v in spec["ensembles"].items()}},
        "heldout_checks": "no evaluation unit, group or scroll appears in any member's training or "
                          "calibration ancestry",
        "positive_control": control,
        "ancestry": reports,
        "pair_agreement_vs_overlap": agreement,
    }
    if not control["fired"]:
        report.update(status="unverified",
                      reason="built-in planted-signal/null control did not fire; no verdict is issued")
        return report
    ranking = rank_failures(spec["units"], probabilities, threshold=spec["threshold"],
                            strata=spec["strata"], min_class_count=spec["min_class_count"],
                            seed=boot["seed"], replicates=boot["replicates"], alpha=spec["alpha"])
    report["status"] = "measured"
    report["ensembles"] = ranking["ensembles"]
    comparison = ranking["comparison_a_minus_b"]
    if matched is not True:
        for entry in comparison.values():
            entry["status"] = "unverified"
            entry["reason"] = "architecture equality across ensembles is not established"
    report["comparison_a_minus_b"] = comparison
    return report


# --------------------------------------------------------------------------- CLI


def _write_create_only(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scroliq-ensemble-independence", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    anc = sub.add_parser("ancestry", help="pairwise training-ancestry overlap and witness count")
    anc.add_argument("--manifest", type=Path, required=True)
    anc.add_argument("--out", type=Path, required=True, help="create-only JSON report")
    anc.add_argument("--fail-unless-independent", action="store_true",
                     help="exit 1 unless the declared purpose's status is 'independent'")
    ev = sub.add_parser("evaluate", help="failure-ranking comparison of two ensembles")
    ev.add_argument("--spec", type=Path, required=True)
    ev.add_argument("--out", type=Path, required=True, help="create-only JSON report")
    sub.add_parser("self-test", help="built-in synthetic controls; exits 1 if any fails")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            result = self_test()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["passed"] else 1
        if args.command == "ancestry":
            report = audit_ancestry(json.loads(args.manifest.read_text(encoding="utf-8")))
            _write_create_only(args.out, report)
            print(f"{report['ensemble_id']}: {report['status']} "
                  f"({report['independent_witnesses']['certified_count']} of {report['member_count']} "
                  f"members certified independent witnesses; regime {report['detected_regime']})")
            return 1 if args.fail_unless_independent and report["status"] != "independent" else 0
        report = evaluate(args.spec)
        _write_create_only(args.out, report)
        print(f"evaluation {report['status']}; control fired: {report['positive_control']['fired']}")
        return 0
    except (EnsembleIndependenceError, OSError, ValueError) as exc:
        parser.exit(2, f"ensemble independence refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
