"""Deterministic tests for the papyrus microtexture seam authenticator.

These are software controls on synthetic sheets. They do not show that real
carbonized papyrus carries a recoverable fingerprint.
"""

import dataclasses
import json

import numpy as np
import pytest

import scrollq.seam_fingerprint as sf

SEED = 424_242


def _pair(seed=SEED, dy=1.3, dx=-0.7, noise=0.0, rng_seed=1):
    rng = np.random.default_rng(rng_seed)
    field = sf.synthetic_sheet(seed)
    a = sf._slab(field)
    b = sf._slab(sf._translate(field, dy, dx))
    if noise:
        a = a + noise * rng.standard_normal(a.shape)
        b = b + noise * rng.standard_normal(b.shape)
    return a, b


def test_genuine_pair_is_authenticated_and_displacement_recovered():
    a, b = _pair(dy=1.3, dx=-0.7, noise=0.5)
    out = sf.authenticate_pair(a, b)
    assert out["verdict"] == sf.AUTHENTICATED
    assert out["reasons"] == []
    got = np.array(out["peak"]["shift_yx_px"])
    assert np.hypot(*(got - np.array([1.3, -0.7]))) < 0.5
    assert out["peak"]["depth_lag"] == 0
    assert out["refinement"]["usable"] is True


def test_shift_convention_content_moves_by_plus_d():
    a, b = _pair(dy=3.0, dx=5.0)
    cfg = dataclasses.replace(sf.DEFAULT_CONFIG, geometry_tolerance_px=8.0)
    out = sf.authenticate_pair(a, b, config=cfg)
    assert out["verdict"] == sf.AUTHENTICATED
    assert out["peak"]["shift_yx_px"] == pytest.approx([3.0, 5.0], abs=0.5)


def test_claimed_registration_offset_is_contradicted_not_silently_absorbed():
    a, b = _pair(dy=8.0, dx=6.0)
    out = sf.authenticate_pair(a, b)
    assert out["verdict"] == sf.CONTRADICTED
    assert out["reasons"] == ["registration-offset-exceeds-tolerance"]
    # telling the unroller the true offset makes the same pair authentic
    again = sf.authenticate_pair(a, b, expected_shift_yx=(8.0, 6.0))
    assert again["verdict"] == sf.AUTHENTICATED
    assert again["peak"]["residual_px"] < 0.5


def test_wrong_sheet_with_identical_statistics_is_contradicted():
    a = sf._slab(sf.synthetic_sheet(SEED))
    b = sf._slab(sf.synthetic_sheet(SEED + 1))
    out = sf.authenticate_pair(a, b)
    assert out["verdict"] == sf.CONTRADICTED
    assert out["reasons"] == ["no-correspondence-within-search"]
    assert out["peak"]["z"] < sf.DEFAULT_CONFIG.z_contradict


def test_phase_randomizing_one_patch_collapses_authentication():
    a, b = _pair()
    genuine = sf.authenticate_pair(a, b)
    rng = np.random.default_rng(3)
    destroyed = sf.authenticate_pair(a, sf._phase_randomized(b, rng))
    assert genuine["verdict"] == sf.AUTHENTICATED
    assert destroyed["verdict"] != sf.AUTHENTICATED
    assert destroyed["peak"]["z"] < 0.2 * genuine["peak"]["z"]


def test_block_shuffling_one_patch_collapses_authentication():
    a, b = _pair()
    shuffled = sf._block_shuffle(b, np.random.default_rng(4))
    out = sf.authenticate_pair(a, shuffled)
    assert out["verdict"] != sf.AUTHENTICATED


def test_identical_permutation_of_both_patches_keeps_identity():
    # the collapse above must come from broken correspondence, not from block seams
    a, b = _pair(dy=0.0, dx=0.0, noise=0.3)
    a = a + 0.0
    perm_a = sf._block_shuffle(a, np.random.default_rng(9))
    perm_b = sf._block_shuffle(b, np.random.default_rng(9))
    out = sf.authenticate_pair(perm_a, perm_b)
    assert out["verdict"] == sf.AUTHENTICATED


@pytest.mark.parametrize("name", ["blank_smooth", "pure_noise"])
def test_low_information_patches_are_unknown_never_authenticated(name):
    case = next(c for c in sf.CONTROL_CASES if c.name == name)
    a, b, _ = case.build(SEED, np.random.default_rng(1))
    out = sf.authenticate_pair(a, b)
    assert out["verdict"] == sf.UNKNOWN
    assert "insufficient-band-information" in out["reasons"]


def test_identical_pixel_arrays_fail_closed():
    a = sf._slab(sf.synthetic_sheet(SEED))
    out = sf.authenticate_pair(a, a.copy())
    assert out["verdict"] == sf.UNKNOWN
    assert out["reasons"] == ["identical-pixel-arrays"]


def test_shared_crack_with_independent_microtexture_is_not_authenticated():
    case = next(c for c in sf.CONTROL_CASES if c.name == "shared_crack_impostor")
    for seed in (SEED, SEED + 3, SEED + 6):
        a, b, _ = case.build(seed, np.random.default_rng(1))
        assert sf.authenticate_pair(a, b)["verdict"] != sf.AUTHENTICATED


def test_feature_gate_is_what_stops_the_crack_impostor():
    # ablation: the naive statistic accepts a crack-dominated impostor
    crack = sf._crack_field(amplitude=40.0)
    a = sf._slab(0.05 * sf.synthetic_sheet(SEED) - crack)
    b = sf._slab(0.05 * sf.synthetic_sheet(SEED + 1) - crack)
    naive = dataclasses.replace(sf.DEFAULT_CONFIG, feature_clip_sigma=0.0)
    assert sf.authenticate_pair(a, b, config=naive)["verdict"] == sf.AUTHENTICATED
    assert sf.authenticate_pair(a, b)["verdict"] != sf.AUTHENTICATED


def test_genuine_pair_carrying_a_crack_is_still_authenticated():
    case = next(c for c in sf.CONTROL_CASES if c.name == "genuine_shared_crack")
    a, b, _ = case.build(SEED, np.random.default_rng(1))
    assert sf.authenticate_pair(a, b)["verdict"] == sf.AUTHENTICATED


def test_flipped_normal_is_flagged_not_authenticated():
    field = sf.synthetic_sheet(SEED)
    a = sf._slab(field)
    out = sf.authenticate_pair(a, a[::-1].copy() + 1e-3 * np.arange(a.size).reshape(a.shape) % 1)
    assert out["verdict"] == sf.CONTRADICTED
    assert out["reasons"] == ["normal-orientation-flipped"]


def test_depth_offset_inside_search_is_recovered_and_outside_is_not_asserted():
    inside = next(c for c in sf.CONTROL_CASES if c.name == "genuine_depth_offset")
    a, b, extra = inside.build(SEED, np.random.default_rng(1))
    out = sf.authenticate_pair(a, b)
    assert out["verdict"] == sf.AUTHENTICATED
    assert out["peak"]["depth_lag"] == extra["truth_lag"] == 1
    far = next(c for c in sf.CONTROL_CASES if c.name == "genuine_depth_misregistered")
    a, b, _ = far.build(SEED, np.random.default_rng(1))
    out = sf.authenticate_pair(a, b)
    assert out["verdict"] == sf.UNKNOWN
    assert out["reasons"] == ["depth-lag-at-search-boundary"]


def test_invalid_pixels_are_masked_not_correlated():
    a, b = _pair(noise=0.3)
    hole = np.zeros(a.shape[1:], dtype=bool)
    hole[10:30, 10:30] = True
    a2, b2 = a.copy(), b.copy()
    a2[:, hole] = 1e6  # garbage inside the invalid region must not matter
    b2[:, hole] = -1e6
    out = sf.authenticate_pair(a2, b2, valid_a=~hole, valid_b=~hole)
    assert out["verdict"] == sf.AUTHENTICATED
    assert out["information"]["valid_fraction"][0] == pytest.approx(1 - hole.mean())


def test_too_little_valid_area_is_unknown():
    a, b = _pair()
    mostly_invalid = np.zeros(a.shape[1:], dtype=bool)
    mostly_invalid[:20, :20] = True
    out = sf.authenticate_pair(a, b, valid_a=mostly_invalid, valid_b=mostly_invalid)
    assert out["verdict"] == sf.UNKNOWN
    assert "insufficient-valid-fraction" in out["reasons"]


def test_authentication_is_deterministic_and_input_pure():
    a, b = _pair(noise=0.5)
    a0, b0 = a.copy(), b.copy()
    first = sf.authenticate_pair(a, b)
    second = sf.authenticate_pair(a, b)
    assert first == second
    assert np.array_equal(a, a0) and np.array_equal(b, b0)


def test_invalid_inputs_are_rejected():
    a, b = _pair()
    with pytest.raises(sf.SeamFingerprintError):
        sf.authenticate_pair(a[0], b[0])
    with pytest.raises(sf.SeamFingerprintError):
        sf.authenticate_pair(a, b[:, :-1])
    bad = a.copy()
    bad[0, 0, 0] = np.nan
    with pytest.raises(sf.SeamFingerprintError):
        sf.authenticate_pair(bad, b)
    with pytest.raises(sf.SeamFingerprintError):
        sf.authenticate_pair(a[:, :30, :30], b[:, :30, :30])  # tile < search disk
    with pytest.raises(sf.SeamFingerprintError):
        sf.authenticate_pair(a, b, expected_shift_yx=(0.0, np.inf))
    with pytest.raises(sf.SeamFingerprintError):
        sf.authenticate_pair(a, b, valid_a=np.ones((3, 3), dtype=bool))


@pytest.mark.parametrize(
    "change",
    [
        {"sigma_low_px": 5.0},
        {"z_contradict": 20.0},
        {"geometry_tolerance_px": 99.0},
        {"surrogates": 0},
        {"min_unique_ratio": 0.5},
        {"z_refine": 1.0},
        {"max_masked_fraction": 0.0},
    ],
)
def test_nonsensical_config_is_rejected(change):
    cfg = dataclasses.replace(sf.DEFAULT_CONFIG, **change)
    with pytest.raises(sf.SeamFingerprintError):
        cfg.validate()


def test_config_digest_changes_with_any_constant():
    base = sf.DEFAULT_CONFIG.sha256()
    assert base == sf.DEFAULT_CONFIG.sha256()
    assert dataclasses.replace(sf.DEFAULT_CONFIG, z_authenticate=9.5).sha256() != base


def test_control_suite_gate_passes_on_a_small_fresh_seed_range():
    suite = sf.run_controls(seed_base=555_000, n=3, sweep_n=1)
    assert suite["gate"]["status"] == "pass", json.dumps(suite["gate"], indent=1)
    names = {row["name"] for row in suite["cases"]}
    for required in (
        "phase_randomized", "block_shuffled", "blank_smooth", "flipped_normal",
        "shared_crack_impostor", "adjacent_shared_coarse", "identical_pixels",
    ):
        assert required in names


def _write_pair_inputs(tmp_path, **arrays):
    a, b = _pair(noise=0.3)
    npz = tmp_path / "pair.npz"
    np.savez(npz, slab_a=a, slab_b=b, **arrays)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"frozen": true}\n', encoding="utf-8")
    return npz, manifest


def _pair_args(npz, manifest, out, *extra):
    return [
        "pair", "--input", str(npz), "--volume-root", "vol/A",
        "--surface-a-sha256", "a" * 64, "--surface-b-sha256", "b" * 64,
        "--sampling-manifest", str(manifest), "--out", str(out), *extra,
    ]


def test_cli_pair_report_binds_inputs_config_and_source(tmp_path, capsys):
    npz, manifest = _write_pair_inputs(tmp_path)
    out = tmp_path / "report.json"
    code = sf.main(_pair_args(npz, manifest, out))
    assert code == sf.EXIT_AUTHENTICATED
    report = json.loads(out.read_text())
    assert report["verdict"] == sf.AUTHENTICATED
    assert report["noise_arm"] == "shared-voxels"
    assert "not evidence of an independent physical fingerprint" in report["interpretation"]
    assert report["config_sha256"] == sf.DEFAULT_CONFIG.sha256()
    assert report["source_sha256"] == sf.source_sha256()
    assert report["input"]["sha256"] == sf._sha256_file(npz)
    assert report["sampling_manifest"]["sha256"] == sf._sha256_file(manifest)
    assert report["classification"] == "EXPERIMENT FURTHER"
    assert "AUTHENTICATED" in capsys.readouterr().out


def test_cli_independent_scan_arm_is_recorded(tmp_path):
    npz, manifest = _write_pair_inputs(tmp_path)
    out = tmp_path / "report.json"
    assert sf.main(_pair_args(npz, manifest, out, "--volume-root-b", "vol/B")) == 0
    assert json.loads(out.read_text())["noise_arm"] == "independent-scans"


def test_cli_refuses_to_overwrite_and_reports_errors(tmp_path, capsys):
    npz, manifest = _write_pair_inputs(tmp_path)
    out = tmp_path / "report.json"
    assert sf.main(_pair_args(npz, manifest, out)) == 0
    assert sf.main(_pair_args(npz, manifest, out)) == sf.EXIT_ERROR
    assert "refusing to overwrite" in capsys.readouterr().err
    missing = tmp_path / "no.npz"
    assert sf.main(_pair_args(missing, manifest, tmp_path / "x.json")) == sf.EXIT_ERROR
    junk = tmp_path / "junk.npz"
    np.savez(junk, slab_a=np.zeros((5, 64, 64)))
    assert sf.main(_pair_args(junk, manifest, tmp_path / "y.json")) == sf.EXIT_ERROR


def test_cli_exit_codes_distinguish_unknown_and_contradicted(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    rng = np.random.default_rng(0)
    noise = tmp_path / "noise.npz"
    np.savez(noise, slab_a=rng.standard_normal((5, 64, 64)), slab_b=rng.standard_normal((5, 64, 64)))
    assert sf.main(_pair_args(noise, manifest, tmp_path / "u.json")) == sf.EXIT_UNKNOWN
    wrong = tmp_path / "wrong.npz"
    np.savez(wrong, slab_a=sf._slab(sf.synthetic_sheet(SEED)), slab_b=sf._slab(sf.synthetic_sheet(SEED + 1)))
    assert sf.main(_pair_args(wrong, manifest, tmp_path / "c.json")) == sf.EXIT_CONTRADICTED


def test_cli_rejects_malformed_digests(tmp_path):
    npz, manifest = _write_pair_inputs(tmp_path)
    args = _pair_args(npz, manifest, tmp_path / "r.json")
    args[args.index("a" * 64)] = "not-a-digest"
    assert sf.main(args) == sf.EXIT_ERROR
    assert not (tmp_path / "r.json").exists()


def test_cli_controls_writes_a_synthetic_labeled_report(tmp_path):
    out = tmp_path / "controls.json"
    code = sf.main(["controls", "--out", str(out), "--seed-base", "556000", "--n", "2", "--sweep-n", "1"])
    assert code == 0
    report = json.loads(out.read_text())
    assert report["synthetic"] is True
    assert report["ablation"] is None
    assert report["gate"]["status"] == "pass"
    assert "says nothing about whether carbonized papyrus" in report["interpretation"]


def test_cli_controls_ablation_is_labeled(tmp_path):
    out = tmp_path / "ablation.json"
    sf.main(["controls", "--out", str(out), "--seed-base", "556000", "--n", "2",
             "--sweep-n", "1", "--ablate", "feature-gate"])
    report = json.loads(out.read_text())
    assert report["ablation"] == "feature-gate-disabled"
    assert report["config"]["feature_clip_sigma"] == 0.0


def test_information_gate_is_what_stops_shared_voxel_noise_on_blank_papyrus():
    case = next(c for c in sf.CONTROL_CASES if c.name == "blank_shared_voxel_noise")
    a, b, _ = case.build(SEED, np.random.default_rng(1))
    gated = sf.authenticate_pair(a, b)
    assert gated["verdict"] == sf.UNKNOWN
    assert "insufficient-band-information" in gated["reasons"]
    # without the gate the shared noise alone is "authenticated": the hazard is real
    naive = dataclasses.replace(sf.DEFAULT_CONFIG, **sf.ABLATIONS["information-gate"])
    assert sf.authenticate_pair(a, b, config=naive)["verdict"] == sf.AUTHENTICATED


def test_fully_invalid_masks_degrade_to_unknown_without_crashing():
    a, b = _pair()
    none = np.zeros(a.shape[1:], dtype=bool)
    out = sf.authenticate_pair(a, b, valid_a=none, valid_b=none)
    assert out["verdict"] == sf.UNKNOWN
    assert "insufficient-valid-fraction" in out["reasons"]
    assert out["refinement"]["usable"] is False
