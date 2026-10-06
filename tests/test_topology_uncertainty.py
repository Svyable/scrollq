import copy
import hashlib
import json

import numpy as np
import pytest

from scrollq import topology_uncertainty as tu
from scrollq.ensemble_independence import ANCESTRY_SCHEMA
from scrollq.topology_uncertainty import (
    TopologyUncertaintyError, decide, evaluate, main, positive_control, rank_units,
    unit_scores, validate_spec,
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_positive_control_fires_and_is_deterministic():
    a, b = positive_control(alpha=0.05), positive_control(alpha=0.05)
    assert a == b and a["fired"]
    assert a["confident_auroc_mi"] == 0.5
    assert a["disagreeing_auroc_confidence"] < 0.1  # confidence is inverted by the plant


def test_unit_scores_zero_disagreement_and_local_enrichment():
    p = np.full((4, 8, 8), 0.9)
    valid = np.ones((8, 8), bool)
    assert unit_scores(p, valid, None, 0.2)["mi"] == 0.0
    split = p.copy()
    split[::2, 3:5, :] = 0.05
    mask = np.zeros((8, 8), bool)
    mask[3:5, :] = True
    s = unit_scores(split, valid, mask, 0.2)
    assert s["mi"] > 0 and s["local_mi"] == 1.0


def test_unit_scores_count_a_planted_hole():
    field = np.ones((12, 12))
    field[5:7, 5:7] = 0.0
    p = np.broadcast_to(field, (3, 12, 12)).copy()
    s = unit_scores(p, np.ones((12, 12), bool), None, 0.5)
    assert s["consensus_holes"] == 1 and s["topology_member_spread"] == 0.0


def _rows(gain):
    rng = np.random.default_rng(1)
    rows = []
    for i in range(60):
        failure = i % 2
        rows.append({"unit_id": f"u{i}", "group_id": f"g{i // 2}",
                     "stratum": "fault" if failure else "ok",
                     "mi": rng.normal(gain * failure, 1.0),
                     "confidence": rng.normal(0, 1.0),
                     "topology_member_spread": 0.0})
    return rows


KW = dict(failure_strata=["fault"], reference="ok", min_class_count=5, seed=0,
          replicates=300, alpha=0.05)


def test_rank_units_promotes_real_gain_and_dismisses_none():
    strong = rank_units(_rows(4.0), **KW)
    assert decide(strong, ["fault"])["verdict"] == "PROMOTE"
    none = rank_units(_rows(0.0), **KW)
    out = decide(none, ["fault"])
    assert out["verdict"] == "DISMISS" and out["underpowered"] in (True, False)


def test_small_class_is_unverified_not_dismissed():
    rows = [r for r in _rows(4.0) if r["stratum"] == "ok" or r["unit_id"] in ("u1", "u3")]
    out = rank_units(rows, **KW)
    assert out["fault"]["status"] == "unverified"
    assert decide(out, ["fault"])["verdict"] == "UNVERIFIED"


def _write(tmp, units, p_for, *, scrolls=("train",), train_units=("blk-1",)):
    members = ["m0", "m1", "m2", "m3"]
    ancestry = {"schema": ANCESTRY_SCHEMA, "ensemble_id": "e", "declared_kind": "other",
                "purpose": "deep_ensemble_uncertainty", "members": [
                    {"member_id": m, "checkpoint_sha256": sha(m), "training_units": list(train_units),
                     "training_scroll_ids": list(scrolls), "init_seed": i, "data_order_seed": i,
                     "parents": [], "config_sha256": sha("arch")} for i, m in enumerate(members)]}
    arrays = {"members": np.array(members)}
    for u in units:
        arrays[f"p/{u['unit_id']}"] = p_for(u)
    np.savez(tmp / "pred.npz", **arrays)
    (tmp / "ancestry.json").write_text(json.dumps(ancestry))
    spec = {"schema": tu.SPEC_SCHEMA, "predictions": "pred.npz", "ancestry": "ancestry.json",
            "failure_strata": ["fault"], "reference_stratum": "ok", "alpha": 0.05,
            "persistence_floor": 0.2, "min_class_count": 5,
            "bootstrap": {"seed": 0, "replicates": 200}, "units": units}
    (tmp / "spec.json").write_text(json.dumps(spec))
    return tmp / "spec.json"


def _units(n=16):
    return [{"unit_id": f"w{i}", "group_id": f"b{i // 2}", "scroll_id": "eval",
             "stratum": "fault" if i % 2 else "ok"} for i in range(n)]


def _fields(u):
    p = np.full((4, 10, 10), 0.95)
    if u["stratum"] == "ok":
        p[:, :, :5] = 0.5  # aleatoric band: high entropy, members agree
    else:
        p[::2, 4:6, :] = 0.05
    return p


def test_evaluate_dismisses_when_confidence_ranks_equally_well(tmp_path):
    def same(u):
        p = np.full((4, 10, 10), 0.95)
        if u["stratum"] == "fault":
            p[::2, 4:6, :] = 0.05  # entropy of the mean rises with the split too
        return p
    report = evaluate(_write(tmp_path, _units(), same))
    assert report["verdict"] == "DISMISS"
    assert report["strata"]["pooled"]["auroc_confidence"]["estimate"] == 1.0


def test_evaluate_end_to_end_promotes_planted_disagreement(tmp_path):
    report = evaluate(_write(tmp_path, _units(), _fields))
    assert report["verdict"] == "PROMOTE" and report["promotional"] is False
    assert report["strata"]["pooled"]["auroc_mi"]["estimate"] == 1.0
    out = tmp_path / "r.json"
    assert main(["evaluate", "--spec", str(tmp_path / "spec.json"), "--out", str(out)]) == 0
    with pytest.raises(SystemExit) as refused:  # create-only output
        main(["evaluate", "--spec", str(tmp_path / "spec.json"), "--out", str(out)])
    assert refused.value.code == 2


def test_evaluate_refuses_training_overlap(tmp_path):
    with pytest.raises(TopologyUncertaintyError, match="overlaps"):
        evaluate(_write(tmp_path, _units(), _fields, train_units=("w3",)))
    with pytest.raises(TopologyUncertaintyError, match="training scrolls"):
        evaluate(_write(tmp_path, _units(), _fields, scrolls=("eval",)))


def test_evaluate_refuses_bad_probabilities_and_missing_arrays(tmp_path):
    def bad(u):
        p = _fields(u)
        p[0, 0, 0] = 1.5
        return p
    with pytest.raises(TopologyUncertaintyError, match=r"\[0, 1\]"):
        evaluate(_write(tmp_path, _units(), bad))
    units = _units()
    spec_path = _write(tmp_path, units, _fields)
    doc = json.loads(spec_path.read_text())
    doc["units"].append({"unit_id": "extra", "group_id": "bx", "scroll_id": "eval", "stratum": "ok"})
    spec_path.write_text(json.dumps(doc))
    with pytest.raises(TopologyUncertaintyError, match="missing array"):
        evaluate(spec_path)


def test_validate_spec_rejects_bad_strata():
    spec = json.loads(json.dumps({
        "schema": tu.SPEC_SCHEMA, "failure_strata": ["fault"], "reference_stratum": "ok",
        "alpha": 0.05, "persistence_floor": 0.2, "min_class_count": 5,
        "bootstrap": {"seed": 0, "replicates": 200},
        "units": [{"unit_id": "a", "group_id": "g", "scroll_id": "s", "stratum": "ok"}]}))
    assert validate_spec(spec)["reference"] == "ok"
    bad = copy.deepcopy(spec)
    bad["units"][0]["stratum"] = "mystery"
    with pytest.raises(TopologyUncertaintyError):
        validate_spec(bad)
    bad = copy.deepcopy(spec)
    bad["failure_strata"] = ["ok"]
    with pytest.raises(TopologyUncertaintyError):
        validate_spec(bad)


def test_self_test_passes():
    assert tu.self_test()["passed"]


def test_committed_synthetic_artifact_matches_a_rerun():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "artifacts" / "2026-10-07-topology-uncertainty-synthetic" / "self-test.json"
    assert json.loads(path.read_text()) == json.loads(json.dumps(tu.self_test()))
