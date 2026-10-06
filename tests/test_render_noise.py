import json

import pytest

from scrollq.render_noise import NoiseError, evaluate, main, positive_control


def _rec(**kw):
    base = {"schema_version": 1, "experiment_id": "exp", "metric": "fg_px",
            "determinism": {"mode": "deterministic",
                            "settings": {"torch_deterministic": True}},
            "repeats": [{"value": 1000, "outputs_sha256": {"x.tif": "a"}},
                        {"value": 1000, "outputs_sha256": {"x.tif": "a"}},
                        {"value": 1000, "outputs_sha256": {"x.tif": "a"}}],
            "claims": [{"claim_id": "c", "baseline": 1000,
                        "candidate": 1020}]}
    base.update(kw)
    return base


def test_positive_control_passes():
    assert positive_control()["passed"]


def test_bit_identical_deterministic_repeats():
    r = evaluate(_rec())
    assert r["status"] == "measured"
    assert r["outputs_bit_identical"] is True
    assert r["noise_floor_relative"] == 0.0
    assert r["claims"][0]["verdict"] == "EXCEEDS_NOISE_FLOOR"


def test_floor_min_prevents_zero_floor_trivialising_tiny_changes():
    r = evaluate(_rec(rule={"floor_min": 0.01}, claims=[
        {"claim_id": "c", "baseline": 1000, "candidate": 1020}]))
    assert r["claims"][0]["verdict"] == "WITHIN_NOISE"


def test_nondeterministic_three_percent_floor_swallows_two_percent_claim():
    r = evaluate(_rec(determinism={"mode": "nondeterministic"}, repeats=[
        {"value": 1000}, {"value": 1030.4}, {"value": 1010}]))
    assert r["noise_floor_relative"] == pytest.approx(30.4 / (3040.4 / 3))
    assert r["claims"][0]["verdict"] == "WITHIN_NOISE"
    assert r["outputs_bit_identical"] is None


def test_declared_deterministic_but_outputs_differ_warns():
    reps = [{"value": 1000, "outputs_sha256": {"x.tif": h}}
            for h in ("a", "a", "b")]
    r = evaluate(_rec(repeats=reps))
    assert r["outputs_bit_identical"] is False
    assert "warning" in r


@pytest.mark.parametrize("kw", [
    {"determinism": {"mode": "unknown"}},
    {"determinism": {}},
    {"repeats": [{"value": 1}, {"value": 1}]},
])
def test_missing_mode_or_repeats_is_unverified(kw):
    assert evaluate(_rec(**kw))["status"] == "unverified"


def test_bad_values_fail_closed():
    with pytest.raises(NoiseError):
        evaluate(_rec(repeats=[{"value": float("nan")}] * 3))
    with pytest.raises(NoiseError):
        evaluate(_rec(claims=[{"claim_id": "c", "baseline": 0,
                               "candidate": 1}]))


def test_cli(tmp_path):
    (tmp_path / "rec.json").write_text(json.dumps(_rec()))
    out = tmp_path / "noise.json"
    assert main(["--record", str(tmp_path / "rec.json"), "--out",
                 str(out)]) == 0
    assert "measurement_noise" in json.loads(out.read_text())
    assert main(["--self-test"]) == 0
