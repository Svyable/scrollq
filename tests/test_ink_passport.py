import json

import numpy as np
import pytest
from PIL import Image

from scrollq import ink_passport as ip

CKPT = "ab" * 32
VOLUME = "PHercTEST/volumes/20260101000000-7.910um-test.zarr"
PPV = 4.0
GRID = (10, 12)  # rows, cols


def _surface(tmp_path, *, hole=None):
    root = tmp_path / "surface"
    root.mkdir(exist_ok=True)
    rr, cc = np.mgrid[0:GRID[0], 0:GRID[1]]
    x = (100 + 2 * cc).astype(np.float32)
    y = (200 + 2 * rr).astype(np.float32)
    z = np.full(GRID, 50.0, dtype=np.float32)
    if hole is not None:
        x[hole] = y[hole] = z[hole] = -1
    for name, arr in (("x.tif", x), ("y.tif", y), ("z.tif", z)):
        Image.fromarray(arr).save(root / name)
    return root


def _expected_zyx(row, col):
    gr = (row + 0.5) / PPV - 0.5
    gc = (col + 0.5) / PPV - 0.5
    return [50.0, 200 + 2 * gr, 100 + 2 * gc]


def _prediction(tmp_path, *, empty=False):
    pred = np.zeros((int(GRID[0] * PPV), int(GRID[1] * PPV)), dtype=np.float32)
    if not empty:
        pred[8:16, 8:16] = 0.9  # component 1
        pred[24:32, 32:44] = 0.7  # component 2
        pred[2, 40] = 0.95  # single pixel, below min size
    path = tmp_path / "pred.npy"
    np.save(path, pred)
    return path


def _regions_file(tmp_path, boxes, volume=VOLUME):
    path = tmp_path / "training.json"
    path.write_text(json.dumps({"region_sets": [{
        "id": "train-a", "role": "training", "volume_id": volume,
        "coordinate_space": "level0-voxel-index",
        "boxes": [{"start": s, "stop": e} for s, e in boxes]}]}))
    return path


def _build(tmp_path, **kwargs):
    defaults = dict(
        prediction_path=kwargs.pop("prediction_path", None) or _prediction(tmp_path),
        surface_path=kwargs.pop("surface_path", None) or _surface(tmp_path),
        pixels_per_vertex=PPV, volume_id=VOLUME, checkpoint_sha256=CKPT, threshold=0.5)
    defaults.update(kwargs)
    return ip.build_passport(**defaults)


def test_uv_to_ct_mapping_is_exact_on_a_linear_surface(tmp_path):
    from scrollq.tifxyz_audit import load_valid_vertices

    xyz, valid, _ = load_valid_vertices(_surface(tmp_path))
    rows = np.array([0, 9, 21, 39])
    cols = np.array([0, 13, 30, 47])
    ct, ok = ip.map_uv_to_ct(rows, cols, xyz, valid, PPV)
    assert ok.all()
    for k, (r, c) in enumerate(zip(rows, cols)):
        expected = _expected_zyx(r, c)
        # Edge pixels are clamped to the grid edge, interior pixels are exact.
        expected[1] = min(max(expected[1], 200.0), 200.0 + 2 * (GRID[0] - 1))
        expected[2] = min(max(expected[2], 100.0), 100.0 + 2 * (GRID[1] - 1))
        assert ct[k] == pytest.approx(expected)


def test_missing_evidence_stays_missing(tmp_path):
    passport = _build(tmp_path)
    assert passport["status"] == "incomplete"
    assert passport["components_found"] == 3
    assert passport["components_below_min_pixels"] == 1
    first, second = passport["units"]
    assert first["pixels"] == 64 and second["pixels"] == 96
    assert first["ink_score"]["mean"] == pytest.approx(0.9)
    assert first["training_exclusion"]["status"] == "unknown"
    assert first["relief_support"]["status"] == "not-measured"
    assert set(first["evidence_gaps"]) == {"training-exclusion-unknown", "relief-not-measured"}
    assert first["ct"]["centroid_zyx"] == pytest.approx(
        np.mean([_expected_zyx(r, c) for r in range(8, 16) for c in range(8, 16)], axis=0))
    assert first["uv_bbox_px"] == [8, 8, 16, 16]
    assert passport["inputs"]["model"]["checkpoint_sha256"] == CKPT
    assert len(passport["inputs"]["surface"]["coordinate_sha256"]) == 64


def test_training_overlap_is_tested_point_by_point(tmp_path):
    # Covers component 1 (y ~ 203-207, x ~ 103-107) but not component 2.
    regions = _regions_file(tmp_path, [([0, 202, 102], [100, 208, 108])])
    passport = _build(tmp_path, training_regions_path=regions)
    first, second = passport["units"]
    assert first["status"] == "training-overlap"
    assert first["training_exclusion"]["overlaps"][0]["points_inside"] == 64
    assert second["training_exclusion"]["status"] == "clear"
    assert passport["status"] == "training-overlap"


def test_box_touching_a_component_bbox_is_not_a_false_overlap(tmp_path):
    # Overlaps component 1's integer bbox but contains none of its points.
    regions = _regions_file(tmp_path, [([0, 207.9, 0], [100, 208, 300])])
    first = _build(tmp_path, training_regions_path=regions)["units"][0]
    assert first["training_exclusion"]["status"] == "clear"


def test_other_volume_training_cannot_overlap(tmp_path):
    regions = _regions_file(tmp_path, [([0, 0, 0], [1000, 1000, 1000])], volume="other.zarr")
    unit = _build(tmp_path, training_regions_path=regions)["units"][0]
    assert unit["training_exclusion"]["status"] == "clear"
    assert unit["training_exclusion"]["other_volume_region_sets"] == ["train-a"]


def test_relief_statistic_and_complete_status(tmp_path):
    relief = np.zeros((40, 48), dtype=np.float32)
    relief[24:32, 32:44] = 1.0
    relief_path = tmp_path / "relief.npy"
    np.save(relief_path, relief)
    regions = _regions_file(tmp_path, [([0, 0, 0], [10, 10, 10])])
    passport = _build(tmp_path, training_regions_path=regions, relief_path=relief_path,
                      relief_producer="synthetic test field")
    first, second = passport["units"]
    assert second["relief_support"]["delta"] == pytest.approx(1.0)
    assert first["relief_support"]["delta"] == pytest.approx(0.0)
    assert first["relief_support"]["standardized_delta"] is None  # constant field
    assert passport["status"] == "complete"
    assert passport["inputs"]["relief"]["producer"] == "synthetic test field"


def test_mesh_hole_leaves_pixels_unmapped(tmp_path):
    surface = _surface(tmp_path, hole=(slice(2, 4), slice(2, 4)))
    unit = _build(tmp_path, surface_path=surface)["units"][0]
    assert unit["ct"]["unmapped_pixels"] > 0
    assert "ct-mapping-incomplete" in unit["evidence_gaps"]


def test_reviewer_regions_are_units(tmp_path):
    regions = tmp_path / "letters.json"
    regions.write_text(json.dumps({"regions": [{"id": "col1-line2-char5",
                                                "bbox_px": [30, 22, 46, 34]}]}))
    units = _build(tmp_path, regions_path=regions)["units"]
    assert units[-1]["id"] == "col1-line2-char5"
    assert units[-1]["kind"] == "reviewer-region"
    assert units[-1]["pixels"] == 16 * 12
    regions.write_text(json.dumps({"regions": [{"id": "a", "bbox_px": [0, 0, 2, 2]},
                                               {"id": "a", "bbox_px": [0, 0, 2, 2]}]}))
    with pytest.raises(ValueError):
        _build(tmp_path, regions_path=regions)


def test_nothing_inspected_is_unverified(tmp_path):
    passport = _build(tmp_path, prediction_path=_prediction(tmp_path, empty=True))
    assert passport["status"] == "unverified"
    assert passport["units"] == []


@pytest.mark.parametrize("kwargs", [
    {"checkpoint_sha256": "not-a-hash"},
    {"pixels_per_vertex": 3.0},  # shape no longer matches the grid
    {"threshold": 1.5},
    {"relief_path": "x.npy"},  # no producer named
])
def test_bad_inputs_fail_closed(tmp_path, kwargs):
    with pytest.raises(ValueError):
        _build(tmp_path, **kwargs)


def test_cli_is_create_only(tmp_path):
    out = tmp_path / "passport.json"
    argv = ["--prediction", str(_prediction(tmp_path)), "--threshold", "0.5",
            "--surface", str(_surface(tmp_path)), "--pixels-per-vertex", "4",
            "--volume-id", VOLUME, "--checkpoint-sha256", CKPT, "--out", str(out)]
    assert ip.main(argv) == 0
    assert json.loads(out.read_text())["tool"] == "scroliq-ink-passport"
    with pytest.raises(SystemExit):
        ip.main(argv)


def test_help_needs_no_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        ip.main(["--help"])
    assert exc.value.code == 0
