import json

import numpy as np
import pytest

from omezarr_fixture import build_store
from scrollq import protocol_pairs as pp
from scrollq.omezarr import OmeZarrVolume
from scrollq.registration import infer_registration
from test_registration import _doc as reg_doc

PERIOD_UM = 48.0
ROT = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])  # 90 z
PX_FINE, PX_COARSE = 2.0, 4.0


def field(phys_xyz, softness):
    """Analytic sheets in physical um; ``softness`` is the edge width."""
    u = (phys_xyz[..., 0] + 0.35 * phys_xyz[..., 1]) / PERIOD_UM
    s = 1.0 / (1.0 + np.exp(-(np.sin(2 * np.pi * u) - 0.35) / softness))
    return np.clip(np.rint(40.0 + 170.0 * s), 1, 255).astype(np.uint8)


def idx_grid(shape):
    z, y, x = np.meshgrid(*[np.arange(n, dtype=np.float64) for n in shape],
                          indexing="ij")
    return np.stack([x, y, z], axis=-1)  # xyz


def make_pair(fine_soft, coarse_soft, seed_landmarks=5, n_f=48,
              rot_deg=90.0):
    """Moving = fine scan (96^3, 2um) rotated 90deg about z vs fixed = coarse
    scan (48^3, 4um) of the same physical field."""
    n_m = 96
    if rot_deg == 90.0:
        rot = ROT
        shift = np.array([n_m * PX_FINE, 0.0, 0.0])
    else:
        a_ = np.deg2rad(rot_deg)
        rot = np.array([[np.cos(a_), -np.sin(a_), 0.0],
                        [np.sin(a_), np.cos(a_), 0.0], [0.0, 0.0, 1.0]])
        corners = np.array([[x, y, z] for x in (0, n_m - 1)
                            for y in (0, n_m - 1) for z in (0, n_m - 1)],
                           dtype=float) * PX_FINE @ rot.T
        shift = -corners.min(axis=0) + 4.0
    p_m = idx_grid((n_m,) * 3) * PX_FINE
    phys_m = p_m @ rot.T + shift                      # moving voxel -> phys
    moving = field(phys_m, fine_soft)
    fixed = field(idx_grid((n_f,) * 3) * PX_COARSE, coarse_soft)
    a = (PX_FINE / PX_COARSE) * rot
    b = shift / PX_COARSE
    rng = np.random.default_rng(seed_landmarks)
    lm = rng.uniform(5, 90, (8, 3))
    doc = {"schema_version": "1.0.0", "fixed_volume": "fixed_masked",
           "transformation_matrix": np.hstack([a, b[:, None]]).tolist(),
           "moving_landmarks": lm.tolist(),
           "fixed_landmarks": (lm @ a.T + b).tolist()}
    reg = infer_registration(doc)
    mv = OmeZarrVolume.open(build_store(moving, chunks=(16, 16, 16),
                                        levels=2), "vol.zarr")
    fx = OmeZarrVolume.open(build_store(fixed, chunks=(16, 16, 16),
                                        levels=1), "vol.zarr")
    return pp.PairRun("S", "mov", "fix", mv, fx, reg, PX_FINE, PX_COARSE)


def run(pr, **kw):
    return pp.run_pair(pr, seed=1, n_regions=10, target_um=4.0, cube_n=16,
                       **kw)


# -- metrics ---------------------------------------------------------------
def _cube(softness, scale=1.0):
    g = idx_grid((24, 24, 24)) * 4.0
    return (field(g, softness).astype(np.float32) * scale)


def test_crisp_layers_beat_hazy_layers_on_both_primary_metrics():
    crisp = pp.separability_metrics(_cube(0.05))
    hazy = pp.separability_metrics(_cube(0.9))
    assert crisp["otsu_eta"] > hazy["otsu_eta"]
    assert crisp["edge_sharpness"] > hazy["edge_sharpness"]


def test_primary_metrics_are_intensity_scale_invariant():
    a = pp.separability_metrics(_cube(0.3, 1.0))
    b = pp.separability_metrics(_cube(0.3, 0.5))
    assert b["otsu_eta"] == pytest.approx(a["otsu_eta"], rel=0.05)
    assert b["edge_sharpness"] == pytest.approx(a["edge_sharpness"], rel=0.05)


def test_flat_cube_has_undefined_primary_metrics_not_fake_numbers():
    m = pp.separability_metrics(np.full((8, 8, 8), 100.0, np.float32))
    assert np.isnan(m["otsu_eta"]) and np.isnan(m["edge_sharpness"])


# -- statistics ------------------------------------------------------------
def test_sign_test_exact_values():
    assert pp.sign_test_p(5, 0) == pytest.approx(1 / 32)
    assert pp.sign_test_p(3, 2) == pytest.approx(0.5)
    assert pp.sign_test_p(0, 0) == 1.0
    assert pp.sign_test_p(0, 5) == pytest.approx(1.0)


def test_bootstrap_ci_is_deterministic_and_degenerate_for_constants():
    assert pp.bootstrap_median_ci([1.0] * 9, seed=3) == (1.0, 1.0)
    a = pp.bootstrap_median_ci([1, 2, 3, 4, 5], seed=3)
    assert a == pp.bootstrap_median_ci([1, 2, 3, 4, 5], seed=3)
    assert a[0] <= 3 <= a[1]
    assert all(np.isnan(pp.bootstrap_median_ci([], seed=1)))


# -- end to end on synthetic registered scans ---------------------------------
def test_pipeline_recovers_known_protocol_ordering():
    res = run(make_pair(fine_soft=0.05, coarse_soft=0.9))
    assert res["ok"] and res["accepted"] == 10
    assert (res["fine"], res["coarse"]) == ("moving", "fixed")
    assert res["grid_spacing_um"] == pytest.approx(4.0)
    for k in pp.PRIMARY_METRICS:
        s = res["summary"]["metrics"][k]
        assert s["frac_positive"] == 1.0 and s["median_d"] > 0
        assert s["sign_test_p"] < 0.01
        # pipeline null (half-step shift) is far smaller than the effect
        assert res["summary"]["null"][k]["median_abs"] < \
            pp.NULL_RATIO_MAX * abs(s["median_d"])


def test_pipeline_can_fail_reversed_ordering_flips_the_sign():
    # the *finer* scan is the hazy one: a sound pipeline must say so
    res = run(make_pair(fine_soft=0.9, coarse_soft=0.05))
    assert res["ok"]
    for k in pp.PRIMARY_METRICS:
        s = res["summary"]["metrics"][k]
        assert s["median_d"] < 0 and s["frac_positive"] == 0.0


def test_identical_protocols_give_no_systematic_difference():
    res = run(make_pair(fine_soft=0.3, coarse_soft=0.3))
    for k in pp.PRIMARY_METRICS:
        s = res["summary"]["metrics"][k]
        assert abs(s["median_d"]) < 0.15  # eta in [0,1]; noise only


def test_run_is_deterministic_for_a_seed():
    a = run(make_pair(0.05, 0.9))
    b = run(make_pair(0.05, 0.9))
    assert a["regions"] == b["regions"]


def test_level_mismatch_beyond_tolerance_is_refused():
    pr = make_pair(0.05, 0.9)
    res = pp.run_pair(pr, seed=1, n_regions=4, target_um=40.0, cube_n=16)
    assert not res["ok"] and "pyramid level" in res["reason"]


def test_all_background_pair_yields_no_regions_and_counts_rejections():
    pr = make_pair(0.05, 0.9)
    # wipe the fixed volume: every cube fails the occupancy rule
    for k in list(pr.fixed.store.data):
        if k.startswith("vol.zarr/0/") and not k.endswith(".zarray"):
            del pr.fixed.store.data[k]
    pr.fixed._cache.clear()
    res = run(pr)
    assert res["ok"] and res["accepted"] == 0
    assert res["rejections"]["occupancy"] > 0


# -- decision rule -----------------------------------------------------------
def _pair(name, med, frac, null, included=True):
    metrics = {k: {"median_d": med, "frac_positive": frac}
               for k in pp.PRIMARY_METRICS}
    nulls = {k: {"median_abs": null} for k in pp.PRIMARY_METRICS}
    return {"name": name, "included": included,
            "summary": {"metrics": metrics, "null": nulls}}


def test_decide_concordant_when_most_pairs_agree():
    pairs = [_pair(f"p{i}", 0.2, 0.9, 0.01) for i in range(5)]
    out = pp.decide(pairs)
    assert all(v["verdict"] == "concordant"
               for v in out["metrics"].values())


def test_decide_discordant_when_half_reverse():
    pairs = [_pair("a", -0.2, 0.1, 0.0), _pair("b", -0.2, 0.0, 0.0),
             _pair("c", 0.2, 0.9, 0.0)]
    out = pp.decide(pairs)
    assert out["metrics"]["otsu_eta"]["verdict"] == "discordant"


def test_decide_inconclusive_with_too_few_pairs():
    out = pp.decide([_pair("a", 0.2, 1.0, 0.0), _pair("b", 0.2, 1.0, 0.0)])
    assert out["metrics"]["otsu_eta"]["verdict"] == "inconclusive"
    assert "required" in out["metrics"]["otsu_eta"]["reason"]


def test_decide_does_not_count_noisy_pipeline_as_concordant():
    # effect 0.1 but pipeline null 0.1: not distinguishable from resampling
    pairs = [_pair(f"p{i}", 0.1, 0.9, 0.1) for i in range(5)]
    assert pp.decide(pairs)["metrics"]["otsu_eta"]["verdict"] == \
        "inconclusive"


def test_decide_ignores_excluded_pairs():
    pairs = [_pair("a", 0.2, 1.0, 0.0), _pair("b", 0.2, 1.0, 0.0),
             _pair("c", 0.2, 1.0, 0.0),
             _pair("x", -9.0, 0.0, 0.0, included=False)]
    out = pp.decide(pairs)
    assert out["n_included_pairs"] == 3
    assert out["metrics"]["otsu_eta"]["verdict"] == "concordant"


# -- discovery ---------------------------------------------------------------
def _vol(px, kev, path):
    return {"properties": {"pixel_size_um": px, "energy_keV": kev},
            "data": [{"type": "ome-zarr", "origins": [{
                "path": path, "access_roots": [
                    {"url": "s3://vesuvius-challenge-open-data"}]}]}]}


def test_resolve_fixed_by_id_unique_match_and_ambiguity():
    vols = {"20260101000000": _vol(1.129, 59, "S/a/"),
            "20250101000000": _vol(2.399, 78, "S/b/"),
            "20250202000000": _vol(2.399, 77, "S/c/")}
    mov = "20260101000000"
    assert pp.resolve_fixed(vols, mov, "S-20250202000000_masked")[0] == \
        "20250202000000"
    assert pp.resolve_fixed(vols, mov, "X_2.399um_78keV_Y_masked")[0] == \
        "20250101000000"
    # same pixel size & energy twice -> ambiguous without a scanRadix
    vols["20250303000000"] = _vol(2.399, 78, "S/d/")
    fid, why = pp.resolve_fixed(vols, mov, "X_2.399um_78keV_Y_masked")
    assert fid is None and "ambiguous" in why
    # ...but a unique scanRadix match resolves it
    radix = {"20250101000000": "X_2.399um_78keV_Y",
             "20250303000000": "other"}
    fid, why = pp.resolve_fixed(vols, mov, "X_2.399um_78keV_Y_masked",
                                radix.get)
    assert fid == "20250101000000" and why == "scanRadix match"
    assert pp.resolve_fixed(vols, mov, "S-99999999999999_masked")[0] is None


def test_discover_reports_every_registered_volume_with_a_status():
    doc, *_ = reg_doc(scale=0.47)
    doc["fixed_volume"] = "X_2.399um_78keV_Y_masked"
    good = json.dumps(doc).encode()
    bad = json.dumps({"transformation_matrix": []}).encode()
    vols = {"20260101000000": _vol(1.129, 59, "S/mov/"),
            "20250101000000": _vol(2.399, 78, "S/fix/"),
            "20260202000000": _vol(1.129, 59, "S/broken/")}
    index = {"samples": {"S": {"volumes": vols}}}
    base = pp.BUCKET_URL
    blobs = {f"{base}/S/mov/transform.json": good,
             f"{base}/S/broken/transform.json": bad}
    specs = pp.discover(index, fetch=blobs.get)
    by = {s["moving_id"]: s for s in specs}
    assert set(by) == {"20260101000000", "20260202000000"}  # fixed has none
    assert by["20260101000000"]["status"] == "ok"
    assert by["20260101000000"]["fixed_id"] == "20250101000000"
    assert by["20260202000000"]["status"] == "registration_rejected"


def _spec(**kw):
    s = {"status": "ok", "px_moving_um": 1.129, "px_fixed_um": 2.399,
         "registration": {"direction": "moving_to_fixed",
                          "residual_mean_vox": 1.0}}
    s.update(kw)
    return s


def test_inclusion_rule():
    assert pp.inclusion(_spec())[0] is True
    ok, why, code = pp.inclusion(_spec(px_moving_um=2.0, px_fixed_um=2.399))
    assert not ok and code == "excluded" and "ratio" in why
    reg = {"direction": "moving_to_fixed", "residual_mean_vox": 43.0}
    ok, why, code = pp.inclusion(_spec(registration=reg))
    assert not ok and code == "residual"          # 43 vox * 2.399 um = 103 um
    ok, _, code = pp.inclusion(_spec(status="fixed_unresolved"))
    assert not ok and code == "excluded"


# -- registration geometry -----------------------------------------------------
def _aligned_correlation(pr, center):
    """Correlation of the two scans' cubes sampled via the registration."""
    n, step = 16, 1.0
    pts = pp.cube_grid_xyz(center, n, step)
    fixed, vf, _ = pp.sample_cube(pr.fixed, 0, pts, n)
    mv_pts = pr.registration.fixed_to_moving(pts.reshape(-1, 3)).reshape(
        pts.shape)
    moving, vm, _ = pp.sample_cube(pr.moving, 1, mv_pts, n)
    assert vf == 1.0 and vm == 1.0
    return float(np.corrcoef(fixed.ravel(), moving.ravel())[0, 1])


def test_registration_samples_the_same_physical_region():
    # same softness, so any residual mismatch is a geometry error
    pr = make_pair(fine_soft=0.3, coarse_soft=0.3)
    for center in ([24.0, 24.0, 24.0], [18.0, 30.0, 22.0]):
        assert _aligned_correlation(pr, center) > 0.9


def test_alignment_test_has_teeth_wrong_mapping_decorrelates(monkeypatch):
    pr = make_pair(fine_soft=0.3, coarse_soft=0.3)
    good = pr.registration.fixed_to_moving

    def wrong(pts):  # transpose x/y of the mapped points: a plausible bug
        out = good(pts)
        return out[:, [1, 0, 2]]

    monkeypatch.setattr(type(pr.registration), "fixed_to_moving",
                        lambda self, pts: wrong(pts))
    assert _aligned_correlation(pr, [24.0, 24.0, 24.0]) < 0.6


# -- deviations D1 / D2 (see artifacts/2026-10-01-protocol-pairs/README.md) ----
def test_partial_footprint_rescan_samples_efficiently_inside_the_overlap():
    # fixed scan is 2x wider per axis (8x the volume) than the rescan footprint
    pr = make_pair(fine_soft=0.05, coarse_soft=0.9, n_f=96)
    res = run(pr)
    assert res["ok"] and res["accepted"] == 10
    assert res["candidates_tried"] <= 25          # not 8x the budget
    # every accepted center lies inside the rescan's footprint in fixed voxels
    for r in res["regions"]:
        back = pr.registration.fixed_to_moving(
            np.array([r["center_fixed_xyz"]]))[0]
        assert (back >= 0).all() and (back <= 95).all()


def test_footprint_that_cannot_hold_a_cube_is_reported_not_crashed():
    pr = make_pair(fine_soft=0.05, coarse_soft=0.9)
    res = pp.run_pair(pr, seed=1, n_regions=4, target_um=4.0, cube_n=64)
    assert not res["ok"]
    assert "no full cube" in res["reason"] or "smaller than one cube" in \
        res["reason"]


def test_chunk_with_contradictory_size_rejects_regions_not_the_pair():
    pr = make_pair(fine_soft=0.05, coarse_soft=0.9)
    # a corner chunk, so only some candidate cubes touch it; it is stored 8x
    # too large, as observed in PHerc0343P
    key = "vol.zarr/1/0/0/0"
    assert key in pr.moving.store.data
    pr.moving.store.data[key] += b"\x01" * (7 * 16**3)
    pr.moving._cache.clear()
    res = run(pr)
    assert res["ok"] and res["accepted"] >= 1
    assert res["rejections"]["inconsistent_chunk"] >= 1


# -- post-hoc lattice-control arms (deviation D4) ---------------------------------
def test_grid_rotation_preserves_spacing_and_center():
    c = np.array([10.0, 20.0, 30.0])
    th = np.deg2rad(30.0)
    rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0],
                   [0, 0, 1]])
    g0 = pp.cube_grid_xyz(c, 5, 2.0)
    g1 = pp.cube_grid_xyz(c, 5, 2.0, rz)
    assert np.allclose(g1.reshape(-1, 3).mean(axis=0), c)
    # neighbour spacing along every lattice axis is unchanged
    for ax in range(3):
        d0 = np.linalg.norm(np.diff(g0, axis=ax), axis=-1)
        d1 = np.linalg.norm(np.diff(g1, axis=ax), axis=-1)
        assert np.allclose(d0, 2.0) and np.allclose(d1, 2.0)
    # a 90 degree rotation maps the lattice onto itself as a point set
    r90 = pp.cube_grid_xyz(c, 5, 2.0, ROT)
    key = lambda g: sorted(map(tuple, np.round(g.reshape(-1, 3), 6)))
    assert key(r90) == key(g0)


def test_arms_recover_ordering_under_a_non_axis_rotation():
    pr = make_pair(fine_soft=0.05, coarse_soft=0.9, n_f=96, rot_deg=30.0)
    res = run(pr)
    assert res["ok"] and res["accepted"] == 10
    assert all(r["arms"]["aligned"] and r["arms"]["rotated"]
               for r in res["regions"])
    for arm in ("aligned", "rotated"):
        for k in pp.PRIMARY_METRICS:
            a = res["arm_summary"][arm][k]
            assert a["n"] == 10 and a["median_d"] > 0
            assert a["frac_positive"] == 1.0
    # the registered rotation is the one the pair was built with
    q = pr.registration.lattice_rotation()
    assert abs(np.degrees(np.arctan2(q[1, 0], q[0, 0])) - 30.0) < 1e-3


def test_arms_show_no_difference_when_protocols_are_identical():
    pr = make_pair(fine_soft=0.3, coarse_soft=0.3, n_f=96, rot_deg=30.0)
    res = run(pr)
    for arm in ("aligned", "rotated"):
        for k in pp.PRIMARY_METRICS:
            assert abs(res["arm_summary"][arm][k]["median_d"]) < 0.1


def test_candidate_factor_caps_the_search():
    pr = make_pair(fine_soft=0.05, coarse_soft=0.9)
    res = pp.run_pair(pr, seed=1, n_regions=50, target_um=4.0, cube_n=16,
                      candidate_factor=1)
    assert res["candidates_tried"] <= 50 and res["candidate_factor"] == 1
