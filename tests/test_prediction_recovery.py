from __future__ import annotations

import numpy as np
import pytest

from scrollq import prediction_recovery as pr


def test_boundary_anchors_have_four_disjoint_sides():
    rows = pr.boundary_anchor_cells((10, 31, 20, 41), ring_offset=2)

    assert len(rows["top"]) == 21
    assert len(rows["bottom"]) == 21
    assert len(rows["left"]) == 19
    assert len(rows["right"]) == 19
    all_cells = [cell for side in rows.values() for cell in side]
    assert len(all_cells) == len(set(all_cells))
    assert rows["top"][0] == (8, 20)
    assert rows["bottom"][-1] == (32, 40)


def test_connectivity_dilation_bridges_one_voxel_gap_not_remote_sheet():
    raw = np.zeros((9, 20, 20), dtype=bool)
    raw[4, 5:9, 5:15] = True
    raw[4, 10:15, 5:15] = True
    raw[8, 5:15, 5:15] = True

    labels, count = pr.label_connectivity(raw, dilation_iterations=1)

    assert count == 2
    assert labels[4, 7, 8] == labels[4, 12, 8]
    assert labels[8, 10, 10] != labels[4, 10, 10]


def test_component_selection_requires_all_four_sides_and_majority():
    labels = np.zeros((7, 7, 7), dtype=np.int32)
    labels[:, :, :4] = 1
    labels[:, :, 4:] = 2
    seeds = {
        "top": [[1, 1, 1], [2, 1, 1], [3, 1, 1]],
        "bottom": [[1, 5, 1], [2, 5, 1], [3, 5, 1]],
        "left": [[1, 3, 1], [2, 3, 1], [3, 3, 1]],
        "right": [[4, 3, 1], [5, 3, 1], [6, 3, 1]],
    }

    result = pr.select_seeded_component(labels, seeds)

    assert result["status"] == "selected"
    assert result["selected_label"] == 1
    assert result["eligible_component_count"] == 1
    assert result["valid_seed_count"] == 12


def test_component_selection_abstains_when_two_components_meet_rule():
    labels = np.zeros((8, 8, 8), dtype=np.int32)
    labels[:, :, :4] = 1
    labels[:, :, 4:] = 2
    seeds = {}
    for side in ("top", "bottom", "left", "right"):
        seeds[side] = (
            [[1, 1, 1], [2, 1, 1], [3, 1, 1]]
            + [[1, 1, 6], [2, 1, 6], [3, 1, 6]]
        )

    result = pr.select_seeded_component(
        labels,
        seeds,
        minimum_total_seed_share=0.5,
    )

    assert result["status"] == "abstain"
    assert result["selected_label"] is None
    assert result["eligible_component_count"] == 2


def test_raw_component_points_exclude_dilation_only_voxels():
    raw = np.zeros((5, 5, 5), dtype=bool)
    raw[2, 2, 1] = True
    raw[2, 2, 3] = True
    labels, count = pr.label_connectivity(raw, dilation_iterations=1)
    assert count == 1

    points = pr.raw_component_points(raw, labels, 1, origin_zyx=(10, 20, 30))

    assert {tuple(row) for row in points.tolist()} == {
        (12.0, 22.0, 31.0),
        (12.0, 22.0, 33.0),
    }


def test_snap_recovers_only_within_frozen_radius_and_reports_duplicates():
    component = np.array(
        [[0.0, 0.0, 0.0], [0.0, 0.0, 10.0], [0.0, 10.0, 0.0]]
    )
    coarse = np.array(
        [[0.0, 0.0, 1.0], [0.0, 0.0, 2.0], [100.0, 100.0, 100.0]]
    )

    result = pr.snap_to_component(
        coarse,
        component,
        maximum_distance_voxels=20,
    )

    assert result["available"].tolist() == [True, True, False]
    assert np.allclose(result["recovered_zyx"][0], [0, 0, 0])
    assert np.allclose(result["recovered_zyx"][1], [0, 0, 0])
    assert np.isnan(result["recovered_zyx"][2]).all()
    assert result["candidate_available_fraction"] == pytest.approx(2 / 3)
    assert result["unique_recovered_voxel_fraction"] == pytest.approx(0.5)


def test_prediction_recovery_primitives_have_no_hidden_truth_argument():
    # Candidate-generation helpers accept masks, labels, visible seeds and coarse
    # coordinates only. Hidden truth is intentionally absent from their APIs.
    import inspect

    names = {
        "boundary_anchor_cells",
        "label_connectivity",
        "select_seeded_component",
        "raw_component_points",
        "snap_to_component",
    }
    for name in names:
        parameters = inspect.signature(getattr(pr, name)).parameters
        assert "truth" not in parameters
        assert "reference_xyz" not in parameters
        assert "hidden_valid" not in parameters


def _scored_center(
    *,
    selected=True,
    availability=0.9,
    fraction8=0.9,
    median_error=4.0,
    p95=10.0,
    unique=0.8,
    wrong_rejected=True,
):
    return {
        "component_status": "selected" if selected else "abstain",
        "candidate_available_fraction": availability if selected else 0.0,
        "fraction_within_8_voxels": fraction8 if selected else 0.0,
        "median_error_voxels": median_error if selected else None,
        "p95_error_voxels": p95 if selected else None,
        "unique_recovered_voxel_fraction": unique if selected else 0.0,
        "wrong_wrap_rejected": wrong_rejected,
    }


def test_development_score_allows_one_abstention_but_keeps_it_in_median():
    centers = [_scored_center() for _ in range(5)] + [_scored_center(selected=False)]

    result = pr.score_development(centers)

    assert result["status"] == "pass"
    assert result["selected_component_center_count"] == 5
    assert result["median_fraction_within_8_voxels_across_all_centers"] == pytest.approx(0.9)
    assert all(result["checks"].values())


def test_development_score_fails_bad_selected_center_and_wrong_wrap():
    centers = [_scored_center() for _ in range(6)]
    centers[0] = _scored_center(availability=0.7, fraction8=0.4)
    centers[1]["wrong_wrap_rejected"] = False

    result = pr.score_development(centers)

    assert result["status"] == "fail"
    assert result["checks"]["candidate_available_fraction_every_selected_center"] is False
    assert result["checks"]["fraction_within_8_voxels_every_selected_center"] is False
    assert result["checks"]["wrong_wrap_controls_rejected"] is False
