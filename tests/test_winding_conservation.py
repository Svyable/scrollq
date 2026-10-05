import json

import numpy as np
import pytest

from scrollq import winding_conservation as wc

SMALL = {
    **wc.SYNTHETIC,
    "windings": 10,
    "z_range": [0.0, 128.0],
    "theta_step_degrees": 2.0,
    "compression": {"windings": [3, 6], "factor": 0.65, "theta_center_degrees": 200.0,
                    "theta_half_width_degrees": 60.0, "z_center": 64.0, "z_half_width": 48.0},
}


@pytest.fixture(scope="module")
def small():
    return wc.synthetic_solution(SMALL)


def _measure(solution, umbilicus, **kwargs):
    return wc.measure(solution, umbilicus, z_origin=0.0, **kwargs)


def test_clean_synthetic_is_consistent_and_reports_pitch(small):
    solution, umbilicus = small
    report = _measure(solution, umbilicus, voxel_um=8.64)
    assert report["status"] == "consistent"
    assert report["flagged_cells"] == 0
    assert report["cells_evaluated"] == 72 * 8
    assert report["label_orientation"] == 1
    pitch = report["pitch"]
    assert 19.0 < pitch["median_voxels"] < 21.0
    assert pitch["median_um"] == pytest.approx(pitch["median_voxels"] * 8.64)
    assert pitch["iqr_um"][0] < pitch["median_um"] < pitch["iqr_um"][1]


@pytest.mark.parametrize(
    "kind, families",
    [
        ("delete", {"layer_count", "pitch"}),
        ("duplicate", {"layer_count", "continuity"}),
        ("merge", {"pitch", "continuity"}),
        ("switch", {"layer_count", "pitch", "continuity"}),
    ],
)
def test_each_planted_defect_fires_its_invariants(small, kind, families):
    solution, umbilicus = small
    planted = wc.plant_defect(solution, umbilicus, kind=kind, k=4, theta0=40.0, dtheta=45.0,
                              z0=32.0, dz=64.0)
    report = _measure(planted, umbilicus)
    fired = {f for f, n in report["flagged_cells_by_family"].items() if n}
    assert families <= fired
    # Every flagged cell touches the footprint dilated by one cell.
    for row in report["flagged"]:
        assert 1 <= row["z_bin"] <= 6
        assert 7 <= row["theta_bin"] <= 18


def test_defects_leave_points_outside_the_footprint_untouched(small):
    solution, umbilicus = small
    inside, _, _ = wc._footprint(solution, umbilicus, 0.0, 40.0, 45.0, 32.0, 64.0)
    outside = {tuple(p) + (w,) for p, w in zip(solution.xyz[~inside].round(6),
                                               solution.winding[~inside])}
    for kind in wc.DEFECTS:
        planted = wc.plant_defect(solution, umbilicus, kind=kind, k=4, theta0=40.0, dtheta=45.0,
                                  z0=32.0, dz=64.0)
        got = {tuple(p) + (w,) for p, w in zip(planted.xyz.round(6), planted.winding)}
        assert outside <= got, kind


def test_merge_halves_the_gap_and_relabels_outer_windings(small):
    solution, umbilicus = small
    planted = wc.plant_defect(solution, umbilicus, kind="merge", k=4, theta0=40.0, dtheta=45.0,
                              z0=32.0, dz=64.0)
    inside, radius, _ = wc._footprint(planted, umbilicus, 0.0, 40.0, 45.0, 32.0, 64.0)
    labels = set(planted.winding[inside].tolist())
    assert labels == set(range(9))  # one identity fewer inside the footprint
    assert set(planted.winding[~inside].tolist()) == set(range(10))


def test_reversed_label_orientation_is_handled(small):
    solution, umbilicus = small
    flipped = wc.Solution(solution.xyz, -solution.winding)
    clean = _measure(flipped, umbilicus)
    assert clean["label_orientation"] == -1
    # With labels decreasing outward the same sheet is one label lower after the cut.
    assert clean["status"] == "consistent"
    planted = wc.plant_defect(flipped, umbilicus, kind="duplicate", k=-4, theta0=40.0,
                              dtheta=45.0, z0=32.0, dz=64.0, orientation=-1)
    assert _measure(planted, umbilicus)["flagged_cells_by_family"]["layer_count"] > 0


def test_wrong_branch_cut_is_loud_not_silent(small):
    solution, umbilicus = small
    report = _measure(solution, umbilicus, branch_cut_degrees=90.0)
    assert report["status"] == "review"
    assert report["flagged_cells_by_family"]["continuity"] > 0


def test_empty_solution_is_not_evaluated(small):
    _, umbilicus = small
    empty = wc.Solution(np.empty((0, 3)), np.empty(0, dtype=np.int64))
    assert _measure(empty, umbilicus)["status"] == "not-evaluated"


def test_solution_rejects_fractional_labels():
    with pytest.raises(ValueError):
        wc.Solution(np.zeros((2, 3)), np.array([0.5, 1.0]))


def test_unknown_defect_is_rejected(small):
    solution, umbilicus = small
    with pytest.raises(ValueError):
        wc.plant_defect(solution, umbilicus, kind="shear", k=4, theta0=0, dtheta=10, z0=0, dz=16)


def test_windowed_measure_matches_full_measure(small):
    solution, umbilicus = small
    planted = wc.plant_defect(solution, umbilicus, kind="switch", k=5, theta0=350.0, dtheta=30.0,
                              z0=48.0, dz=32.0)
    full = _measure(planted, umbilicus, max_flagged_cells=10**6)
    window = wc._window(350.0, 30.0, 48.0, 32.0, 0.0, wc.THETA_BINS, wc.Z_BIN, 8)
    part = _measure(planted, umbilicus, cell_window=window, max_flagged_cells=10**6)
    z0, z1, t0, t1 = window
    expected = [
        (r["z_bin"], r["theta_bin"], r["flags"]) for r in full["flagged"]
        if z0 <= r["z_bin"] <= z1 and (r["theta_bin"] >= t0 or r["theta_bin"] <= t1)
    ]
    got = [(r["z_bin"], r["theta_bin"], r["flags"]) for r in part["flagged"]]
    assert sorted(got, key=str) == sorted(expected, key=str)
    assert got


def test_calibration_is_deterministic_and_reports_a_frontier(small):
    solution, umbilicus = small
    kwargs = dict(seed=3, theta_extents=(5.0, 45.0), z_extents=(64.0,), placements=3,
                  defects=("delete", "switch"))
    first = wc.calibrate(solution, umbilicus, **kwargs)
    second = wc.calibrate(solution, umbilicus, **kwargs)
    assert first == second
    assert len(first["rows"]) == 4
    assert first["clean"]["status"] == "consistent"
    big = next(r for r in first["rows"]
               if r["defect"] == "delete" and r["dtheta_degrees"] == 45.0)
    assert big["detection_rate"]["any"] == 1.0
    assert big["null_rate"]["any"] == 0.0
    frontier = first["smallest_reliable_extent"]["delete"]["any"]
    assert frontier[0]["smallest_reliable"]["dtheta_degrees"] in (5.0, 45.0)


def test_cli_measure_runs_positive_control_and_is_create_only(tmp_path, small):
    solution, _ = small
    npz = tmp_path / "solution.npz"
    np.savez(npz, xyz=solution.xyz, winding=solution.winding)
    umb = tmp_path / "umbilicus.json"
    umb.write_text(json.dumps(wc._synthetic_umbilicus_doc()))
    out = tmp_path / "report.json"
    argv = ["measure", "--solution", str(npz), "--umbilicus", str(umb), "--voxel-um", "8.64",
            "--out", str(out)]
    assert wc.main(argv) == 0
    report = json.loads(out.read_text())
    assert report["status"] == "consistent"
    assert report["positive_control"]["detected"] is True
    assert len(report["solution"]["sha256"]) == 64
    with pytest.raises(SystemExit):
        wc.main(argv)


def test_cli_help_needs_no_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        wc.main(["--help"])
    assert exc.value.code == 0
    assert "conservation" in capsys.readouterr().out.lower()


def test_switch_keeps_every_vertex_on_a_real_sheet(small):
    # The switched surface reuses the neighbouring sheet's own vertices, so
    # any local CT-seating measure is unchanged; only identity is wrong.
    solution, umbilicus = small
    planted = wc.plant_defect(solution, umbilicus, kind="switch", k=4, theta0=40.0, dtheta=45.0,
                              z0=32.0, dz=64.0)
    original = {tuple(p) for p in solution.xyz.round(6)}
    assert {tuple(p) for p in planted.xyz.round(6)} <= original
    assert _measure(planted, umbilicus)["status"] == "review"
