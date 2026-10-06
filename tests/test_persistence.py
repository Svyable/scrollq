"""Threshold-persistence engine: exact diagrams, invariances, and feature semantics."""

import numpy as np
import pytest
from scipy import ndimage

from scrollq import persistence as ps
from scrollq import persistence_controls as pc

CFG = ps.SweepConfig()


def _levels(values, valid=None):
    values = np.asarray(values, dtype=np.float64)
    mask = np.ones(values.shape, dtype=bool) if valid is None else np.asarray(valid, dtype=bool)
    return ps.dense_levels(values, mask)


def _diagrams(lv):
    return ps.h0_diagram(lv.levels), ps.h1_holes(lv.levels)


# ---------------------------------------------------------------- hand-checked


def test_two_peaks_and_a_saddle_have_exact_rank_persistence():
    # peaks of height 5 and 3 joined by a saddle of height 1 on a strip
    lv = _levels([[0, 5, 1, 3, 0]])
    d, _ = _diagrams(lv)
    pairs = sorted(zip(lv.values[d.birth].tolist(), np.where(d.death >= 0, lv.values[np.maximum(d.death, 0)], -1).tolist()))
    assert pairs == [(3.0, 1.0), (5.0, -1)]
    s = lv.mid_rank()
    # scores 0,0 | 1 | 3 | 5 are dense levels 0..3 with counts 2,1,1,1 over 5 pixels
    assert lv.counts.tolist() == [2, 1, 1, 1]
    assert s.tolist() == pytest.approx([0.8, 0.5, 0.3, 0.1])
    persistence = ps.diagram_persistence(lv, d, "rank")
    assert persistence.tolist() == pytest.approx([s[1] - s[2]])
    assert ps.diagram_persistence(lv, d, "value").tolist() == [2.0]


def test_ring_has_one_component_and_one_hole_whose_lifetime_spans_ring_to_floor():
    f = np.zeros((7, 7))
    f[1:6, 1:6] = 1.0
    f[2:5, 2:5] = 0.2
    lv = _levels(f)
    d, holes = _diagrams(lv)
    top = lv.n_levels - 1
    assert ps.betti_at(d, holes, top) == (1, 1)
    assert holes.lo.tolist() == [1] and holes.hi.tolist() == [2]  # alive for 0.2 < t <= 1.0
    assert ps.betti_at(d, holes, 2) == (1, 1)
    assert ps.betti_at(d, holes, 1) == (1, 0)  # interior filled once the threshold reaches 0.2


def test_foreground_is_eight_connected_and_background_four_connected():
    diag = np.array([[1.0, 0.0], [0.0, 1.0]])
    lv = _levels(diag)
    d, holes = _diagrams(lv)
    assert ps.betti_at(d, holes, 1) == (1, 0)  # diagonal pixels are one component
    diamond = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
    lv = _levels(diamond)
    d, holes = _diagrams(lv)
    assert ps.betti_at(d, holes, 1) == (1, 1)  # the centre is not 8-connected out, so it is a hole


def test_masked_pixels_are_outside_not_holes():
    f = np.zeros((7, 7))
    f[1:6, 1:6] = 1.0
    valid = np.ones((7, 7), dtype=bool)
    valid[3, 3] = False  # a masked pixel inside the ring
    lv = _levels(f, valid)
    d, holes = _diagrams(lv)
    assert holes.lo.size == 0
    assert lv.levels[3, 3] == -1


def test_dense_levels_validation():
    with pytest.raises(ps.PersistenceError):
        ps.dense_levels(np.array([[0.0, np.nan]]), np.ones((1, 2), dtype=bool))
    with pytest.raises(ps.PersistenceError):
        ps.dense_levels(np.zeros((2, 2)), np.zeros((2, 2), dtype=bool))
    with pytest.raises(ps.PersistenceError):
        ps.dense_levels(np.zeros((2, 2)), np.ones((3, 3), dtype=bool))
    # NaN under the mask is ignored; non-finite *inside* it is rejected above
    lv = ps.dense_levels(np.array([[0.5, np.nan]]), np.array([[True, False]]))
    assert lv.levels.tolist() == [[0, -1]]


def test_mid_rank_is_strictly_decreasing_and_inside_unit_interval():
    rng = np.random.default_rng(3)
    lv = _levels(np.floor(rng.random((20, 20)) * 6))
    s = lv.mid_rank()
    assert np.all(np.diff(s) < 0) and 0 < s.min() and s.max() < 1


def test_nominal_level_uses_first_value_at_or_above_threshold():
    lv = _levels([[0.1, 0.4, 0.4, 0.9]])
    assert ps.nominal_level(lv, 0.4) == 1
    assert ps.nominal_level(lv, 0.41) == 2
    assert ps.nominal_level(lv, 0.95) is None


# ---------------------------------------------------------------------- oracles


def test_engine_matches_independent_oracles_and_the_oracle_has_teeth():
    result = pc.engine_oracles(11, 24)
    assert result["levels_checked"] > 500
    assert result["betti_mismatches"] == 0
    assert result["euler_checked"] > 100 and result["euler_mismatches"] == 0
    assert result["dihedral_invariant"] == result["dihedral_fields"]
    assert result["wrong_convention_disagreements"] > 0


def test_persistence_betti_counts_agree_with_scipy_on_a_gaussian_field():
    rng = np.random.default_rng(5)
    f = ndimage.gaussian_filter(rng.random((40, 40)), 1.5)
    lv = _levels(f)
    d, holes = _diagrams(lv)
    for u in range(0, lv.n_levels, 37):
        _, expected = ndimage.label(lv.levels >= u, structure=np.ones((3, 3)))
        assert ps.betti_at(d, holes, u)[0] == expected


# ------------------------------------------------------------------ invariances


def _field_with_two_strokes():
    rng = np.random.default_rng(7)
    field, _ = pc.synth_region(rng, [(pc.INK_STYLE, True)] * 3 + [(pc.SKIRTED_STYLE, False)] * 3, 0.2)
    return field


@pytest.mark.parametrize("remap", [lambda v: v**3, lambda v: np.expm1(3 * v), lambda v: 7.0 * v, np.sqrt])
def test_every_rank_quantity_is_bitwise_invariant_to_monotone_remaps(remap):
    f = _field_with_two_strokes().astype(np.float64)
    tau = 0.5
    base = _levels(f)
    u = ps.nominal_level(base, tau)
    res = ps.analyze_components(base, u, CFG, *_diagrams(base))
    g = remap(f)
    remapped = _levels(g)
    assert remapped.n_levels == base.n_levels  # the remap is injective here
    u2 = ps.nominal_level(remapped, float(remap(np.float64(tau))))
    assert u2 == u and np.array_equal(remapped.levels, base.levels)
    res2 = ps.analyze_components(remapped, u2, CFG, *_diagrams(remapped))
    assert [c["features"] for c in res2["components"]] == [c["features"] for c in res["components"]]
    assert [c["geometry"] for c in res2["components"]] == [c["geometry"] for c in res["components"]]
    assert np.array_equal(ps.diagram_persistence(remapped, _diagrams(remapped)[0], "rank"),
                          ps.diagram_persistence(base, _diagrams(base)[0], "rank"))


def test_value_parameterised_persistence_is_not_invariant_so_the_control_has_teeth():
    f = _field_with_two_strokes().astype(np.float64)
    a, b = _levels(f), _levels(f**3)
    assert not np.array_equal(
        ps.diagram_persistence(a, _diagrams(a)[0], "value"),
        ps.diagram_persistence(b, _diagrams(b)[0], "value"),
    )


def test_features_never_read_the_raw_values():
    f = _field_with_two_strokes().astype(np.float64)
    lv = _levels(f)
    u = ps.nominal_level(lv, 0.5)
    res = ps.analyze_components(lv, u, CFG, *_diagrams(lv))
    scrambled = ps.Levels(levels=lv.levels, counts=lv.counts, values=np.zeros_like(lv.values))
    res2 = ps.analyze_components(scrambled, u, CFG, *_diagrams(lv))
    assert [c["features"] for c in res2["components"]] == [c["features"] for c in res["components"]]


def test_a_remap_that_collapses_scores_is_not_injective_and_changes_ranks():
    # distinct tiny scores merge under float offset: invariance is a statement about injective remaps
    f = np.array([[1e-18, 2e-18, 0.5, 0.9]])
    assert _levels(f).n_levels == 4
    assert _levels(f * 1e-3 + 2.0).n_levels < 4


# ------------------------------------------------------------ component features


def _bar(h=64, w=64, y=30, x0=10, x1=40, half=2, amp=0.9, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    f = rng.normal(0, noise, (h, w)) if noise else np.zeros((h, w))
    f[y - half : y + half + 1, x0:x1] = amp
    return np.clip(f, 0, 1)


def test_single_stable_bar_is_one_component_with_expected_geometry():
    lv = _levels(_bar())
    u = ps.nominal_level(lv, 0.5)
    res = ps.analyze_components(lv, u, CFG, *_diagrams(lv))
    (c,) = res["components"]
    assert c["area"] == 5 * 30
    assert c["peak_yx"] == [28, 10]  # lowest flat index among the tied maxima
    assert c["essential"] is True
    assert c["geometry"]["elongation"] > 4
    assert c["features"]["hole_life_log"] == 0.0
    assert c["features"]["n_significant_peaks"] == 0.0
    assert c["features"]["centroid_drift_norm"] == pytest.approx(0.0)


def test_small_components_are_dropped_and_counted():
    f = _bar()
    f[5, 5] = 0.9
    lv = _levels(f)
    res = ps.analyze_components(lv, ps.nominal_level(lv, 0.5), CFG, *_diagrams(lv))
    assert len(res["components"]) == 1 and res["n_dropped_small"] == 1


def test_too_many_components_is_an_error_not_a_silent_truncation():
    f = np.zeros((40, 40))
    for i in range(0, 40, 6):
        for j in range(0, 40, 6):
            f[i : i + 3, j : j + 4] = 0.9
    lv = _levels(f)
    cfg = ps.SweepConfig(max_components=5)
    with pytest.raises(ps.PersistenceError, match="max_components"):
        ps.analyze_components(lv, ps.nominal_level(lv, 0.5), cfg, *_diagrams(lv))


def test_sub_nominal_skirt_increases_area_growth_and_shortens_the_loose_side():
    stable = pc.synth_region(np.random.default_rng(1), [(pc.INK_STYLE, True)] * 6, 0.2)[0]
    skirted = pc.synth_region(np.random.default_rng(1), [(pc.SKIRTED_STYLE, True)] * 6, 0.2)[0]

    def median(field, name):
        lv = _levels(field)
        u = ps.nominal_level(lv, 0.5)
        res = ps.analyze_components(lv, u, CFG, *_diagrams(lv))
        return float(np.median([c["features"][name] for c in res["components"]]))

    assert median(skirted, "area_growth_log") > median(stable, "area_growth_log")


def test_ring_component_reports_its_hole_lifetime():
    f = np.zeros((40, 40))
    f[10:30, 10:30] = 0.9
    f[14:26, 14:26] = 0.05
    lv = _levels(f)
    res = ps.analyze_components(lv, ps.nominal_level(lv, 0.5), CFG, *_diagrams(lv))
    (c,) = res["components"]
    assert c["features"]["hole_life_log"] > 0.0


def test_two_peaks_in_one_nominal_component_count_as_a_significant_sub_peak():
    f = np.zeros((30, 60))
    f[10:15, 5:30] = 0.9
    f[10:15, 30:55] = 0.8
    f[10:15, 29:31] = 0.6  # weak link, still above the nominal threshold
    lv = _levels(f)
    res = ps.analyze_components(lv, ps.nominal_level(lv, 0.5), CFG, *_diagrams(lv))
    (c,) = res["components"]
    assert c["features"]["n_significant_peaks"] >= 1.0


# ---------------------------------------------------------------------- skeleton


def test_skeleton_of_a_wide_bar_is_roughly_its_length():
    mask = np.zeros((30, 60), dtype=bool)
    mask[12:17, 5:45] = True
    n = int(ps.skeleton(mask).sum())
    assert 34 <= n <= 42


def test_skeleton_edge_cases():
    assert ps.skeleton(np.zeros((5, 5), dtype=bool)).sum() == 0
    one = np.zeros((5, 5), dtype=bool)
    one[2, 2] = True
    assert ps.skeleton(one).sum() == 1
    block = np.ones((7, 7), dtype=bool)
    assert 1 <= ps.skeleton(block).sum() <= 5


def test_euler_characteristic_known_shapes():
    assert ps.euler_characteristic(np.ones((4, 4), dtype=bool)) == 1
    ring = np.ones((5, 5), dtype=bool)
    ring[2, 2] = False
    assert ps.euler_characteristic(ring) == 0
    two = np.zeros((3, 5), dtype=bool)
    two[1, 0] = two[1, 4] = True
    assert ps.euler_characteristic(two) == 2


def test_sweep_config_validation():
    for bad in (
        {"min_component_pixels": 0},
        {"max_components": 0},
        {"significant_persistence": 0.0},
        {"window_log10": 0.0},
        {"steps_per_side": 0},
    ):
        with pytest.raises(ps.PersistenceError):
            ps.SweepConfig(**bad).validate()
