"""Threshold-persistence audit: manifest, measurement, model, and decision rule."""

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scrollq import persistence_audit as pa
from scrollq import persistence_controls as pc

ROOT = Path(__file__).resolve().parents[1]
PINNED_SPEC_SHA256 = "31e22a9153463dd514dbffecfaa458a990ea331a7717a49d66326ef1e3699b26"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------- the spec


def test_frozen_spec_hash_is_a_pinned_literal_not_derived_from_the_spec():
    assert pa.FROZEN_SPEC_SHA256 == PINNED_SPEC_SHA256
    assert pa.canonical_sha256(pa.SPEC) == PINNED_SPEC_SHA256


def test_committed_spec_artifact_matches_the_code():
    committed = json.loads((ROOT / "artifacts/2026-10-05-threshold-persistence-prereg/spec.json").read_text())
    assert committed == pa.SPEC


def test_any_changed_spec_is_not_preregistered():
    spec = copy.deepcopy(pa.SPEC)
    spec["decision"]["min_mean_gain"] = 0.01
    assert pa.canonical_sha256(spec) != pa.FROZEN_SPEC_SHA256


# ------------------------------------------------------------------- manifest


def _valid_manifest():
    sha = "a" * 64
    return {
        "schema_version": 1,
        "protocol": pa.PROTOCOL,
        "selection_contract": dict(pa._CONTRACT),
        "detector": {
            "name": "frozen-detector",
            "checkpoint_sha256": sha,
            "inference_config_sha256": sha,
            "training_domains": ["scroll-A"],
        },
        "regions": [
            {
                "id": "r1", "domain": "fragment-1", "kind": "verified_ink",
                "prediction": "p.npy", "prediction_sha256": sha,
                "labels": "l.npy", "labels_sha256": sha, "nominal_threshold": 0.5,
            },
            {
                "id": "r2", "domain": "fragment-1", "kind": "blank_papyrus",
                "prediction": "q.npy", "prediction_sha256": sha, "nominal_threshold": 0.5,
            },
        ],
    }


def test_valid_manifest_normalises():
    out = pa.validate_manifest(_valid_manifest())
    assert [r["id"] for r in out["regions"]] == ["r1", "r2"]
    assert out["detector"]["training_domains"] == ["scroll-A"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda m: m.update(schema_version=2), "schema_version"),
        (lambda m: m.update(protocol="other"), "protocol"),
        (lambda m: m["selection_contract"].update(nominal_thresholds_declared_before_measurement=False), "declared_before"),
        (lambda m: m["selection_contract"].update(topology_used_to_choose_threshold=True), "topology_used"),
        (lambda m: m["selection_contract"].update(ocr_or_text_used_to_choose_regions_or_thresholds=True), "ocr_or_text"),
        (lambda m: m["selection_contract"].update(detector_trained_on_evaluation_domains=True), "detector_trained"),
        (lambda m: m.pop("selection_contract"), "selection_contract"),
        (lambda m: m["detector"].update(checkpoint_sha256="xyz"), "checkpoint_sha256"),
        (lambda m: m["detector"].update(training_domains="scroll-A"), "training_domains"),
        (lambda m: m["detector"]["training_domains"].append("fragment-1"), "training_domains"),
        (lambda m: m["regions"][1].update(id="r1"), "duplicate"),
        (lambda m: m["regions"][0].update(kind="mystery"), "kind"),
        (lambda m: m["regions"][0].update(nominal_threshold=1.0), "nominal_threshold"),
        (lambda m: m["regions"][0].update(nominal_threshold=True), "nominal_threshold"),
        (lambda m: m["regions"][0].pop("labels"), "labels"),
        (lambda m: m["regions"][0].update(prediction_sha256="short"), "prediction_sha256"),
        (lambda m: m.update(regions=[]), "regions"),
    ],
)
def test_manifest_fails_closed(mutate, message):
    manifest = _valid_manifest()
    mutate(manifest)
    with pytest.raises(pa.AuditError, match=message):
        pa.validate_manifest(manifest)


def test_manifest_paths_cannot_escape_the_manifest_directory(tmp_path):
    with pytest.raises(pa.AuditError, match="escapes"):
        pa._resolve_under(tmp_path, "../elsewhere.npy", "x")


# ------------------------------------------------------- invariance + labelling


def test_invariance_check_passes_and_reports_non_injective_remaps():
    values = np.random.default_rng(0).random((64, 64))
    valid = np.ones(values.shape, dtype=bool)
    lv = pa.ps.dense_levels(values, valid)
    ok = pa.invariance_check(values, valid, 0.5, lv, pa.ps.nominal_level(lv, 0.5), ["cube", "expm1_3x"])
    assert ok["ok"] and {r["status"] for r in ok["remaps"]} == {"identical"}

    tiny = np.full((64, 64), 0.4)
    tiny[0, :4] = [1e-110, 2e-110, 3e-110, 4e-110]  # their cubes underflow to zero
    lv = pa.ps.dense_levels(tiny, valid)
    mixed = pa.invariance_check(tiny, valid, 0.3, lv, pa.ps.nominal_level(lv, 0.3), ["cube", "expm1_3x"])
    statuses = {r["remap"]: r["status"] for r in mixed["remaps"]}
    assert statuses == {"cube": "not_injective", "expm1_3x": "identical"}
    assert mixed["ok"]  # one conclusive remap, none that differ

    only_bad = pa.invariance_check(tiny, valid, 0.3, lv, pa.ps.nominal_level(lv, 0.3), ["cube"])
    assert not only_bad["ok"]  # nothing conclusive is not a pass


def _three_bars():
    f = np.zeros((64, 64))
    f[10:15, 5:35] = 0.9   # ink
    f[40:45, 5:35] = 0.9   # clear false positive
    f[17:22, 5:35] = 0.9   # 2 px from the ink: inside the clear margin, no overlap
    ink = np.zeros((64, 64), dtype=np.uint8)
    ink[9:16, 4:36] = 1
    return f, ink


def test_measure_region_labels_ink_false_positive_and_ambiguous():
    f, ink = _three_bars()
    out = pa.measure_region(f, np.ones(f.shape, dtype=bool), ink, 0.5, "verified_ink")
    labels = sorted((r["peak_yx"][0], r["label"], r["negative_kind"]) for r in out["components"])
    assert labels == [(10, 1, None), (40, 0, pa.IN_REGION_NEGATIVE)]
    assert out["summary"]["n_ambiguous"] == 1
    assert out["summary"]["n_positive"] == 1 and out["summary"]["n_negative"] == 1


def test_non_ink_regions_label_every_component_negative_with_the_region_kind():
    f, _ = _three_bars()
    out = pa.measure_region(f, np.ones(f.shape, dtype=bool), None, 0.5, "crack")
    assert {r["label"] for r in out["components"]} == {0}
    assert {r["negative_kind"] for r in out["components"]} == {"crack"}
    assert out["summary"]["n_negative"] == 3


def test_measure_region_refuses_bad_inputs():
    f, ink = _three_bars()
    valid = np.ones(f.shape, dtype=bool)
    with pytest.raises(pa.AuditError, match="need labels"):
        pa.measure_region(f, valid, None, 0.5, "verified_ink")
    with pytest.raises(pa.AuditError, match="must not contain ink"):
        pa.measure_region(f, valid, ink, 0.5, "blank_papyrus")
    with pytest.raises(pa.AuditError, match="min_valid_pixels"):
        pa.measure_region(f[:10, :10], np.ones((10, 10), dtype=bool), None, 0.5, "fold")
    with pytest.raises(pa.AuditError, match="nominal_threshold"):
        pa.measure_region(f, valid, None, 1.5, "fold")
    with pytest.raises(pa.AuditError, match="unknown region kind"):
        pa.measure_region(f, valid, None, 0.5, "mystery")


def test_region_with_nothing_above_threshold_has_no_components():
    out = pa.measure_region(np.full((64, 64), 0.1), np.ones((64, 64), dtype=bool), None, 0.5, "blank_papyrus")
    assert out["components"] == [] and out["summary"]["nominal_level"] is None


# ----------------------------------------------------------- measure (file I/O)


def _write_region(tmp_path, name, field, ink=None):
    pred = tmp_path / f"{name}.npy"
    np.save(pred, field.astype(np.float32))
    entry = {"prediction": pred.name, "prediction_sha256": _sha(pred)}
    if ink is not None:
        lab = tmp_path / f"{name}.labels.npy"
        np.save(lab, ink.astype(np.uint8))
        entry.update(labels=lab.name, labels_sha256=_sha(lab))
    return entry


def _manifest_on_disk(tmp_path):
    f, ink = _three_bars()
    sha = "b" * 64
    manifest = {
        "schema_version": 1,
        "protocol": pa.PROTOCOL,
        "selection_contract": dict(pa._CONTRACT),
        "detector": {"name": "d", "checkpoint_sha256": sha, "inference_config_sha256": sha,
                     "training_domains": ["scroll-A"]},
        "regions": [
            {"id": "ink", "domain": "frag-1", "kind": "verified_ink", "nominal_threshold": 0.5,
             **_write_region(tmp_path, "ink", f, ink)},
            {"id": "blank", "domain": "frag-1", "kind": "blank_papyrus", "nominal_threshold": 0.5,
             **_write_region(tmp_path, "blank", np.where(f > 0, 0.9, 0.0))},
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_measure_manifest_end_to_end_binds_hashes_and_overlay(tmp_path):
    path, _ = _manifest_on_disk(tmp_path)
    doc = pa.measure_manifest(path, overlay_dir=tmp_path / "overlays")
    assert doc["preregistered"] is True
    assert doc["spec_sha256"] == pa.FROZEN_SPEC_SHA256
    assert all(r["status"] == "ok" for r in doc["regions"])
    assert doc["regions"][0]["inputs"]["prediction_sha256"] == _sha(tmp_path / "ink.npy")
    assert {c["region"] for c in doc["components"]} == {"ink", "blank"}
    overlay = np.load(tmp_path / "overlays" / "ink.persistence-margin.npy")
    assert overlay.shape == (64, 64) and np.isfinite(overlay).sum() > 0


def test_a_hash_mismatch_fails_the_region_instead_of_dropping_it(tmp_path):
    path, manifest = _manifest_on_disk(tmp_path)
    np.save(tmp_path / "blank.npy", np.zeros((64, 64), dtype=np.float32))  # content changed after hashing
    doc = pa.measure_manifest(path)
    failed = [r for r in doc["regions"] if r["status"] != "ok"]
    assert [r["id"] for r in failed] == ["blank"]
    assert "SHA-256 mismatch" in failed[0]["reason"]


def test_evaluate_refuses_a_run_with_failed_regions(tmp_path):
    path, _ = _manifest_on_disk(tmp_path)
    np.save(tmp_path / "blank.npy", np.zeros((64, 64), dtype=np.float32))
    report = pa.evaluate_features(pa.measure_manifest(path))
    assert report["verdict"] == pa.INCONCLUSIVE
    assert "cannot be dropped" in report["reasons"][0]


def test_cli_measure_is_create_only_and_reports_exit_codes(tmp_path, capsys):
    path, _ = _manifest_on_disk(tmp_path)
    out = tmp_path / "features.json"
    assert pa.main(["measure", "--manifest", str(path), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["tool"] == pa.TOOL
    assert pa.main(["measure", "--manifest", str(path), "--out", str(out)]) == pa.EXIT_ERROR
    assert "refusing to overwrite" in capsys.readouterr().err


@pytest.mark.parametrize("command", [[], ["measure"], ["evaluate"], ["controls"]])
def test_every_command_answers_help_without_arguments(command, capsys):
    with pytest.raises(SystemExit) as exc:
        pa.main(command + ["--help"])
    assert exc.value.code == 0
    assert "persistence" in capsys.readouterr().out.lower()


# ------------------------------------------------------------------------ model


def test_quadratic_expansion_shape_and_values():
    x = np.array([[2.0, 3.0, 5.0]])
    q = pa.quadratic_expansion(x)
    assert q.shape == (1, 3 + 3 + 3)
    assert q[0].tolist() == [2, 3, 5, 4, 9, 25, 6, 10, 15]


def test_ridge_logistic_separates_a_linear_problem_and_is_deterministic():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(400, 3))
    y = (x[:, 0] + 0.2 * rng.normal(size=400) > 0).astype(float)
    kw = {"l2": 1.0, "max_iter": 50, "tol": 1e-8}
    a = pa.fit_ridge_logistic(x, y, **kw)
    b = pa.fit_ridge_logistic(x, y, **kw)
    assert np.array_equal(a["w"], b["w"])
    assert a["w"][1] > abs(a["w"][2]) * 3
    s = pa.model_scores(a, x)
    assert np.mean(s[y == 1] > np.median(s)) > 0.8


def test_constant_feature_does_not_break_standardisation():
    x = np.hstack([np.ones((50, 1)), np.linspace(-1, 1, 50)[:, None]])
    y = (x[:, 1] > 0).astype(float)
    model = pa.fit_ridge_logistic(x, y, l2=1.0, max_iter=50, tol=1e-8)
    assert np.all(np.isfinite(pa.model_scores(model, x)))


def test_fpr_at_recall_hand_example_and_ties_count_against():
    pos = np.arange(1.0, 11.0)
    neg = np.array([0.5, 5.5, 9.5])
    assert pa.fpr_at_recall(pos, neg, 0.9) == pytest.approx(2 / 3)  # cut at 2.0
    assert pa.fpr_at_recall(np.array([1.0, 1.0]), np.array([1.0]), 1.0) == 1.0


def test_bootstrap_over_domains_is_seeded():
    a = pa.bootstrap_domains([0.1, 0.2, 0.3], seed=1, samples=500)
    assert a == pa.bootstrap_domains([0.1, 0.2, 0.3], seed=1, samples=500)
    assert a[0] <= 0.2 <= a[1]


# -------------------------------------------------------------------- decide()


def _analysis(**over):
    base = {"feasible": True, "n_included_domains": 4, "mean_gain": 0.3, "ci95": [0.1, 0.5],
            "n_positive_domains": 4, "permutation_p": 0.01}
    base.update(over)
    return base


def _stats(**over):
    stats = {"invalid_reasons": [], "incomplete_reasons": [], "preregistered": True,
             "analyses": {"all": _analysis(), "within_region": _analysis()}}
    stats.update(over)
    return stats


def test_decide_all_gates_on_both_scopes_adds_signal():
    out = pa.decide(_stats(), pa.SPEC)
    assert out["verdict"] == pa.ADDS_SIGNAL and out["reasons"] == []


def test_decide_invalid_beats_everything():
    out = pa.decide(_stats(invalid_reasons=["bad"]), pa.SPEC)
    assert out["verdict"] == pa.INVALID_DESIGN


def test_decide_infeasible_or_incomplete_is_inconclusive_never_a_pass():
    stats = _stats()
    stats["analyses"]["within_region"] = {"feasible": False, "reason": "1 usable held-out domain(s) < required 3"}
    out = pa.decide(stats, pa.SPEC)
    assert out["verdict"] == pa.INCONCLUSIVE and "within_region" in out["reasons"][0]
    assert pa.decide(_stats(incomplete_reasons=["x"]), pa.SPEC)["verdict"] == pa.INCONCLUSIVE
    assert pa.decide(_stats(analyses={}), pa.SPEC)["verdict"] == pa.INCONCLUSIVE


@pytest.mark.parametrize(
    "scope, over, gate",
    [
        ("all", {"mean_gain": 0.049}, "mean_gain"),
        ("all", {"ci95": [0.0, 0.5]}, "ci_lower_positive"),
        ("all", {"n_positive_domains": 2}, "positive_domain_fraction"),
        ("all", {"permutation_p": 0.051}, "permutation"),
        ("within_region", {"mean_gain": 0.0}, "mean_gain"),
        ("within_region", {"ci95": [-0.1, 0.5]}, "ci_lower_positive"),
        ("within_region", {"permutation_p": 0.5}, "permutation"),
    ],
)
def test_decide_each_gate_can_fail_alone_on_either_scope(scope, over, gate):
    stats = _stats()
    stats["analyses"][scope] = _analysis(**over)
    out = pa.decide(stats, pa.SPEC)
    assert out["verdict"] == pa.NO_ADDED_SIGNAL
    assert out["reasons"] == [f"gate not met: {scope}/{gate}"]


def test_decide_non_preregistered_spec_can_never_pass():
    out = pa.decide(_stats(preregistered=False), pa.SPEC)
    assert out["verdict"] == pa.EXPLORATORY
    assert "not the preregistered spec" in out["reasons"][0]


def test_gain_threshold_edge_is_inclusive_and_two_thirds_rule_needs_two_of_three():
    stats = _stats()
    stats["analyses"]["all"] = _analysis(mean_gain=0.05, n_included_domains=3, n_positive_domains=2)
    assert pa.decide(stats, pa.SPEC)["verdict"] == pa.ADDS_SIGNAL
    stats["analyses"]["all"] = _analysis(n_included_domains=3, n_positive_domains=1)
    assert pa.decide(stats, pa.SPEC)["verdict"] == pa.NO_ADDED_SIGNAL


# ------------------------------------------------------------ evaluate_features


def _fake_document(signal: str, seed: int = 0, n_domains: int = 4) -> dict:
    """Feature rows with no images: ``signal`` picks which columns carry the label."""
    rng = np.random.default_rng(seed)
    names = list(pa.BASELINE_FULL) + list(pa.PERSISTENCE_FEATURES)
    rows = []
    for d in range(n_domains):
        for label, kind in [(1, "verified_ink")] * 30 + [(0, "verified_ink")] * 15 + [(0, "crack")] * 15:
            x = {n: float(rng.normal()) for n in names}
            if signal == "persistence" and label:
                x["area_growth_log"] += 2.5
                x["skeleton_log_change"] -= 2.5
            if signal == "baseline" and label:
                x["peak_prob"] += 3.0
                x["log_area"] += 3.0
            rows.append({"region": f"r{d}", "domain": f"dom{d}", "kind": kind, "label": label,
                         "negative_kind": None if label else (pa.IN_REGION_NEGATIVE if kind == "verified_ink" else kind),
                         "x": x})
    return {"tool": pa.TOOL, "protocol": pa.PROTOCOL, "spec_sha256": pa.canonical_sha256(pa.SPEC),
            "manifest_sha256": "0" * 64, "selection_contract": dict(pa._CONTRACT),
            "regions": [{"id": "r", "status": "ok"}], "components": rows}


def _fast_spec():
    spec = copy.deepcopy(pa.SPEC)
    spec["decision"].update(permutations=40, bootstrap_samples=300)
    return spec


def _fast_doc(signal, seed=0):
    doc = _fake_document(signal, seed)
    doc["spec_sha256"] = pa.canonical_sha256(_fast_spec())
    return doc


def test_persistence_signal_is_credited_on_both_scopes():
    report = pa.evaluate_features(_fast_doc("persistence"), _fast_spec())
    assert report["verdict"] == pa.EXPLORATORY  # reduced-permutation spec is not the frozen one
    assert all(all(g.values()) for g in report["gates"].values())
    for scope in pa.SCOPES:
        a = report["analyses"][scope]
        assert a["mean_gain"] > 0.2 and a["permutation_p"] <= 0.05
        assert a["feature_auroc_by_domain"]["area_growth_log"]
        assert "crack" in report["analyses"]["all"]["negative_kinds"]


def test_signal_the_baseline_already_has_is_not_credited_to_persistence():
    report = pa.evaluate_features(_fast_doc("baseline"), _fast_spec())
    assert not all(all(g.values()) for g in report["gates"].values())
    assert report["analyses"]["all"]["mean_gain"] < 0.05


def test_pure_noise_is_not_credited():
    report = pa.evaluate_features(_fast_doc("none"), _fast_spec())
    assert not all(all(g.values()) for g in report["gates"].values())


def test_evaluation_is_deterministic():
    a = pa.evaluate_features(_fast_doc("persistence"), _fast_spec())
    b = pa.evaluate_features(_fast_doc("persistence"), _fast_spec())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_evaluate_rejects_mismatched_spec_and_tampered_contract():
    doc = _fake_document("none")
    assert pa.evaluate_features(doc, _fast_spec())["verdict"] == pa.INVALID_DESIGN  # measured under another spec
    doc = _fake_document("none")
    doc["selection_contract"]["topology_used_to_choose_threshold"] = True
    out = pa.evaluate_features(doc, pa.SPEC)
    assert out["verdict"] == pa.INVALID_DESIGN and "selection contract" in out["reasons"][0]


def test_too_few_domains_is_inconclusive_and_names_the_within_region_confound():
    report = pa.evaluate_features(_fake_document("persistence", n_domains=2), pa.SPEC)
    assert report["verdict"] == pa.INCONCLUSIVE
    assert any("usable held-out domain" in r for r in report["reasons"])


def test_domains_below_the_count_floor_are_excluded_and_listed():
    doc = _fake_document("none")
    doc["components"] = [r for r in doc["components"] if not (r["domain"] == "dom0" and r["label"] == 0)]
    spec = _fast_spec()
    report = pa.evaluate_features(doc | {"spec_sha256": pa.canonical_sha256(spec)}, spec)
    table = {t["domain"]: t for t in report["analyses"]["all"]["domains"]}
    assert table["dom0"]["included"] is False and "negatives" in table["dom0"]["excluded_reason"]
    assert report["analyses"]["all"]["n_included_domains"] == 3


def test_no_labelled_components_is_inconclusive():
    doc = _fake_document("none")
    doc["components"] = []
    assert pa.evaluate_features(doc, pa.SPEC)["verdict"] == pa.INCONCLUSIVE


def test_cli_evaluate_exit_code_for_an_inconclusive_run(tmp_path):
    doc = _fake_document("none", n_domains=2)
    features = tmp_path / "f.json"
    features.write_text(json.dumps(doc))
    out = tmp_path / "report.json"
    assert pa.main(["evaluate", "--features", str(features), "--out", str(out)]) == pa.EXIT_INCONCLUSIVE
    assert json.loads(out.read_text())["verdict"] == pa.INCONCLUSIVE
    assert pa.main(["evaluate", "--features", str(features), "--out", str(out)]) == pa.EXIT_ERROR


def test_synthetic_regions_have_feasible_domains_in_both_scopes():
    doc = pc.synthetic_document(pc.DEV_SEED_BASE + 3, pc.SCENARIOS["null_no_effect"])
    for scope in pa.SCOPES:
        table = pa._domain_table(pa._scope_rows(doc["components"], scope), pa.SPEC, scope)
        assert sum(t["included"] for t in table) >= pa.SPEC["decision"]["min_domains"]
