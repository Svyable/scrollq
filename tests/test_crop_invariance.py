import json

import numpy as np
import pytest

from scrollq.crop_invariance import (
    InvarianceError, _auroc, decide, evaluate, main, positive_control,
    synthetic_fixture,
)


def test_positive_control_passes():
    assert positive_control()["passed"]


def test_auroc_ties_and_extremes():
    assert _auroc(np.array([2.0, 3.0]), np.array([0.0, 1.0])) == 1.0
    assert _auroc(np.array([1.0, 1.0]), np.array([1.0, 1.0])) == 0.5


def test_planted_bias_removed_without_losing_separation():
    r = evaluate(*synthetic_fixture(bias=1.5))
    assert r["verdict"] == "POSITIONAL_DEPENDENCE_DEBIAS_PROMOTED"
    assert r["raw"]["position_r2"] > 0.5
    assert r["debiased"]["position_r2"] < 0.05
    assert r["debiased"]["same_voxel_cosine"] > r["raw"]["same_voxel_cosine"]


def test_clean_fixture_is_not_promoted():
    assert evaluate(*synthetic_fixture(bias=0.0))["verdict"] == \
        "NO_POSITIONAL_DEPENDENCE_DETECTED"


def test_nonpolynomial_dependence_is_not_called_clean():
    assert evaluate(*synthetic_fixture(bias=1.0, kind="highfreq"))["verdict"] == \
        "FRAME_DEPENDENCE_UNEXPLAINED"


def test_deterministic():
    a = evaluate(*synthetic_fixture(bias=1.0, seed=3))
    b = evaluate(*synthetic_fixture(bias=1.0, seed=3))
    assert a == b


def _blocks(**over):
    raw = {"position_r2": 0.5, "frame_variance_fraction": 0.3,
           "same_voxel_cosine": 0.8, "nn_stability": 0.6,
           "sheet_vs_neighbor_auroc": 0.9, "ink_vs_negative_auroc": 0.9}
    deb = dict(raw, position_r2=0.01, same_voxel_cosine=0.95, nn_stability=0.8)
    deb.update(over)
    return raw, deb


@pytest.mark.parametrize("over,failed", [
    ({"position_r2": 0.3}, "residual_position_r2"),
    ({"same_voxel_cosine": 0.7}, "same_voxel_cosine_not_lower"),
    ({"nn_stability": 0.5}, "nn_stability_not_lower"),
    ({"sheet_vs_neighbor_auroc": 0.8}, "sheet_vs_neighbor_kept"),
    ({"ink_vs_negative_auroc": 0.8}, "ink_vs_negative_kept"),
])
def test_each_gate_can_reject(over, failed):
    d = decide(*_blocks(**over))
    assert d["verdict"] == "POSITIONAL_DEPENDENCE_DEBIAS_REJECTED"
    assert d["failed_checks"] == [failed]


def test_smoother_alone_is_not_enough():
    d = decide(*_blocks(same_voxel_cosine=1.0, nn_stability=1.0,
                        sheet_vs_neighbor_auroc=0.5, ink_vs_negative_auroc=0.5))
    assert d["verdict"] == "POSITIONAL_DEPENDENCE_DEBIAS_REJECTED"


def test_chance_raw_separation_is_unverified():
    raw, deb = _blocks()
    raw["ink_vs_negative_auroc"] = 0.52
    assert decide(raw, deb)["status"] == "unverified"


def test_identical_crop_frames_unverified():
    arrays, shape = synthetic_fixture(bias=1.0)
    arrays["crop_origin"] = np.zeros_like(arrays["crop_origin"])
    assert evaluate(arrays, shape)["status"] == "unverified"


def test_missing_class_unverified():
    arrays, shape = synthetic_fixture(bias=1.0)
    arrays["labels"] = np.where(arrays["labels"] == "void", "fiber", arrays["labels"])
    r = evaluate(arrays, shape)
    assert r["status"] == "unverified" and "void" in r["reason"]


def test_point_outside_crop_is_error():
    arrays, shape = synthetic_fixture(bias=1.0)
    arrays["points_xyz"][0, 0] = 200.0
    with pytest.raises(InvarianceError):
        evaluate(arrays, shape)


def _write(tmp_path, sha=None):
    arrays, shape = synthetic_fixture(bias=1.5)
    np.savez(tmp_path / "f.npz", **arrays)
    from scrollq.crop_invariance import _sha256
    man = {"schema_version": 1, "experiment_id": "t", "crop_shape": list(shape),
           "arrays": "f.npz", "arrays_sha256": sha or _sha256(tmp_path / "f.npz")}
    (tmp_path / "m.json").write_text(json.dumps(man))
    return tmp_path / "m.json"


def test_cli_manifest_roundtrip_and_create_only(tmp_path):
    m = _write(tmp_path)
    out = tmp_path / "o.json"
    assert main(["--manifest", str(m), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["verdict"] == "POSITIONAL_DEPENDENCE_DEBIAS_PROMOTED"
    with pytest.raises(FileExistsError):
        main(["--manifest", str(m), "--out", str(out)])


def test_cli_hash_mismatch_fails(tmp_path):
    assert main(["--manifest", str(_write(tmp_path, sha="0" * 64))]) == 2


def test_missing_embeddings_are_unavailable_input_not_failed(tmp_path, capsys):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"schema_version": 1, "experiment_id": "t",
                             "arrays": None}))
    assert main(["--manifest", str(m)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable_input"


def test_help_needs_no_args(capsys):
    assert main([]) == 0
