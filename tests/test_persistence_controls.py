"""Synthetic control suite for the threshold-persistence audit."""

import json

import numpy as np
import pytest

from scrollq import persistence_audit as pa
from scrollq import persistence_controls as pc


def test_synthetic_documents_are_deterministic_and_seed_sensitive():
    a = pc.synthetic_document(41, pc.SCENARIOS["null_no_effect"])
    b = pc.synthetic_document(41, pc.SCENARIOS["null_no_effect"])
    c = pc.synthetic_document(42, pc.SCENARIOS["null_no_effect"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert json.dumps(a, sort_keys=True) != json.dumps(c, sort_keys=True)


def test_every_synthetic_domain_has_its_own_calibration_and_passes_measurement():
    doc = pc.synthetic_document(pc.DEV_SEED_BASE + 5, pc.SCENARIOS["planted_sweep_effect"])
    assert all(r["status"] == "ok" and r["invariance"]["ok"] for r in doc["regions"])
    by_domain = {}
    for r in doc["regions"]:
        by_domain.setdefault(r["domain"], set()).add(r["remap"])
    assert all(len(v) == 1 for v in by_domain.values())  # one calibration per domain
    assert len({next(iter(v)) for v in by_domain.values()}) >= 2  # and they differ across domains


def test_the_planted_effect_is_invisible_to_baseline_features_at_the_nominal_threshold():
    doc = pc.synthetic_document(pc.DEV_SEED_BASE + 1003, pc.SCENARIOS["planted_sweep_effect"])
    rows = [r for r in doc["components"]]
    y = np.array([r["label"] for r in rows])
    for name in ("log_area", "peak_margin_log", "bbox_fill"):
        x = np.array([r["x"][name] for r in rows])
        auc = pa._roc_auc(x, y)
        assert 0.35 < auc < 0.65, (name, auc)


def test_invariance_controls_have_teeth():
    inv = pc.invariance_controls(pc.DEV_SEED_BASE + 7)
    assert inv["n_components"] >= 3
    conclusive = [r for r in inv["remaps"] if r["injective"]]
    assert {r["remap"] for r in conclusive} == {"cube", "expm1_3x", "sqrt", "scale"}
    assert all(r["rank_features_identical"] and r["rank_persistence_identical"] for r in conclusive)
    assert all(not r["value_persistence_identical"] for r in conclusive)


def test_planted_effect_is_found_and_adds_signal_on_both_scopes():
    out = pc.run_scenario("planted_sweep_effect", [pc.DEV_SEED_BASE + 1001])
    run = out["runs"][0]
    assert run["verdict"] == pa.ADDS_SIGNAL
    assert run["all_scope_gates_pass"] and run["within_region_gates_pass"]
    assert run["all"]["mean_gain"] > 0.2 and run["within_region"]["mean_gain"] > 0.2


def test_identical_generators_are_not_credited():
    out = pc.run_scenario("null_no_effect", [pc.DEV_SEED_BASE + 2001])
    assert out["runs"][0]["verdict"] == pa.NO_ADDED_SIGNAL
    assert out["runs"][0]["all"]["mean_gain"] < 0.05


def test_a_region_level_confound_is_stopped_by_the_within_region_scope():
    out = pc.run_scenario("region_confound_only", [pc.DEV_SEED_BASE + 4001])
    run = out["runs"][0]
    assert run["verdict"] == pa.NO_ADDED_SIGNAL
    assert not run["within_region_gates_pass"]
    assert run["all"]["mean_gain"] > run["within_region"]["mean_gain"]


def test_cli_controls_writes_a_report_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pc, "SCENARIOS", {"planted_sweep_effect": pc.SCENARIOS["planted_sweep_effect"]})
    out = tmp_path / "controls.json"
    code = pa.main(["controls", "--out", str(out), "--n", "1", "--quick", "--seed-base", str(pc.DEV_SEED_BASE)])
    report = json.loads(out.read_text())
    assert code in (0, 1)
    assert report["synthetic"] is True
    assert report["spec_sha256"] == pa.FROZEN_SPEC_SHA256
    assert [s["name"] for s in report["scenarios"]] == ["planted_sweep_effect"]
    names = [g["name"] for g in report["gates"]]
    assert any("Euler" in n for n in names) and any("teeth" in n for n in names)
    assert report["gate_status"] == ("pass" if all(g["pass"] for g in report["gates"]) else "fail")
    assert pa.main(["controls", "--out", str(out)]) == pa.EXIT_ERROR
    assert "refusing to overwrite" in capsys.readouterr().err


def test_run_controls_rejects_a_nonsensical_seed_count():
    with pytest.raises(pa.AuditError):
        pc.run_controls(n=0, quick=True)


def test_manifest_chain_on_disk_reaches_a_preregistered_verdict(tmp_path):
    """Files -> `measure` -> `evaluate` with the frozen spec, float32 storage included."""
    import hashlib

    scenario = pc.SCENARIOS["planted_sweep_effect"]
    rng = np.random.default_rng(pc.DEV_SEED_BASE + 1001)
    sha = "c" * 64

    def save(name, array):
        path = tmp_path / name
        np.save(path, array)
        return path.name, hashlib.sha256(path.read_bytes()).hexdigest()

    regions = []
    for d in range(pc.N_DOMAINS):
        noise = rng.uniform(0.15, 0.30)
        remap = list(pc.REMAP_POOL.values())[int(rng.integers(0, len(pc.REMAP_POOL)))]
        threshold = float(remap(np.float64(pc.TAU)))
        ink_strokes = [(pc.INK_STYLE, True)] * pc.INK_STROKES + [(scenario["inregion"], False)] * pc.INREGION_FP_STROKES
        plan = [("verified_ink", ink_strokes)] * pc.INK_REGIONS + [
            ("known_false_positive", [(scenario["blank"], False)] * pc.BLANK_STROKES)
        ] * pc.BLANK_REGIONS
        for i, (kind, strokes) in enumerate(plan):
            field, ink = pc.synth_region(rng, strokes, noise)
            rid = f"d{d}-{kind}-{i}"
            pred, pred_sha = save(f"{rid}.npy", remap(field).astype(np.float32))
            entry = {"id": rid, "domain": f"dom{d}", "kind": kind, "nominal_threshold": threshold,
                     "prediction": pred, "prediction_sha256": pred_sha}
            if kind == "verified_ink":
                lab, lab_sha = save(f"{rid}.labels.npy", ink.astype(np.uint8))
                entry.update(labels=lab, labels_sha256=lab_sha)
            regions.append(entry)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "protocol": pa.PROTOCOL, "selection_contract": dict(pa._CONTRACT),
        "detector": {"name": "synthetic", "checkpoint_sha256": sha, "inference_config_sha256": sha,
                     "training_domains": ["scroll-never-evaluated"]},
        "regions": regions,
    }))
    features, report = tmp_path / "features.json", tmp_path / "report.json"
    assert pa.main(["measure", "--manifest", str(manifest), "--out", str(features)]) == 0
    doc = json.loads(features.read_text())
    assert doc["preregistered"] is True and all(r["status"] == "ok" for r in doc["regions"])
    assert pa.main(["evaluate", "--features", str(features), "--out", str(report)]) == pa.EXIT_ADDS_SIGNAL
    result = json.loads(report.read_text())
    assert result["verdict"] == pa.ADDS_SIGNAL and result["preregistered"] is True
    assert all(all(g.values()) for g in result["gates"].values())
