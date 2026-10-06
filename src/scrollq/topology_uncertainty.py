"""Post-hoc topology-conditioned uncertainty audit of frozen surface predictions.

Question, fixed before any real prediction is read: on a frozen ensemble of
surface-support predictions (seeds, checkpoints or controlled inference
perturbations; nothing is retrained), does epistemic disagreement rank
*independently known structural failures* (cross-roll impostors, drifted
surfaces, phantom predictions in unscanned CT, planted winding errors) better
than the ordinary confidence the same ensemble already reports?

Each unit is one TIFXYZ-grid patch with member support fields ``(members, H, W)``
in [0, 1], a physical ``group_id``, a ``scroll_id`` and a fixture ``stratum`` that
comes from sealed fixture construction, never from this audit. Per unit:

* ``mi``: mean mutual information (members vs. their mean) over valid cells;
* ``confidence``: mean predictive entropy of the ensemble mean, the baseline;
* indicators (descriptive): significant H0/H1 persistence features of the
  consensus field and their spread across members (``topology_member_spread``,
  exploratory and outside the decision rule);
* optional local enrichment: AUROC of cell MI vs. cell entropy against a
  fixture-supplied failure-location mask (secondary, outside the decision rule).

Decision rule (constants in code, so a spec cannot shop for a pass):
``PROMOTE`` only if the pooled MI AUROC interval is above 0.5, the pooled paired
gain over confidence has a lower bound above 0, at least half the failure strata
individually beat confidence and none is worse. Otherwise ``DISMISS`` (flagged
``underpowered`` if the gain interval still reaches ``MIN_MEANINGFUL_GAIN``).
A control that does not fire, a stratum without enough units in a class, or any
unmeasured stratum makes the verdict ``UNVERIFIED``; there is no partial pass.

This is evidence machinery. It is not an ink, readability or surface verdict,
adds no learned confidence head, and borrows no TUNE++ code (its public
repository states no license, and its released topology module is a
distance-transform approximation, not the persistent-homology method of the
paper).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import rankdata

from scrollq.ensemble_independence import (
    EnsembleIndependenceError, audit_ancestry, disagreement, validate_ancestry,
)
from scrollq.persistent_topology import persistence

SPEC_SCHEMA = "scroliq-topology-uq-spec-v1"
REPORT_SCHEMA = "scroliq-topology-uq-report-v1"
CONTROL_SEED = 20261007
CONTROL_REPLICATES = 300
CONTROL_NULL_TRIALS = 12
MAX_NULL_FALSE_DETECTION_RATE = 0.2
MIN_VALID_CELLS = 16
MIN_MASK_CELLS = 3
MIN_MEANINGFUL_GAIN = 0.1
POOLED = "pooled"
SCORES = ("mi", "confidence", "topology_member_spread")
PROOF_QUESTION = ("does ensemble disagreement concentrate on independently known structural "
                  "failures better than raw model confidence?")


class TopologyUncertaintyError(ValueError):
    """Raised when a spec or input violates the contract."""


def _fail(message: str) -> None:
    raise TopologyUncertaintyError(message)


# --------------------------------------------------------------------------- per-unit scores


def _consensus_features(field: np.ndarray, valid: np.ndarray, floor: float) -> tuple[int, int]:
    """Significant extra components (H0) and holes (H1) of one support field."""
    diagrams = persistence(field, valid)
    components = sum(1 for p in diagrams["h0"]
                     if p["death"] is not None and p["birth"] - p["death"] >= floor)
    holes = sum(1 for p in diagrams["h1"]
                if p["birth"] - (0.0 if p["death"] is None else p["death"]) >= floor)
    return components, holes


def unit_scores(probabilities: np.ndarray, valid: np.ndarray, mask: np.ndarray | None,
                floor: float) -> dict[str, Any]:
    """Scores for one unit from ``(members, H, W)`` probabilities."""
    members = probabilities.shape[0]
    flat = probabilities.reshape(members, -1)
    ok = valid.ravel()
    mi, entropy = disagreement(flat[:, ok])
    consensus = probabilities.mean(axis=0)
    components, holes = _consensus_features(consensus, valid, floor)
    per_member = np.array([_consensus_features(probabilities[k], valid, floor)
                           for k in range(members)], dtype=float)
    out: dict[str, Any] = {
        "mi": float(mi.mean()), "confidence": float(entropy.mean()),
        "topology_member_spread": float(per_member.std(axis=0).mean()),
        "consensus_components": components, "consensus_holes": holes,
        "local_mi": math.nan, "local_confidence": math.nan,
    }
    if mask is not None:
        positive = mask.ravel()[ok]
        if min(int(positive.sum()), int((~positive).sum())) >= MIN_MASK_CELLS:
            out["local_mi"] = _auroc(mi, positive.astype(int))
            out["local_confidence"] = _auroc(entropy, positive.astype(int))
    return out


def _auroc(score: np.ndarray, label: np.ndarray) -> float:
    positive = label == 1
    n1 = int(positive.sum())
    n0 = len(label) - n1
    if n1 == 0 or n0 == 0:
        return math.nan
    ranks = rankdata(score)
    return float((ranks[positive].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


# --------------------------------------------------------------------------- ranking


def _ci(samples: np.ndarray, alpha: float, replicates: int) -> dict[str, Any]:
    valid = int(np.isfinite(samples).sum())
    if valid < 0.9 * replicates:
        return {"valid_replicates": valid}
    low, high = np.nanquantile(samples, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {"valid_replicates": valid, "ci": [float(low), float(high)]}


def _stratum_verdict(mi_ci: list[float], gain_ci: list[float]) -> str:
    if gain_ci[1] < 0.0:
        return "worse_than_confidence"
    if gain_ci[0] > 0.0 and mi_ci[0] > 0.5:
        return "beats_confidence"
    return "not_distinguished"


def rank_units(rows: Sequence[Mapping[str, Any]], *, failure_strata: Sequence[str],
               reference: str, min_class_count: int, seed: int, replicates: int,
               alpha: float) -> dict[str, Any]:
    """Block-bootstrap ranking of failures against the reference stratum."""
    n = len(rows)
    stratum = np.array([r["stratum"] for r in rows])
    score = {name: np.array([r[name] for r in rows], dtype=float) for name in SCORES}
    labels = [POOLED, *failure_strata]
    keep = {POOLED: np.ones(n, bool)}
    keep.update({s: (stratum == s) | (stratum == reference) for s in failure_strata})

    def vector(index: np.ndarray, label: str) -> list[float]:
        sel = index[keep[label][index]]
        failure = (stratum[sel] != reference).astype(int)
        return [_auroc(score[name][sel], failure) for name in SCORES]

    groups: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(r["group_id"], []).append(i)
    blocks = [np.array(v) for _, v in sorted(groups.items())]
    rng = np.random.default_rng(seed)
    draws = {label: np.full((replicates, len(SCORES)), math.nan) for label in labels}
    for r in range(replicates):
        picks = np.concatenate([blocks[k] for k in rng.integers(0, len(blocks), len(blocks))])
        for label in labels:
            draws[label][r] = vector(picks, label)

    result: dict[str, Any] = {}
    everything = np.arange(n)
    for label in labels:
        selected = keep[label]
        n_failure = int((selected & (stratum != reference)).sum())
        n_reference = int((selected & (stratum == reference)).sum())
        entry: dict[str, Any] = {"n_failure": n_failure, "n_reference": n_reference}
        if min(n_failure, n_reference) < min_class_count:
            entry.update(status="unverified",
                         reason=f"fewer than {min_class_count} units in a class")
            result[label] = entry
            continue
        point = vector(everything, label)
        d = draws[label]
        for column, name in enumerate(SCORES):
            entry[f"auroc_{name}"] = {"estimate": point[column],
                                      **_ci(d[:, column], alpha, replicates)}
        gain = {"estimate": point[0] - point[1], **_ci(d[:, 0] - d[:, 1], alpha, replicates)}
        entry["auroc_mi_minus_confidence"] = gain
        mi_ci = entry["auroc_mi"].get("ci")
        if mi_ci is None or "ci" not in gain:
            entry.update(status="unverified", reason="too few valid bootstrap replicates")
        else:
            entry.update(status="measured",
                         decision=_stratum_verdict(mi_ci, gain["ci"]))
        result[label] = entry
    return result


def local_enrichment(rows: Sequence[Mapping[str, Any]], *, seed: int, replicates: int,
                     alpha: float) -> dict[str, Any]:
    """Secondary: within-unit AUROC of cell MI vs. cell entropy against failure masks."""
    mi = np.array([r["local_mi"] for r in rows], dtype=float)
    conf = np.array([r["local_confidence"] for r in rows], dtype=float)
    eligible = np.isfinite(mi) & np.isfinite(conf)
    if not eligible.any():
        return {"status": "unverified", "reason": "no unit supplied a usable failure-location mask"}
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(r["group_id"], []).append(i)
    blocks = [np.array(v) for _, v in sorted(groups.items())]
    rng = np.random.default_rng(seed)
    draws = np.full((replicates, 3), math.nan)
    for r in range(replicates):
        picks = np.concatenate([blocks[k] for k in rng.integers(0, len(blocks), len(blocks))])
        picks = picks[eligible[picks]]
        if picks.size:
            draws[r] = [mi[picks].mean(), conf[picks].mean(), (mi - conf)[picks].mean()]
    return {
        "status": "measured", "units": int(eligible.sum()),
        "mean_cell_auroc_mi": {"estimate": float(mi[eligible].mean()),
                               **_ci(draws[:, 0], alpha, replicates)},
        "mean_cell_auroc_confidence": {"estimate": float(conf[eligible].mean()),
                                       **_ci(draws[:, 1], alpha, replicates)},
        "mean_cell_auroc_mi_minus_confidence": {
            "estimate": float((mi - conf)[eligible].mean()), **_ci(draws[:, 2], alpha, replicates)},
        "role": "secondary and descriptive; not part of the decision rule",
    }


def decide(strata: Mapping[str, Mapping[str, Any]], failure_strata: Sequence[str]) -> dict[str, Any]:
    """Apply the frozen decision rule to ``rank_units`` output."""
    entries = [strata[POOLED], *(strata[s] for s in failure_strata)]
    unverified = [label for label, e in strata.items() if e["status"] != "measured"]
    if unverified:
        return {"verdict": "UNVERIFIED", "reasons": [f"unmeasured: {sorted(unverified)}"],
                "underpowered": None}
    pooled = strata[POOLED]
    beating = [s for s in failure_strata if strata[s]["decision"] == "beats_confidence"]
    worse = [s for s in failure_strata if strata[s]["decision"] == "worse_than_confidence"]
    need = math.ceil(len(failure_strata) / 2)
    reasons: list[str] = []
    if pooled["decision"] != "beats_confidence":
        reasons.append(f"pooled decision is {pooled['decision']}")
    if len(beating) < need:
        reasons.append(f"{len(beating)} of {len(failure_strata)} strata beat confidence; need {need}")
    if worse:
        reasons.append(f"worse than confidence in {sorted(worse)}")
    del entries
    if not reasons:
        return {"verdict": "PROMOTE", "reasons": [], "underpowered": False,
                "strata_beating_confidence": beating}
    upper = pooled["auroc_mi_minus_confidence"]["ci"][1]
    return {"verdict": "DISMISS", "reasons": reasons, "underpowered": upper >= MIN_MEANINGFUL_GAIN,
            "strata_beating_confidence": beating}


# --------------------------------------------------------------------------- controls


def _synthetic_units(seed: int, per_stratum: int = 24, members: int = 4, size: int = 10):
    """Planted fields.

    ``reference``: broad aleatoric band (members agree at p=0.5), so entropy is high
    and disagreement zero. ``disagreeing_fault``: confident except a mask band where
    members split. ``confident_fault``: every member confidently wrong, no
    disagreement anywhere. Disagreement must rank the second, not the third.
    """
    rng = np.random.default_rng(seed)
    units = []
    for stratum in ("reference", "disagreeing_fault", "confident_fault"):
        for k in range(per_stratum):
            # Noise is shared by all members, so agreeing members have exactly zero
            # disagreement and MI cannot rank by noise scale alone.
            shared = rng.normal(0, 0.01, (1, size, size))
            p = np.broadcast_to(0.95 + shared, (members, size, size)).copy()
            mask = np.zeros((size, size), bool)
            if stratum == "reference":
                p[:, :, : size // 2] = 0.5 + shared[:, :, : size // 2]
            elif stratum == "disagreeing_fault":
                mask[4:7, :] = True
                split = np.where(np.arange(members) % 2 == 0, 0.95, 0.05)
                p[:, 4:7, :] = split[:, None, None] + shared[:, 4:7, :]
            p = np.clip(p, 0.0, 1.0)
            units.append({"unit_id": f"{stratum}-{k:03d}", "group_id": f"g{(len(units)) // 3:03d}",
                          "stratum": stratum, "p": p,
                          "valid": np.ones((size, size), bool),
                          "mask": mask if stratum == "disagreeing_fault" else None})
    return units


def positive_control(*, alpha: float) -> dict[str, Any]:
    """Planted disagreement must be ranked and beat confidence; confident errors and
    permuted labels must not be credited. Seed and replicates are code constants."""
    units = _synthetic_units(CONTROL_SEED)
    rows = [{**{k: u[k] for k in ("unit_id", "group_id", "stratum")},
             **unit_scores(u["p"], u["valid"], u["mask"], 0.2)} for u in units]
    kwargs = dict(failure_strata=["disagreeing_fault", "confident_fault"], reference="reference",
                  min_class_count=5, seed=CONTROL_SEED, replicates=CONTROL_REPLICATES, alpha=alpha)
    planted = rank_units(rows, **kwargs)
    hit, miss = planted["disagreeing_fault"], planted["confident_fault"]
    detected = hit.get("decision") == "beats_confidence" and hit["auroc_mi"]["estimate"] > 0.9
    confident_not_credited = (miss.get("status") == "measured"
                              and miss["decision"] != "beats_confidence"
                              and miss["auroc_mi"]["estimate"] < 0.7)
    local = local_enrichment(rows, seed=CONTROL_SEED, replicates=CONTROL_REPLICATES, alpha=alpha)
    local_hit = (local.get("status") == "measured"
                 and local["mean_cell_auroc_mi"]["estimate"] > 0.9)
    false = 0
    for trial in range(CONTROL_NULL_TRIALS):
        order = np.random.default_rng(CONTROL_SEED + 1 + trial).permutation(len(rows))
        shuffled = [{**r, "stratum": rows[j]["stratum"]} for r, j in zip(rows, order)]
        null = rank_units(shuffled, **kwargs)
        false += any(null[s].get("decision") == "beats_confidence"
                     for s in ("disagreeing_fault", "confident_fault"))
    rate = false / CONTROL_NULL_TRIALS
    return {"planted_disagreement_ranked_above_confidence": bool(detected),
            "confident_errors_not_credited": bool(confident_not_credited),
            "local_enrichment_detected": bool(local_hit),
            "disagreeing_auroc_mi": hit.get("auroc_mi", {}).get("estimate"),
            "disagreeing_auroc_confidence": hit.get("auroc_confidence", {}).get("estimate"),
            "confident_auroc_mi": miss.get("auroc_mi", {}).get("estimate"),
            "null_false_detection_rate": rate, "null_trials": CONTROL_NULL_TRIALS,
            "fired": bool(detected and confident_not_credited and local_hit
                          and rate <= MAX_NULL_FALSE_DETECTION_RATE)}


def self_test(*, alpha: float = 0.05) -> dict[str, Any]:
    control = positive_control(alpha=alpha)
    # A rule with nothing to credit must dismiss, and one with an empty class must not verdict.
    flat = {POOLED: {"status": "measured", "decision": "not_distinguished",
                     "auroc_mi_minus_confidence": {"ci": [-0.2, 0.05]}},
            "a": {"status": "measured", "decision": "not_distinguished"}}
    sparse = {POOLED: {"status": "unverified"}, "a": {"status": "measured", "decision": "x"}}
    checks = {
        "positive_control_fired": control["fired"],
        "no_gain_is_dismissed": decide(flat, ["a"])["verdict"] == "DISMISS",
        "unmeasured_stratum_is_unverified": decide(sparse, ["a"])["verdict"] == "UNVERIFIED",
    }
    return {"schema": "scroliq-topology-uq-self-test-v1", "passed": all(checks.values()),
            "checks": checks, "control": control}


# --------------------------------------------------------------------------- spec + evaluation


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    return value.strip()


def validate_spec(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("schema") != SPEC_SCHEMA:
        _fail(f"spec.schema must be {SPEC_SCHEMA}")
    strata = document.get("failure_strata")
    if not isinstance(strata, list) or not strata:
        _fail("spec.failure_strata must be a non-empty list")
    strata = [_text(s, "spec.failure_strata") for s in strata]
    reference = _text(document.get("reference_stratum"), "spec.reference_stratum")
    if len(set(strata)) != len(strata) or reference in strata or POOLED in strata + [reference]:
        _fail("spec strata must be distinct, exclude the reference, and not use 'pooled'")
    boot = document.get("bootstrap")
    if not isinstance(boot, dict) or type(boot.get("seed")) is not int or boot["seed"] < 0 \
            or type(boot.get("replicates")) is not int or boot["replicates"] < 100:
        _fail("spec.bootstrap needs a nonnegative integer seed and replicates >= 100")
    for key, low, high in (("alpha", 0.0, 1.0), ("persistence_floor", 0.0, 1.0)):
        v = document.get(key)
        if type(v) not in (int, float) or not low < float(v) < high:
            _fail(f"spec.{key} must be a number in ({low}, {high})")
    min_class = document.get("min_class_count")
    if type(min_class) is not int or min_class < 1:
        _fail("spec.min_class_count must be a positive integer")
    rows, seen = [], set()
    raw = document.get("units")
    if not isinstance(raw, list) or not raw:
        _fail("spec.units must be a non-empty list")
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            _fail(f"spec.units[{i}] must be an object")
        unit = {k: _text(row.get(k), f"spec.units[{i}].{k}")
                for k in ("unit_id", "group_id", "scroll_id", "stratum")}
        if unit["unit_id"] in seen:
            _fail(f"duplicate unit_id {unit['unit_id']!r}")
        seen.add(unit["unit_id"])
        if unit["stratum"] not in strata + [reference]:
            _fail(f"unit {unit['unit_id']!r} has a stratum outside the spec")
        rows.append(unit)
    return {"failure_strata": strata, "reference": reference, "bootstrap": boot,
            "alpha": float(document["alpha"]), "floor": float(document["persistence_floor"]),
            "min_class_count": min_class, "units": rows}


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


def _check_heldout(units: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> None:
    eval_ids = {u["unit_id"] for u in units} | {u["group_id"] for u in units}
    eval_scrolls = {u["scroll_id"] for u in units}
    for member in manifest["members"]:
        seen = set(member["training_units"]) | set(member["calibration_units"] or ())
        if seen & eval_ids:
            _fail(f"evaluation unit overlaps training/calibration ancestry of "
                  f"{member['member_id']}: {sorted(seen & eval_ids)[:3]}")
        if set(member["training_scroll_ids"]) & eval_scrolls:
            _fail(f"evaluation scroll is in the training scrolls of {member['member_id']}")


def _load_fields(path: Path, member_ids: Sequence[str], units: Sequence[Mapping[str, Any]]):
    out = {}
    with np.load(path, allow_pickle=False) as data:
        if "members" not in data:
            _fail("predictions are missing array 'members'")
        stored = [str(m) for m in data["members"]]
        if sorted(stored) != sorted(member_ids) or len(set(stored)) != len(stored):
            _fail("predictions members must equal the ancestry member IDs exactly")
        order = [stored.index(m) for m in member_ids]
        for unit in units:
            key = f"p/{unit['unit_id']}"
            if key not in data:
                _fail(f"predictions are missing array {key!r}")
            p = np.asarray(data[key], dtype=float)
            if p.ndim != 3 or p.shape[0] != len(member_ids):
                _fail(f"{key} must have shape (members, H, W)")
            p = p[order]
            valid = (np.asarray(data[f"valid/{unit['unit_id']}"], dtype=bool)
                     if f"valid/{unit['unit_id']}" in data else np.ones(p.shape[1:], bool))
            mask = (np.asarray(data[f"mask/{unit['unit_id']}"], dtype=bool)
                    if f"mask/{unit['unit_id']}" in data else None)
            if valid.shape != p.shape[1:] or (mask is not None and mask.shape != p.shape[1:]):
                _fail(f"valid/mask for {unit['unit_id']!r} must match the grid shape")
            valid = valid & np.isfinite(p).all(axis=0)
            if int(valid.sum()) < MIN_VALID_CELLS:
                _fail(f"{unit['unit_id']!r} has fewer than {MIN_VALID_CELLS} valid cells")
            if p[:, valid].min() < 0 or p[:, valid].max() > 1:
                _fail(f"{key} must hold probabilities in [0, 1]")
            out[unit["unit_id"]] = (np.nan_to_num(p), valid, mask)
    return out


def evaluate(spec_path: Path) -> dict[str, Any]:
    spec_path = Path(spec_path)
    root = spec_path.parent
    document = json.loads(spec_path.read_text(encoding="utf-8"))
    spec = validate_spec(document)
    predictions = _resolve_under(root, document.get("predictions"), "spec.predictions")
    ancestry_path = _resolve_under(root, document.get("ancestry"), "spec.ancestry")
    raw = json.loads(ancestry_path.read_text(encoding="utf-8"))
    manifest = validate_ancestry(raw)
    ancestry = audit_ancestry(raw)
    _check_heldout(spec["units"], manifest)
    fields = _load_fields(predictions, [m["member_id"] for m in manifest["members"]], spec["units"])

    boot = spec["bootstrap"]
    control = positive_control(alpha=spec["alpha"])
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "promotional": False,
        "claim": "ranking of independently known structural failures by post-hoc ensemble "
                 "disagreement vs. raw confidence; not an ink, surface or readability verdict",
        "proof_question": PROOF_QUESTION,
        "sha256": {"spec": _sha256_file(spec_path), "predictions": _sha256_file(predictions),
                   "ancestry": _sha256_file(ancestry_path)},
        "alpha": spec["alpha"], "bootstrap": boot, "persistence_floor": spec["floor"],
        "units": len(spec["units"]), "groups": len({u["group_id"] for u in spec["units"]}),
        "ensemble": {"detected_regime": ancestry["detected_regime"],
                     "certified_independent_witnesses":
                         ancestry["independent_witnesses"]["certified_count"],
                     "members": ancestry["member_count"],
                     "note": "disagreement among dependent members is ranked here as a signal; "
                             "it does not make them independent witnesses"},
        "decision_rule": {"min_meaningful_gain": MIN_MEANINGFUL_GAIN,
                          "required_strata_beating_confidence": math.ceil(
                              len(spec["failure_strata"]) / 2),
                          "baseline": "mean predictive entropy of the ensemble mean"},
        "heldout_checks": "no evaluation unit, group or scroll appears in any member's training "
                          "or calibration ancestry",
        "positive_control": control,
    }
    if not control["fired"]:
        report.update(verdict="UNVERIFIED",
                      reason="built-in planted-signal/null control did not fire; no verdict is issued")
        return report
    rows = [{**u, **unit_scores(*fields[u["unit_id"]], spec["floor"])} for u in spec["units"]]
    strata = rank_units(rows, failure_strata=spec["failure_strata"], reference=spec["reference"],
                        min_class_count=spec["min_class_count"], seed=boot["seed"],
                        replicates=boot["replicates"], alpha=spec["alpha"])
    report["strata"] = strata
    report["decision"] = decide(strata, spec["failure_strata"])
    report["verdict"] = report["decision"]["verdict"]
    report["local_enrichment"] = local_enrichment(rows, seed=boot["seed"],
                                                  replicates=boot["replicates"], alpha=spec["alpha"])
    report["topology_indicators"] = {
        s: {"units": sum(r["stratum"] == s for r in rows),
            "mean_consensus_components": float(np.mean([r["consensus_components"] for r in rows
                                                        if r["stratum"] == s])),
            "mean_consensus_holes": float(np.mean([r["consensus_holes"] for r in rows
                                                   if r["stratum"] == s]))}
        for s in [spec["reference"], *spec["failure_strata"]]}
    report["exploratory"] = ("topology_member_spread AUROCs in `strata` are exploratory and "
                             "never enter the verdict")
    report["limits"] = [
        "fixture strata are only as independent as their construction; a fixture built from "
        "any member's output invalidates the ranking",
        "fixtures differing from verified-good surfaces in acquisition or region can be ranked "
        "by that difference rather than by topology",
        "units are patches, not independent specimens; intervals resample group_id blocks",
        "post-hoc only: no member is retrained and no learned geometric prior is added",
    ]
    return report


# --------------------------------------------------------------------------- CLI


def _write_create_only(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scroliq-topology-uncertainty", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="rank frozen structural failures by ensemble disagreement")
    ev.add_argument("--spec", type=Path, required=True)
    ev.add_argument("--out", type=Path, required=True, help="create-only JSON report")
    sub.add_parser("self-test", help="built-in synthetic controls; exits 1 if any fails")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            result = self_test()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["passed"] else 1
        report = evaluate(args.spec)
        _write_create_only(args.out, report)
        print(f"verdict {report['verdict']}; control fired: {report['positive_control']['fired']}")
        return 0
    except (TopologyUncertaintyError, EnsembleIndependenceError, OSError, ValueError) as exc:
        parser.exit(2, f"topology uncertainty refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
