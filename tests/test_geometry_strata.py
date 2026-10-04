import copy
import json
import math

import numpy as np
import pytest
from PIL import Image

from scrollq.geometry_strata import (
    MEASURE_METHOD,
    StrataError,
    digest,
    evaluate_strata,
    main,
    measure_surface,
    measure_units,
    validate_spec,
)

CURV = (0.005, 0.03, 0.08)  # one representative value per bin of edges [0.01, 0.05]
METRIC = "bidirectional_coverage"


def _spec(**overrides):
    document = {
        "schema_version": 1,
        "dataset": "heldout-v1",
        "target": "PHerc-T",
        "measurement": {"method": MEASURE_METHOD, "reference": "ref-surface"},
        "metric": {"name": METRIC, "higher_is_better": True, "failure_value": 0.0},
        "bootstrap": {"samples": 400, "seed": 11},
        "covariates": [
            {
                "name": "mean_abs_curvature",
                "unit": "1/voxel",
                "edges": [0.01, 0.05],
                "hard_bins": [2],
                "min_rois_per_bin": 3,
                "min_target_fraction": 0.05,
                "low_coverage_ratio": 0.75,
                "max_unmeasured_fraction": 0.0,
                "margin": 0.0,
            }
        ],
    }
    document.update(overrides)
    return document


def _world(
    *,
    target_counts=(60, 30, 10),
    roi_counts=(20, 10, 5),
    delta=(0.1, 0.1, 0.1),
    spec=None,
    candidate_overrides=None,
    base_overrides=None,
):
    """Inventory, ROIs and paired baseline/candidate results with known effects."""
    spec = spec or _spec()
    inventory_units = [
        {"id": f"t{b}-{i}", "weight": 1.0, "covariates": {"mean_abs_curvature": CURV[b]}}
        for b, n in enumerate(target_counts)
        for i in range(n)
    ]
    rois, base_rows, cand_rows = [], [], []
    for b, n in enumerate(roi_counts):
        for i in range(n):
            rid = f"roi-{b}-{i}"
            rois.append({"id": rid, "weight": 1.0, "covariates": {"mean_abs_curvature": CURV[b]}})
            base = 0.5 + 0.01 * (-1) ** i
            cand = base + delta[b] + 0.005 * (-1) ** (i // 2)
            base_rows.append({"id": rid, "status": "ok", "metrics": {METRIC: base}})
            cand_rows.append({"id": rid, "status": "ok", "metrics": {METRIC: cand}})
    for rows, overrides in ((base_rows, base_overrides), (cand_rows, candidate_overrides)):
        for rid, override in (overrides or {}).items():
            index = next(k for k, r in enumerate(rows) if r["id"] == rid)
            if override is None:
                del rows[index]
            else:
                rows[index] = {"id": rid, **override}
    measurement = copy.deepcopy(spec["measurement"])
    return {
        "spec": spec,
        "inventory": {
            "schema_version": 1,
            "target": spec["target"],
            "measurement": measurement,
            "units": inventory_units,
        },
        "regions": {
            "schema_version": 1,
            "dataset": spec["dataset"],
            "measurement": copy.deepcopy(measurement),
            "regions": rois,
        },
        "baseline": {"schema_version": 1, "model": "baseline", "dataset": spec["dataset"],
                     "task": "segmentation", "regions": base_rows},
        "candidate": {"schema_version": 1, "model": "candidate", "dataset": spec["dataset"],
                      "task": "segmentation", "regions": cand_rows},
    }


def _evaluate(world):
    return evaluate_strata(
        world["spec"], world["inventory"], world["regions"], world["baseline"], world["candidate"]
    )


def _cov(report):
    return report["covariates"][0]


def _codes(report):
    return [r["code"] for r in _cov(report)["reasons"]]


def test_uniform_improvement_with_adequate_coverage_passes():
    report = _evaluate(_world())

    assert report["verdict"] == "STRATA_PASS"
    cov = _cov(report)
    assert cov["verdict"] == "GENERALIZES" and cov["reasons"] == []
    assert [b["state"] for b in cov["bins"]] == ["evaluated"] * 3
    assert cov["overall_improvement"]["mean"] == pytest.approx(0.1, abs=0.01)
    assert cov["overall_improvement"]["ci_low"] > 0


def test_bins_report_target_share_and_label_coverage():
    cov = _cov(_evaluate(_world()))
    easy, mid, hard = cov["bins"]

    assert [b["target"]["fraction"] for b in cov["bins"]] == [0.6, 0.3, 0.1]
    assert easy["labeled"]["rois"] == 20 and easy["labeled"]["fraction_of_bin"] == pytest.approx(1 / 3)
    assert hard["labeled"]["fraction_of_bin"] == 0.5
    assert cov["labeled_fraction_of_target"] == pytest.approx(0.35)
    # over-represented = ratio > 1: the hard bin is, the easy bin is not
    assert hard["labeled"]["representation_ratio"] == pytest.approx(0.5 / 0.35)
    assert easy["labeled"]["representation_ratio"] == pytest.approx((1 / 3) / 0.35)
    assert hard["hard"] is True and easy["hard"] is False
    assert easy["baseline_mean"] == pytest.approx(0.5, abs=0.01)
    assert easy["candidate_mean"] == pytest.approx(0.6, abs=0.01)


def test_improvement_confined_to_the_easy_stratum_is_blocked():
    # Most labels sit in the easy bin; the hard bin is under-labelled and flat.
    world = _world(roi_counts=(40, 12, 4), delta=(0.12, 0.12, 0.0))
    report = _evaluate(world)

    cov = _cov(report)
    assert report["verdict"] == "STRATA_BLOCKED"
    assert "HARD_STRATUM_NOT_IMPROVED" in _codes(report)
    # the labeled-set aggregate still looks like a clear win
    assert cov["overall_improvement"]["ci_low"] > 0.05
    # while the target-weighted estimate, which re-weights to the actual
    # scroll, is smaller than the labeled-set mean
    assert (
        cov["target_weighted_improvement"]["estimate"]
        < cov["overall_improvement"]["mean"]
    )


def test_a_thin_flat_stratum_blocks_even_when_the_big_and_hard_strata_improve():
    # The mid bin is 30% of the target but only 5 labels (0.48x the average
    # label density) and flat. The easy bin is the largest and barely below
    # average density; it must not dilute the thin stratum away.
    report = _evaluate(_world(roi_counts=(20, 5, 10), delta=(0.12, 0.0, 0.12)))

    cov = _cov(report)
    assert report["verdict"] == "STRATA_BLOCKED"
    assert _codes(report) == ["UNDER_REPRESENTED_STRATUM_NOT_IMPROVED"]
    assert [b["under_represented"] for b in cov["bins"]] == [False, True, False]
    assert cov["overall_improvement"]["ci_low"] > 0.05  # the aggregate hides it


def test_a_flat_but_well_covered_easy_stratum_does_not_block():
    # Same flat mid bin, but now well-labelled (ratio ~1.08) and not hard: a
    # saturated baseline there is allowed as long as nothing regresses.
    report = _evaluate(_world(roi_counts=(20, 12, 5), delta=(0.12, 0.0, 0.12)))

    assert report["verdict"] == "STRATA_PASS"
    assert _cov(report)["bins"][1]["under_represented"] is False


def test_improvement_is_judged_on_the_target_not_on_the_labeled_set():
    # Labels are mostly the saturated easy bin (flat). The thin and hard strata
    # both improve by 0.1, so every per-stratum rule is satisfied, but on the
    # actual scroll the gain is only 0.3*0.1 + 0.1*0.1 = 0.04.
    spec = _spec()
    spec["covariates"][0]["margin"] = 0.05
    world = _world(roi_counts=(60, 12, 8), delta=(0.0, 0.1, 0.1), spec=spec)
    report = _evaluate(world)

    cov = _cov(report)
    assert _codes(report) == ["TARGET_WEIGHTED_NOT_IMPROVED"]
    assert cov["target_weighted_improvement"]["estimate"] == pytest.approx(0.04, abs=0.005)
    assert cov["overall_improvement"]["mean"] == pytest.approx(0.025, abs=0.005)

    spec["covariates"][0]["margin"] = 0.0
    assert _evaluate(_world(roi_counts=(60, 12, 8), delta=(0.0, 0.1, 0.1), spec=spec))[
        "verdict"
    ] == "STRATA_PASS"


def test_a_required_stratum_with_too_few_rois_blocks_even_if_all_else_improves():
    report = _evaluate(_world(roi_counts=(20, 10, 0)))

    cov = _cov(report)
    assert report["verdict"] == "STRATA_BLOCKED"
    assert cov["primary_reason"] == "UNDER_EVALUATED_STRATUM"
    assert cov["bins"][2]["state"] == "under-evaluated"
    assert cov["bins"][2]["improvement"]["ci_low"] is None


def test_a_negligible_target_stratum_is_not_required():
    # bin 2 is 2% of the target (< 5%) and has no ROIs: nothing to evaluate.
    world = _world(target_counts=(60, 38, 2), roi_counts=(20, 10, 0))
    spec = copy.deepcopy(world["spec"])
    spec["covariates"][0]["hard_bins"] = [1]
    world = _world(target_counts=(60, 38, 2), roi_counts=(20, 10, 0), spec=spec)

    report = _evaluate(world)
    assert report["verdict"] == "STRATA_PASS"
    assert _cov(report)["bins"][2]["state"] == "negligible"


def test_significant_regression_in_any_stratum_is_blocked():
    report = _evaluate(_world(delta=(0.12, -0.12, 0.12)))

    assert "REGRESSION_IN_STRATUM" in _codes(report)
    assert report["verdict"] == "STRATA_BLOCKED"


def test_failed_and_missing_regions_stay_in_the_denominator():
    clean = _evaluate(_world())
    # candidate fails the first hard ROI and never emits the second
    failing = _world(
        candidate_overrides={
            "roi-2-0": {"status": "failed", "reason": "no surface"},
            "roi-2-1": None,
        }
    )
    report = _evaluate(failing)

    assert report["arm_failures"]["candidate"] == {"failed": ["roi-2-0"], "missing": ["roi-2-1"]}
    assert report["arm_failures"]["baseline"] == {"failed": [], "missing": []}
    hard_clean = _cov(clean)["bins"][2]["improvement"]["mean"]
    hard_failing = _cov(report)["bins"][2]["improvement"]["mean"]
    assert hard_failing < hard_clean - 0.2  # failure_value 0 replaced ~0.6 for 2 of 5 ROIs
    assert _cov(report)["bins"][2]["improvement"]["n"] == 5  # nothing dropped
    assert report["verdict"] == "STRATA_BLOCKED"


def test_lower_is_better_metrics_flip_the_sign_of_improvement():
    spec = _spec(metric={"name": METRIC, "higher_is_better": False, "failure_value": 1.0})
    better = _evaluate(_world(delta=(-0.1, -0.1, -0.1), spec=spec))
    worse = _evaluate(_world(delta=(0.1, 0.1, 0.1), spec=spec))

    assert better["verdict"] == "STRATA_PASS"
    assert _cov(better)["overall_improvement"]["mean"] == pytest.approx(0.1, abs=0.01)
    assert worse["verdict"] == "STRATA_BLOCKED"
    assert "REGRESSION_IN_STRATUM" in _codes(worse)


def test_unmeasured_target_and_unmeasured_rois_block():
    world = _world()
    for unit in world["inventory"]["units"][:5]:
        unit["covariates"]["mean_abs_curvature"] = None
    report = _evaluate(world)
    assert "UNMEASURED_TARGET" in _codes(report)
    assert _cov(report)["unmeasured"]["target_fraction"] == pytest.approx(0.05)

    world = _world()
    world["regions"]["regions"][0]["covariates"]["mean_abs_curvature"] = None
    report = _evaluate(world)
    assert "UNMEASURED_ROI" in _codes(report)
    assert _cov(report)["unmeasured"]["rois"] == ["roi-0-0"]
    # the allowance is a frozen parameter, not a default
    spec = _spec()
    spec["covariates"][0]["max_unmeasured_fraction"] = 0.1
    world = _world(spec=spec)
    for unit in world["inventory"]["units"][:5]:
        unit["covariates"]["mean_abs_curvature"] = None
    assert "UNMEASURED_TARGET" not in _codes(_evaluate(world))


def test_rois_must_be_a_subset_of_the_inventory():
    report = _evaluate(_world(target_counts=(60, 30, 10), roi_counts=(70, 10, 5)))
    assert "INVENTORY_DOES_NOT_CONTAIN_ROIS" in _codes(report)
    assert report["verdict"] == "STRATA_BLOCKED"


def test_bin_edges_are_half_open_with_open_outer_bins():
    spec = _spec()
    world = _world(spec=spec)
    edges_world = [
        ("below", 0.0, 0), ("at-first-edge", 0.01, 1),
        ("between", 0.04999, 1), ("at-last-edge", 0.05, 2), ("above", 9.0, 2),
    ]
    for name, value, expected in edges_world:
        probe = copy.deepcopy(world)
        for unit in probe["inventory"]["units"]:
            unit["covariates"]["mean_abs_curvature"] = value
        bins = _cov(_evaluate(probe))["bins"]
        assert bins[expected]["target"]["units"] == 100, name


def test_target_weighted_estimate_reweights_to_the_scroll():
    report = _evaluate(_world(roi_counts=(30, 10, 10), delta=(0.2, 0.1, 0.0)))
    cov = _cov(report)
    means = [b["improvement"]["mean"] for b in cov["bins"]]
    expected = 0.6 * means[0] + 0.3 * means[1] + 0.1 * means[2]

    weighted = cov["target_weighted_improvement"]
    assert weighted["supported_target_fraction"] == pytest.approx(1.0)
    assert weighted["estimate"] == pytest.approx(expected)
    assert weighted["ci_low"] < weighted["estimate"] < weighted["ci_high"]


def test_report_is_deterministic_and_hash_binds_inputs():
    a = _evaluate(_world())
    b = _evaluate(_world())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    json.dumps(a, allow_nan=False)

    changed = _world()
    changed["spec"]["bootstrap"]["seed"] = 12
    assert _evaluate(changed)["spec_sha256"] != a["spec_sha256"]
    assert a["spec_sha256"] == digest(_world()["spec"])


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda s: s["covariates"][0].update(edges=[0.05, 0.01]), "strictly increasing"),
        (lambda s: s["covariates"][0].update(edges=[]), "non-empty"),
        (lambda s: s["covariates"][0].update(hard_bins=[]), "at least one distinct bin"),
        (lambda s: s["covariates"][0].update(hard_bins=[3]), "at least one distinct bin"),
        (lambda s: s["covariates"][0].update(hard_bins=[1, 1]), "at least one distinct bin"),
        (lambda s: s["covariates"][0].update(min_rois_per_bin=2), "integer >= 3"),
        (lambda s: s["covariates"][0].update(min_target_fraction=0.0), "must be in"),
        (lambda s: s["covariates"][0].update(max_unmeasured_fraction=1.5), "must be in"),
        (lambda s: s["covariates"][0].update(low_coverage_ratio=0.0), "must be in"),
        (lambda s: s["covariates"][0].pop("low_coverage_ratio"), "must be a number"),
        (lambda s: s["covariates"][0].update(margin=-0.1), "margin must be >= 0"),
        (lambda s: s["covariates"].append(dict(s["covariates"][0])), "duplicate covariate"),
        (lambda s: s.update(bootstrap={"samples": 10, "seed": 1}), "samples must be"),
        (lambda s: s.update(metric={"name": METRIC, "failure_value": 0}), "higher_is_better"),
        (lambda s: s.update(schema_version=2), "schema_version"),
        (lambda s: s.update(measurement={"method": "m"}), "reference"),
        (lambda s: s.update(covariates=[]), "non-empty"),
    ],
)
def test_underspecified_specs_are_rejected(mutate, message):
    spec = _spec()
    mutate(spec)
    with pytest.raises(StrataError, match=message):
        validate_spec(spec)


def test_inconsistent_documents_are_rejected():
    world = _world()
    world["inventory"]["measurement"]["reference"] = "another-surface"
    with pytest.raises(StrataError, match="one method on one reference"):
        _evaluate(world)

    world = _world()
    world["regions"]["dataset"] = "other"
    with pytest.raises(StrataError, match="regions.dataset"):
        _evaluate(world)

    world = _world()
    world["inventory"]["target"] = "other-scroll"
    with pytest.raises(StrataError, match="inventory.target"):
        _evaluate(world)

    world = _world()
    world["candidate"]["model"] = "baseline"
    with pytest.raises(StrataError, match="different models"):
        _evaluate(world)

    world = _world()
    world["candidate"]["regions"].append(
        {"id": "roi-not-committed", "status": "ok", "metrics": {METRIC: 1.0}}
    )
    with pytest.raises(StrataError, match="outside the committed ROI set"):
        _evaluate(world)

    world = _world()
    world["candidate"]["regions"].append(dict(world["candidate"]["regions"][0]))
    with pytest.raises(StrataError, match="repeats region"):
        _evaluate(world)

    world = _world()
    world["candidate"]["regions"][0] = {"id": "roi-0-0", "status": "ok", "metrics": {"other": 1}}
    with pytest.raises(StrataError, match="primary metric"):
        _evaluate(world)

    world = _world()
    world["candidate"]["dataset"] = "other"
    with pytest.raises(StrataError, match="candidate.dataset"):
        _evaluate(world)

    world = _world(roi_counts=(1, 1, 0))
    with pytest.raises(StrataError, match="at least 3 committed ROIs"):
        _evaluate(world)


# --- geometry measurement -------------------------------------------------


def _save_surface(root, x, y, z):
    root.mkdir(parents=True)
    for name, arr in (("x.tif", x), ("y.tif", y), ("z.tif", z)):
        Image.fromarray(np.asarray(arr, dtype=np.float32)).save(root / name)
    (root / "meta.json").write_text(json.dumps({"format": "tifxyz", "scale": [1, 1]}))
    return root


def _cylinder(root, radius=50.0, rows=12, cols=24, step=2.0):
    phi = np.arange(cols) * (step / radius)
    zz = np.arange(rows) * step + 10.0
    x = radius * np.cos(phi)[None, :] + 0 * zz[:, None] + 100
    y = radius * np.sin(phi)[None, :] + 0 * zz[:, None] + 100
    z = zz[:, None] + 0 * phi[None, :]
    return _save_surface(root, x, y, z)


def _mean(measure, key):
    values = measure[key][measure["ok"]]
    return float(np.nanmean(values))


def test_plane_has_zero_curvature_and_known_tilt(tmp_path):
    rows, cols = 10, 10
    jj, ii = np.meshgrid(np.arange(cols) * 2.0, np.arange(rows) * 2.0)
    flat = _save_surface(tmp_path / "flat", jj, ii, np.full((rows, cols), 10.0))
    m = measure_surface(flat)
    assert _mean(m, "curvature") == pytest.approx(0.0, abs=1e-6)
    assert _mean(m, "tilt_deg") == pytest.approx(90.0)  # normal along z

    alpha = math.radians(60)  # sheet spanned by (cos a, 0, sin a) and y
    s = jj
    tilted = _save_surface(
        tmp_path / "tilted", s * math.cos(alpha) + 5, ii + 1, s * math.sin(alpha) + 10
    )
    assert _mean(measure_surface(tilted), "tilt_deg") == pytest.approx(90 - 60, abs=1e-3)


def test_cylinder_curvature_reads_one_over_two_radius(tmp_path):
    for radius in (30.0, 80.0):
        m = measure_surface(_cylinder(tmp_path / f"c{int(radius)}", radius=radius))
        assert _mean(m, "curvature") == pytest.approx(1 / (2 * radius), rel=0.02)
        assert _mean(m, "tilt_deg") == pytest.approx(0.0, abs=1e-3)  # axis along z


def test_sphere_curvature_reads_one_over_radius(tmp_path):
    radius = 60.0
    rows, cols, step = 12, 12, 2.0
    theta = (np.arange(rows)[:, None] * step / radius) + math.radians(70)
    phi = np.arange(cols)[None, :] * step / radius
    x = radius * np.sin(theta) * np.cos(phi) + 200
    y = radius * np.sin(theta) * np.sin(phi) + 200
    z = radius * np.cos(theta) + 0 * phi + 200
    m = measure_surface(_save_surface(tmp_path / "sphere", x, y, z))
    assert _mean(m, "curvature") == pytest.approx(1 / radius, rel=0.03)


def test_measure_units_tiles_conserve_area_and_skip_empty_tiles(tmp_path):
    cyl = _cylinder(tmp_path / "cyl")
    whole = measure_units({"S": cyl}, tile=0)
    tiled = measure_units({"S": cyl}, tile=8)

    assert [u["id"] for u in whole] == ["S"]
    assert len(tiled) > 1 and all(u["id"].startswith("S:r") for u in tiled)
    assert sum(u["weight"] for u in tiled) == pytest.approx(whole[0]["weight"])
    # one unit per surface also works as ROI input, with both covariates measured
    assert set(whole[0]["covariates"]) == {"mean_abs_curvature", "axis_tilt_deg"}
    assert whole[0]["covariates"]["mean_abs_curvature"] == pytest.approx(0.01, rel=0.02)

    hollow = _save_surface(
        tmp_path / "hollow", *(np.full((6, 6), -1.0) for _ in range(3))
    )
    with pytest.raises(StrataError, match="nothing was measured"):
        measure_units({"H": hollow})
    with pytest.raises(StrataError, match="tile"):
        measure_units({"S": cyl}, tile=-1)


# --- CLI -------------------------------------------------------------------


def _write_world(tmp_path, world):
    paths = {}
    for key, document in world.items():
        paths[key] = tmp_path / f"{key}.json"
        paths[key].write_text(json.dumps(document))
    return paths


def _evaluate_args(paths, out, *extra):
    return [
        "evaluate",
        "--spec", str(paths["spec"]),
        "--inventory", str(paths["inventory"]),
        "--regions", str(paths["regions"]),
        "--baseline", str(paths["baseline"]),
        "--candidate", str(paths["candidate"]),
        "--out", str(out),
        *extra,
    ]


def test_cli_exit_codes_spec_pin_and_create_only(tmp_path, capsys):
    passing = _write_world(tmp_path / "pass", _make(tmp_path / "pass", _world()))
    blocked = _write_world(
        tmp_path / "blocked",
        _make(tmp_path / "blocked", _world(roi_counts=(40, 12, 4), delta=(0.12, 0.12, 0.0))),
    )

    assert main(["spec-hash", "--spec", str(passing["spec"])]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == digest(json.loads(passing["spec"].read_text()))

    out = tmp_path / "pass.out.json"
    assert main(_evaluate_args(passing, out, "--expect-spec-sha256", printed)) == 0
    assert json.loads(out.read_text())["verdict"] == "STRATA_PASS"
    assert "STRATA_PASS" in capsys.readouterr().out

    assert main(_evaluate_args(blocked, tmp_path / "blocked.out.json")) == 1
    assert "blocked on mean_abs_curvature" in capsys.readouterr().out

    for argv in (
        _evaluate_args(passing, out),  # create-only
        _evaluate_args(passing, tmp_path / "x.json", "--expect-spec-sha256", "0" * 64),
    ):
        with pytest.raises(SystemExit) as error:
            main(argv)
        assert error.value.code == 2
    assert not (tmp_path / "x.json").exists()


def _make(folder, world):
    folder.mkdir(parents=True, exist_ok=True)
    return world


def test_cli_measure_writes_inventory_and_regions_with_one_measurement(tmp_path, capsys):
    cyl = _cylinder(tmp_path / "cyl")
    inventory = tmp_path / "inventory.json"
    regions = tmp_path / "regions.json"
    base = ["measure", "--surface", f"S={cyl}", "--reference", "ref-surface"]

    assert main([*base, "--as", "inventory", "--target", "PHerc-T", "--tile", "8",
                 "--out", str(inventory)]) == 0
    assert main([*base, "--as", "regions", "--dataset", "heldout-v1",
                 "--out", str(regions)]) == 0
    capsys.readouterr()

    inv = json.loads(inventory.read_text())
    reg = json.loads(regions.read_text())
    assert inv["target"] == "PHerc-T" and len(inv["units"]) > 1
    assert reg["dataset"] == "heldout-v1" and [r["id"] for r in reg["regions"]] == ["S"]
    assert inv["measurement"] == reg["measurement"] == {
        "method": MEASURE_METHOD, "reference": "ref-surface"}

    for argv in (
        [*base, "--as", "inventory", "--out", str(tmp_path / "a.json")],  # no --target
        [*base, "--as", "regions", "--out", str(tmp_path / "b.json")],  # no --dataset
        ["measure", "--surface", "nopath", "--reference", "r", "--as", "regions",
         "--dataset", "d", "--out", str(tmp_path / "c.json")],
        [*base, "--as", "regions", "--dataset", "d", "--out", str(inventory)],  # exists
    ):
        with pytest.raises(SystemExit) as error:
            main(argv)
        assert error.value.code == 2
