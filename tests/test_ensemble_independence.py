import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scrollq import ensemble_independence as ei
from scrollq.ensemble_independence import (
    EnsembleIndependenceError, audit_ancestry, disagreement, evaluate, main,
    positive_control, rank_failures,
)

CONFIG = hashlib.sha256(b"architecture").hexdigest()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def member(mid, units, *, init=0, order=0, parents=(), config=CONFIG, scrolls=("train",),
           checkpoint=None, calibration=None):
    row = {"member_id": mid, "checkpoint_sha256": checkpoint or sha(mid),
           "training_units": list(units), "training_scroll_ids": list(scrolls),
           "init_seed": init, "data_order_seed": order,
           "parents": None if parents is None else list(parents), "config_sha256": config}
    if calibration is not None:
        row["calibration_units"] = calibration
    return row


def manifest(members, *, kind="other", purpose="independent_witnesses", **extra):
    return {"schema": ei.ANCESTRY_SCHEMA, "ensemble_id": "test", "declared_kind": kind,
            "purpose": purpose, "members": members, **extra}


def pool(n=100):
    return [f"block-{i:03d}" for i in range(n)]


def cv(k=5, *, init=7, order=7):
    units = pool()
    return [member(f"cv-{i}", [u for j, u in enumerate(units) if j % k != i], init=init, order=order)
            for i in range(k)]


def deep(k=5):
    return [member(f"deep-{i}", pool(), init=i, order=100 + i) for i in range(k)]


def disjoint(k=5):
    units = pool()
    size = len(units) // k
    return [member(f"sub-{i}", units[i * size:(i + 1) * size], init=i, order=100 + i) for i in range(k)]


# ----------------------------------------------------------------------------- ancestry


def test_cv_folds_are_one_witness_and_not_a_deep_ensemble():
    report = audit_ancestry(manifest(cv(), kind="cv_fold"))
    assert report["detected_regime"] == "cv_partition"
    assert report["mean_overlap_coefficient"] == pytest.approx(0.75)
    assert all(p["supervision"]["shared_units"] == 60 for p in report["pairs"])
    assert report["independent_witnesses"]["certified_count"] == 1
    assert report["independent_witnesses"]["upper_bound_count"] == 1
    assert report["status"] == "dependent"
    deep_verdict = report["deep_ensemble_uncertainty"]
    assert deep_verdict["status"] == "dependent"
    assert "cross-validation-folds-share-supervision" in deep_verdict["reasons"]
    assert "shared-lineage-seed-or-checkpoint" in deep_verdict["reasons"]
    assert all(p["init_seed"] == "shared" and p["data_order_seed"] == "shared" for p in report["pairs"])
    assert report["promotional"] is False


def test_deep_ensemble_is_valid_deep_ensemble_but_one_witness():
    report = audit_ancestry(manifest(deep(), kind="deep_ensemble", purpose="deep_ensemble_uncertainty"))
    assert report["detected_regime"] == "identical_full_set"
    assert report["status"] == "independent"
    # identical supervision: five seeds are five optimization samples, not five witnesses
    assert report["independent_witnesses"]["certified_count"] == 1
    assert report["independent_witnesses"]["status"] == "dependent"


def test_disjoint_subsets_are_witnesses_under_the_strict_rule():
    report = audit_ancestry(manifest(disjoint(), kind="independent_subsets"))
    assert report["detected_regime"] == "disjoint_subsets"
    assert report["status"] == "independent"
    assert report["independent_witnesses"]["certified_count"] == 5
    assert report["deep_ensemble_uncertainty"]["status"] == "dependent"


def test_two_fold_cv_is_independent_halves_not_a_partition_artifact():
    report = audit_ancestry(manifest(cv(2, init=1, order=1), kind="other"))
    assert report["detected_regime"] == "disjoint_subsets"


def test_partial_overlap_regime_and_bagging_like_sets():
    units = pool(10)
    members = [member("a", units[:7], init=1, order=1), member("b", units[3:], init=2, order=2),
               member("c", units[:4] + units[8:], init=3, order=3)]
    assert audit_ancestry(manifest(members))["detected_regime"] == "partial_overlap"


def test_exact_witness_count_is_a_maximum_independent_subset_not_a_pair_count():
    # m3 overlaps every other member; the other three are mutually disjoint.
    members = [member("m0", ["1", "2"], init=0, order=0), member("m1", ["3", "4"], init=1, order=1),
               member("m2", ["5", "6"], init=2, order=2), member("m3", ["1", "3", "5"], init=3, order=3)]
    report = audit_ancestry(manifest(members))
    assert report["independent_witnesses"]["certified_count"] == 3
    assert report["status"] == "dependent"


def test_unknown_seed_never_certifies_independence():
    members = disjoint()
    members[0]["init_seed"] = None
    report = audit_ancestry(manifest(members))
    assert report["status"] == "unverified"
    assert report["independent_witnesses"]["certified_count"] < 5
    assert report["independent_witnesses"]["upper_bound_count"] == 5
    assert {p["witness_independence"] for p in report["pairs"] if "sub-0" in (p["a"], p["b"])} == {"unverified"}


def test_unknown_parents_and_missing_config_are_unknown():
    members = disjoint()
    members[1]["parents"] = None
    assert audit_ancestry(manifest(members))["status"] == "unverified"
    members = deep()
    members[2]["config_sha256"] = None
    report = audit_ancestry(manifest(members, purpose="deep_ensemble_uncertainty", kind="deep_ensemble"))
    assert report["status"] == "unverified"


def test_shared_pretrained_parent_is_dependent():
    parent = sha("pretrained-backbone")
    members = [member(f"m{i}", [f"u{i}"], init=i, order=i, parents=[parent]) for i in range(3)]
    report = audit_ancestry(manifest(members))
    assert {p["lineage"] for p in report["pairs"]} == {"shared"}
    assert report["independent_witnesses"]["certified_count"] == 1


def test_transitive_and_member_parent_lineage_is_shared():
    root, mid = sha("root"), sha("mid")
    members = [member("a", ["1"], init=1, order=1, parents=[root], checkpoint=mid),
               member("b", ["2"], init=2, order=2, parents=[mid]),
               member("c", ["3"], init=3, order=3, parents=[])]
    report = audit_ancestry(manifest(members))
    lineage = {(p["a"], p["b"]): p["lineage"] for p in report["pairs"]}
    assert lineage[("a", "b")] == "shared"
    assert lineage[("a", "c")] == lineage[("b", "c")] == "distinct"
    # b descends from a, which descends from root; c declares no ancestry at all
    members[2]["parents"] = [root]
    lineage = {(p["a"], p["b"]): p["lineage"] for p in audit_ancestry(manifest(members))["pairs"]}
    assert lineage[("a", "c")] == lineage[("b", "c")] == "shared"


@pytest.mark.parametrize("cycle", ["self", "loop"])
def test_lineage_cycles_are_refused(cycle):
    a, b = sha("a"), sha("b")
    members = [member("a", ["1"], parents=[a if cycle == "self" else b], checkpoint=a),
               member("b", ["2"], parents=[a], checkpoint=b)]
    with pytest.raises(EnsembleIndependenceError, match="cycle"):
        audit_ancestry(manifest(members))


def test_identical_checkpoint_bytes_count_once():
    twin = sha("same-bytes")
    members = [member("a", ["1"], init=1, order=1, checkpoint=twin),
               member("b", ["2"], init=2, order=2, checkpoint=twin)]
    pair = audit_ancestry(manifest(members))["pairs"][0]
    assert pair["identical_checkpoint"] is True
    assert pair["witness_independence"] == "dependent"


def test_equal_seeds_do_not_imply_equal_initialization_across_architectures():
    members = [member("a", ["1"], init=5, order=1, config=sha("net-a")),
               member("b", ["2"], init=5, order=2, config=sha("net-b"))]
    assert audit_ancestry(manifest(members))["pairs"][0]["init_seed"] == "distinct"


def test_overlap_threshold_is_strict_and_frozen_in_the_manifest():
    def build(threshold):
        members = [member("a", ["1", "2", "3", "4"], init=1, order=1),
                   member("b", ["3", "4", "5", "6"], init=2, order=2)]
        return audit_ancestry(manifest(members, max_overlap=threshold))
    assert build(0.5)["status"] == "independent"
    assert build(0.49)["status"] == "dependent"
    assert build(0.0)["pairs"][0]["supervision"]["overlap_coefficient"] == 0.5


def test_unit_weights_change_overlap_but_not_regime():
    members = [member("a", ["1", "2"], init=1, order=1), member("b", ["2", "3"], init=2, order=2)]
    plain = audit_ancestry(manifest(members))["pairs"][0]["supervision"]
    heavy = audit_ancestry(manifest(members, unit_weights={"1": 1, "2": 9, "3": 1}))["pairs"][0]["supervision"]
    assert plain["overlap_coefficient"] == 0.5
    assert heavy["overlap_coefficient"] == pytest.approx(0.9)
    assert heavy["shared_units"] == plain["shared_units"] == 1


def test_declared_kind_contradicting_inventory_is_never_independent():
    # honest disjoint subsets mislabelled as CV: downgraded, not silently accepted
    report = audit_ancestry(manifest(disjoint(), kind="cv_fold"))
    assert report["declared_kind_consistent"] is False
    assert report["status"] == "unverified"
    assert "declared-kind-contradicts-inventory" in report["reasons"]
    # CV folds claimed as a deep ensemble: the central failure mode
    report = audit_ancestry(manifest(cv(), kind="deep_ensemble", purpose="deep_ensemble_uncertainty"))
    assert report["status"] == "dependent"
    assert report["declared_kind_consistent"] is False


def test_single_member_is_unverified():
    report = audit_ancestry(manifest([member("only", ["1"])]))
    assert report["status"] == "unverified"
    assert report["detected_regime"] is None


def test_report_is_deterministic_and_strict_json():
    document = manifest(cv(), kind="cv_fold")
    first = audit_ancestry(copy.deepcopy(document))
    assert first == audit_ancestry(copy.deepcopy(document))
    json.dumps(first, allow_nan=False)


@pytest.mark.parametrize("mutation", [
    "schema", "purpose", "kind", "dup_member", "dup_unit", "bad_sha", "missing_seed_key",
    "bool_seed", "negative_seed", "empty_units", "empty_scrolls", "too_many", "bad_overlap",
    "weights_missing", "weight_zero", "parents_not_list", "no_members",
])
def test_fail_closed_on_invalid_manifest(mutation):
    document = manifest(disjoint())
    members = document["members"]
    if mutation == "schema":
        document["schema"] = "other"
    elif mutation == "purpose":
        document["purpose"] = "vibes"
    elif mutation == "kind":
        document["declared_kind"] = "bagging"
    elif mutation == "dup_member":
        members[1]["member_id"] = members[0]["member_id"]
    elif mutation == "dup_unit":
        members[0]["training_units"].append(members[0]["training_units"][0])
    elif mutation == "bad_sha":
        members[0]["checkpoint_sha256"] = "ABC"
    elif mutation == "missing_seed_key":
        del members[0]["init_seed"]
    elif mutation == "bool_seed":
        members[0]["data_order_seed"] = True
    elif mutation == "negative_seed":
        members[0]["init_seed"] = -1
    elif mutation == "empty_units":
        members[0]["training_units"] = []
    elif mutation == "empty_scrolls":
        members[0]["training_scroll_ids"] = []
    elif mutation == "too_many":
        document["members"] = [member(f"m{i}", [f"u{i}"]) for i in range(ei.MAX_MEMBERS + 1)]
    elif mutation == "bad_overlap":
        document["max_overlap"] = 1.0
    elif mutation == "weights_missing":
        document["unit_weights"] = {"block-000": 1}
    elif mutation == "weight_zero":
        document["unit_weights"] = {u: 0 for m in members for u in m["training_units"]}
    elif mutation == "parents_not_list":
        members[0]["parents"] = "abc"
    else:
        document["members"] = []
    with pytest.raises(EnsembleIndependenceError):
        audit_ancestry(document)


# ----------------------------------------------------------------------------- metrics


def test_disagreement_known_values():
    mi, total = disagreement(np.array([[0.1], [0.9]]))
    h = lambda p: -(p * np.log2(p) + (1 - p) * np.log2(1 - p))  # noqa: E731
    assert total[0] == pytest.approx(1.0)
    assert mi[0] == pytest.approx(1.0 - h(0.1))
    agree, _ = disagreement(np.array([[0.3], [0.3], [0.3]]))
    assert agree[0] == pytest.approx(0.0, abs=1e-12)
    sure, entropy = disagreement(np.array([[0.0, 1.0], [0.0, 1.0]]))
    assert np.all(np.isfinite(sure)) and np.allclose(entropy, 0.0)


def test_exactly_agreeing_members_have_exactly_zero_disagreement():
    # float residue from mean-of-identical-values must not break ties among agreeing units
    values = np.random.default_rng(0).random(500)
    probabilities = np.tile(values, (3, 1))
    assert np.array_equal(disagreement(probabilities)[0], np.zeros(500))


def test_auroc_with_ties_and_degenerate_classes():
    score = np.array([0.1, 0.4, 0.4, 0.9])
    failure = np.array([0, 0, 1, 1])
    assert ei._auroc(score, failure) == pytest.approx(0.875)
    assert ei._auroc(score, failure * 0 + 1) != ei._auroc(score, failure * 0 + 1)  # nan


def test_aurc_is_independent_of_unit_order_under_ties():
    score = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0])
    failure = np.array([1, 0, 0, 1, 0, 1])
    order = np.random.default_rng(3).permutation(len(score))
    assert ei._aurc(score, failure) == pytest.approx(ei._aurc(score[order], failure[order]))
    perfect = ei._aurc(np.array([0.0, 0.1, 0.8, 0.9]), np.array([0, 0, 1, 1]))
    worst = ei._aurc(np.array([0.9, 0.8, 0.1, 0.0]), np.array([0, 0, 1, 1]))
    assert perfect < worst


# ----------------------------------------------------------------------------- failure ranking


KW = dict(threshold=0.5, strata=["negative_papyrus", "supported_ink"], min_class_count=5,
          seed=0, replicates=200, alpha=0.05)


def test_planted_disagreement_ranks_failures_and_agreeing_errors_do_not():
    units, panel = ei._synthetic_panel(11)
    result = rank_failures(units, panel, **KW)
    deep_pooled = result["ensembles"]["b"][ei.POOLED]
    folds_pooled = result["ensembles"]["a"][ei.POOLED]
    assert deep_pooled["decision"] == "ranks_failures"
    assert deep_pooled["auroc_mutual_information"]["estimate"] > 0.9
    assert deep_pooled["incremental_over_confidence"] is True
    assert folds_pooled["decision"] == "not_distinguished_from_chance"
    assert folds_pooled["incremental_over_confidence"] is False
    assert result["comparison_a_minus_b"][ei.POOLED]["decision"] == "b_exceeds_a"
    # the folds fail just as often; they simply fail in agreement
    assert folds_pooled["n_failure"] > 0.15 * folds_pooled["n"]


def test_frozen_decision_threshold_defines_failure():
    units = [{"unit_id": f"u{i}", "group_id": f"g{i}", "scroll_id": "s", "stratum": "x", "truth": t}
             for i, t in enumerate([0, 0, 1, 1])]
    probabilities = {"a": np.tile([0.6, 0.6, 0.6, 0.9], (2, 1))}
    options = dict(strata=["x"], min_class_count=1, seed=0, replicates=100, alpha=0.05)
    low = rank_failures(units, probabilities, threshold=0.5, **options)["ensembles"]["a"][ei.POOLED]
    high = rank_failures(units, probabilities, threshold=0.7, **options)["ensembles"]["a"][ei.POOLED]
    assert (low["n_failure"], high["n_failure"]) == (2, 1)


def test_rank_failures_is_deterministic_and_seed_sensitive_only_in_intervals():
    units, panel = ei._synthetic_panel(11)
    first = rank_failures(units, panel, **KW)
    assert first == rank_failures(units, panel, **KW)
    other = rank_failures(units, panel, **{**KW, "seed": 1})
    key = ("ensembles", "b", ei.POOLED, "auroc_mutual_information")
    get = lambda r: r[key[0]][key[1]][key[2]][key[3]]  # noqa: E731
    assert get(first)["estimate"] == get(other)["estimate"]
    assert get(first)["ci"] != get(other)["ci"]


def test_small_failure_classes_are_unverified_not_measured():
    units, panel = ei._synthetic_panel(11)
    result = rank_failures(units, panel, **{**KW, "min_class_count": 200})
    for ensemble in result["ensembles"].values():
        assert ensemble[ei.POOLED]["status"] == "unverified"
        assert "decision" not in ensemble[ei.POOLED]


def test_block_bootstrap_resamples_physical_groups_not_units():
    units, panel = ei._synthetic_panel(11)
    one_block = [{**u, "group_id": "same"} for u in units]
    result = rank_failures(one_block, panel, **KW)
    # a single physical block cannot support an interval: every resample is identical
    ci = result["ensembles"]["b"][ei.POOLED]["auroc_mutual_information"]["ci"]
    assert ci[0] == ci[1]


def test_positive_control_fires_and_fails_closed_under_mutations(monkeypatch):
    control = positive_control(alpha=0.05)
    assert control["fired"] is True
    assert control["null_false_detection_rate"] <= ei.MAX_NULL_FALSE_DETECTION_RATE
    monkeypatch.setattr(ei, "_auroc", lambda score, failure: 0.5)  # a gate that detects nothing
    assert positive_control(alpha=0.05)["fired"] is False
    monkeypatch.setattr(ei, "_auroc", lambda score, failure: 1.0)  # a gate that detects everything
    assert positive_control(alpha=0.05)["fired"] is False


def test_control_is_not_fired_by_a_gate_that_manufactures_signal_on_the_null(monkeypatch):
    real = ei.rank_failures
    calls = []

    def leaky(*args, **kwargs):
        result = real(*args, **kwargs)
        calls.append(1)
        if len(calls) > 1:  # every permuted-null call "detects" failure ranking
            for entry in result["ensembles"].values():
                entry[ei.POOLED]["decision"] = "ranks_failures"
        return result

    monkeypatch.setattr(ei, "rank_failures", leaky)
    control = positive_control(alpha=0.05)
    assert control["planted_disagreement_detected"] and control["agreeing_errors_not_ranked"]
    assert control["null_false_detection_rate"] == 1.0
    assert control["fired"] is False


def test_pair_agreement_dose_response_and_symmetric_cv_unverified():
    members = [member(f"m{i}", [f"u{j}" for j in range(i, i + 6)], init=i, order=i) for i in range(4)]
    report = audit_ancestry(manifest(members))
    # members with more shared supervision agree more: a fold-membership signature
    rng = np.random.default_rng(0)
    base = rng.random(40)
    probs = np.array([np.clip(base + 0.05 * (i + 1) * rng.normal(size=40), 0, 1) for i in range(4)])
    result = ei._pair_agreement(report, [f"m{i}" for i in range(4)], probs)
    assert result["status"] == "measured_descriptive_only"
    assert -1.0 <= result["spearman_overlap_vs_mean_abs_difference"] <= 1.0
    symmetric = audit_ancestry(manifest(cv()))
    result = ei._pair_agreement(symmetric, [m["member_id"] for m in cv()], np.tile(base[:10], (5, 1)))
    assert result["status"] == "unverified"


# ----------------------------------------------------------------------------- evaluate / CLI


@pytest.fixture(scope="module")
def cached_control():
    return positive_control(alpha=0.05)


@pytest.fixture
def workspace(tmp_path, monkeypatch, cached_control):
    """A frozen spec, two ancestry manifests and predictions for the planted panel."""
    monkeypatch.setattr(ei, "positive_control", lambda *, alpha: dict(cached_control))
    units, panel = ei._synthetic_panel(5)
    for u in units:
        u["scroll_id"] = "heldout-scroll"
    members = {"a": cv(), "b": deep()}
    for name, kind, purpose in (("a", "cv_fold", "independent_witnesses"),
                                ("b", "deep_ensemble", "deep_ensemble_uncertainty")):
        (tmp_path / f"ancestry-{name}.json").write_text(
            json.dumps(manifest(members[name], kind=kind, purpose=purpose)))
    order = np.random.default_rng(1).permutation(5)  # predictions stored in a different member order
    unit_order = np.random.default_rng(2).permutation(len(units))
    arrays = {"unit_ids": np.array([units[i]["unit_id"] for i in unit_order])}
    for name in "ab":
        ids = [m["member_id"] for m in members[name]]
        arrays[name] = panel[name][np.ix_(order, unit_order)]
        arrays[f"{name}_members"] = np.array([ids[i] for i in order])
    np.savez(tmp_path / "predictions.npz", **arrays)
    spec = {"schema": ei.SPEC_SCHEMA, "predictions": "predictions.npz",
            "strata": ["negative_papyrus", "supported_ink"], "decision_threshold": 0.5,
            "alpha": 0.05, "min_class_count": 5, "bootstrap": {"seed": 0, "replicates": 200},
            "ensembles": {
                "a": {"label": "cv_folds", "ancestry": "ancestry-a.json", "expected_regime": "cv_partition"},
                "b": {"label": "independent_seeds", "ancestry": "ancestry-b.json",
                      "expected_regime": "identical_full_set"}},
            "units": units}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    return tmp_path, spec, path


def rewrite(path, spec):
    path.write_text(json.dumps(spec))


def test_evaluate_end_to_end_answers_the_proof_question(workspace):
    _, _, path = workspace
    report = evaluate(path)
    assert report["status"] == "measured"
    assert report["promotional"] is False
    assert report["proof_question"] == ei.PROOF_QUESTION
    assert report["ancestry"]["a"]["detected_regime"] == "cv_partition"
    assert report["ancestry"]["a"]["independent_witnesses"]["certified_count"] == 1
    assert report["ancestry"]["b"]["status"] == "independent"
    assert report["ensembles"]["b"][ei.POOLED]["decision"] == "ranks_failures"
    assert report["ensembles"]["a"][ei.POOLED]["decision"] == "not_distinguished_from_chance"
    assert report["comparison_a_minus_b"][ei.POOLED]["decision"] == "b_exceeds_a"
    assert report["design"]["same_architecture"] is True
    assert report["pair_agreement_vs_overlap"]["a"]["status"] == "unverified"
    assert set(report["sha256"]) == {"spec", "predictions", "ancestry_a", "ancestry_b"}
    json.dumps(report, allow_nan=False)


def test_predictions_are_aligned_by_identifier_not_position(tmp_path):
    # Ensemble-level scores are member-order invariant, so alignment is checked at the loader:
    # rows must follow the ancestry member order and columns the spec unit order.
    rows = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    np.savez(tmp_path / "p.npz", unit_ids=np.array(["u2", "u0", "u1"]), a=rows,
             a_members=np.array(["m1", "m0"]))
    loaded = ei._load_probabilities(tmp_path / "p.npz", "a", ["m0", "m1"], ["u0", "u1", "u2"])
    assert loaded.tolist() == [[0.5, 0.6, 0.4], [0.2, 0.3, 0.1]]
    with pytest.raises(EnsembleIndependenceError):
        ei._load_probabilities(tmp_path / "p.npz", "a", ["m0", "mX"], ["u0", "u1", "u2"])


def test_unfired_control_withholds_every_verdict(workspace, monkeypatch):
    _, _, path = workspace
    monkeypatch.setattr(ei, "positive_control", lambda *, alpha: {"fired": False})
    report = evaluate(path)
    assert report["status"] == "unverified"
    assert "ensembles" not in report and "comparison_a_minus_b" not in report


def test_unestablished_architecture_equality_makes_comparison_unverified(workspace):
    root, spec, path = workspace
    document = json.loads((root / "ancestry-b.json").read_text())
    for m in document["members"]:
        m["config_sha256"] = sha("different-net")
    (root / "ancestry-b.json").write_text(json.dumps(document))
    report = evaluate(path)
    assert report["design"]["same_architecture"] is False
    assert {c["status"] for c in report["comparison_a_minus_b"].values()} == {"unverified"}
    assert report["ensembles"]["b"][ei.POOLED]["decision"] == "ranks_failures"  # still reported per ensemble


@pytest.mark.parametrize("mutation", [
    "unit_in_training", "group_in_training", "scroll_in_training", "calibration_overlap",
    "wrong_regime", "unequal_size", "missing_array", "extra_unit", "bad_probability",
    "member_mismatch", "bad_stratum", "bad_truth", "few_replicates", "path_escape", "reserved_stratum",
    "dup_unit", "bad_threshold",
])
def test_evaluate_refuses_leakage_and_invalid_inputs(workspace, mutation):
    root, spec, path = workspace
    ancestry_a = json.loads((root / "ancestry-a.json").read_text())
    if mutation == "unit_in_training":
        ancestry_a["members"][0]["training_units"].append(spec["units"][0]["unit_id"])
    elif mutation == "group_in_training":
        ancestry_a["members"][0]["training_units"].append(spec["units"][0]["group_id"])
    elif mutation == "scroll_in_training":
        ancestry_a["members"][0]["training_scroll_ids"].append("heldout-scroll")
    elif mutation == "calibration_overlap":
        ancestry_a["members"][0]["calibration_units"] = [spec["units"][3]["unit_id"]]
    elif mutation == "wrong_regime":
        spec["ensembles"]["b"]["expected_regime"] = "cv_partition"
    elif mutation == "unequal_size":
        ancestry_b = json.loads((root / "ancestry-b.json").read_text())
        ancestry_b["members"].pop()
        (root / "ancestry-b.json").write_text(json.dumps(ancestry_b))
    elif mutation in ("missing_array", "extra_unit", "bad_probability", "member_mismatch"):
        with np.load(root / "predictions.npz") as data:
            arrays = {k: data[k] for k in data.files}
        if mutation == "missing_array":
            del arrays["b_members"]
        elif mutation == "extra_unit":
            arrays["unit_ids"] = np.append(arrays["unit_ids"][1:], "unit-not-in-spec")
        elif mutation == "bad_probability":
            arrays["a"][0, 0] = 1.5
        else:
            arrays["a_members"] = np.array([f"other-{i}" for i in range(5)])
        np.savez(root / "predictions.npz", **arrays)
    elif mutation == "bad_stratum":
        spec["units"][0]["stratum"] = "somewhere-else"
    elif mutation == "bad_truth":
        spec["units"][0]["truth"] = True
    elif mutation == "few_replicates":
        spec["bootstrap"]["replicates"] = 10
    elif mutation == "path_escape":
        spec["predictions"] = "../predictions.npz"
    elif mutation == "reserved_stratum":
        spec["strata"].append(ei.POOLED)
    elif mutation == "dup_unit":
        spec["units"][1]["unit_id"] = spec["units"][0]["unit_id"]
    else:
        spec["decision_threshold"] = 1.0
    (root / "ancestry-a.json").write_text(json.dumps(ancestry_a))
    rewrite(path, spec)
    with pytest.raises(EnsembleIndependenceError):
        evaluate(path)


def test_cli_help_needs_no_network_or_arguments(capsys):
    for argv in (["--help"], ["ancestry", "--help"], ["evaluate", "--help"], ["self-test", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0
    assert "ancestry" in capsys.readouterr().out


def test_cli_ancestry_gate_exit_codes_and_create_only(tmp_path, capsys):
    cv_path, sub_path = tmp_path / "cv.json", tmp_path / "sub.json"
    cv_path.write_text(json.dumps(manifest(cv(), kind="cv_fold")))
    sub_path.write_text(json.dumps(manifest(disjoint(), kind="independent_subsets")))
    assert main(["ancestry", "--manifest", str(cv_path), "--out", str(tmp_path / "cv-report.json")]) == 0
    assert "1 of 5 members certified" in capsys.readouterr().out
    assert main(["ancestry", "--manifest", str(sub_path), "--out", str(tmp_path / "sub-report.json"),
                 "--fail-unless-independent"]) == 0
    with pytest.raises(SystemExit) as exc:  # create-only
        main(["ancestry", "--manifest", str(cv_path), "--out", str(tmp_path / "cv-report.json")])
    assert exc.value.code == 2
    assert main(["ancestry", "--manifest", str(cv_path), "--out", str(tmp_path / "gate.json"),
                 "--fail-unless-independent"]) == 1
    assert json.loads((tmp_path / "cv-report.json").read_text())["promotional"] is False


def test_cli_refuses_bad_manifest_with_exit_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit) as exc:
        main(["ancestry", "--manifest", str(bad), "--out", str(tmp_path / "out.json")])
    assert exc.value.code == 2
    assert not (tmp_path / "out.json").exists()


def test_cli_evaluate_and_self_test(workspace, capsys):
    root, _, path = workspace
    assert main(["evaluate", "--spec", str(path), "--out", str(root / "report.json")]) == 0
    assert json.loads((root / "report.json").read_text())["status"] == "measured"
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", "--spec", str(path), "--out", str(root / "report.json")])
    assert exc.value.code == 2
    capsys.readouterr()
    assert main(["self-test"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_committed_synthetic_artifact_matches_a_fresh_self_test():
    root = Path(__file__).resolve().parents[1] / "artifacts" / "2026-10-06-ensemble-independence-synthetic"
    committed = json.loads((root / "self-test.json").read_text())
    fresh = ei.self_test()
    assert committed["passed"] is True and fresh["passed"] is True
    assert committed["checks"] == fresh["checks"]
    for key in ("planted_disagreement_detected", "agreeing_errors_not_ranked", "fired", "null_trials"):
        assert committed["control"][key] == fresh["control"][key]
    for key in ("independent_auroc_mutual_information", "agreeing_auroc_mutual_information",
                "null_false_detection_rate"):
        assert committed["control"][key] == pytest.approx(fresh["control"][key], abs=0.02)
    readme = (root / "README.md").read_text()
    assert hashlib.sha256((root / "self-test.json").read_bytes()).hexdigest() in readme
    assert "Synthetic only" in readme
