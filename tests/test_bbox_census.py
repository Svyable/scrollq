import json

import numpy as np
import pytest
from PIL import Image

from scrollq import bbox_census
from scrollq.bbox_census import (
    BBoxCensusError,
    census,
    census_patch,
    find_patches,
    main,
    run_positive_control,
)


def _patch(root, name, *, z0=100.0, bbox="exact", z_grid=None, bad_meta=False):
    """4x4 planar patch, 2-voxel spacing, at z = z0 (or an explicit z grid)."""
    folder = root / name
    folder.mkdir(parents=True)
    yy, xx = np.mgrid[0:4, 0:4]
    z = np.full((4, 4), z0, np.float32) if z_grid is None else z_grid
    for fname, arr in (
        ("x.tif", (xx * 2).astype(np.float32)),
        ("y.tif", (yy * 2).astype(np.float32)),
        ("z.tif", z),
    ):
        Image.fromarray(arr).save(folder / fname)
    meta = {"format": "tifxyz", "scale": [0.5, 0.5]}
    if bbox == "exact":
        meta["bbox"] = [[0, 0, float(z.max())], [6, 6, float(z.max())]]
    elif bbox is not None:
        meta["bbox"] = bbox
    (folder / "meta.json").write_text("{not json" if bad_meta else json.dumps(meta))
    return folder


def _pack(tmp_path):
    root = tmp_path / "pack"
    _patch(root, "a-exact")
    _patch(root, "b-stale-z", z0=754.0, bbox=[[0, 0, 100], [6, 6, 100]])
    _patch(root, "c-stale-xz", z0=754.0, bbox=[[10, 0, 100], [16, 6, 100]])
    _patch(root, "d-undeclared", bbox=None)
    _patch(root, "e-rounding", bbox=[[0, 0, 100], [5.5, 6, 100]])
    return root


def test_census_separates_patches_and_counts_staleness_by_axis(tmp_path):
    result = census(_pack(tmp_path))

    summary = result["summary"]
    assert summary["patches_inspected"] == 5
    assert summary["by_status"] == {
        "consistent": 2,  # exact + sub-voxel rounding
        "stale": 2,
        "undeclared": 1,
    }
    assert summary["stale_patches"] == 2
    assert summary["stale_axis_counts"] == {"x": 1, "y": 0, "z": 2}
    assert summary["worst_excess_voxels"] == 654.0
    assert summary["worst_patch"] == "b-stale-z"
    # every vertex of both stale patches lies outside its declared box
    assert summary["valid_vertices_outside_declared_bbox"] == 32
    assert result["verdict"] == "metadata-defects-present"


def test_filtering_on_declared_bbox_would_lose_the_geometry(tmp_path):
    row = census_patch(_patch(tmp_path / "p", "stale", z0=754.0, bbox=[[0, 0, 100], [6, 6, 100]]))
    assert row["status"] == "stale"
    assert row["fraction_outside_declared_bbox"] == 1.0
    assert row["observed_bbox_xyz"] == [[0.0, 0.0, 754.0], [6.0, 6.0, 754.0]]


def test_rows_default_to_defects_only_and_all_rows_is_opt_in(tmp_path):
    root = _pack(tmp_path)
    assert {r["patch"] for r in census(root)["rows"]} == {"b-stale-z", "c-stale-xz"}
    full = census(root, include_all_rows=True)
    assert len(full["rows"]) == 5 and full["rows_included"] == "all"


def test_empty_root_is_unverified_not_clean(tmp_path):
    (tmp_path / "empty").mkdir()
    result = census(tmp_path / "empty")
    assert result["summary"]["patches_inspected"] == 0
    assert result["verdict"] == "unverified"

    out = tmp_path / "out.json"
    assert main(["--root", str(tmp_path / "empty"), "--out", str(out)]) == 2


def test_directories_missing_required_files_are_not_patches(tmp_path):
    root = tmp_path / "pack"
    _patch(root, "ok")
    (root / "junk").mkdir()
    (root / "junk" / "meta.json").write_text("{}")
    assert [p.name for p in find_patches(root)] == ["ok"]


def test_symlinked_directories_are_not_followed(tmp_path):
    root = tmp_path / "pack"
    _patch(root, "ok")
    (root / "loop").symlink_to(root, target_is_directory=True)
    assert [p.name for p in find_patches(root)] == ["ok"]


def test_unreadable_patches_are_recorded_and_do_not_abort_the_census(tmp_path):
    root = tmp_path / "pack"
    _patch(root, "good")
    _patch(root, "bad-meta", bad_meta=True)
    broken = _patch(root, "bad-tiff")
    (broken / "x.tif").write_bytes(b"not a tiff")

    result = census(root, include_all_rows=True)

    statuses = {r["patch"]: r["status"] for r in result["rows"]}
    assert statuses == {"good": "consistent", "bad-meta": "unreadable", "bad-tiff": "unreadable"}
    assert result["verdict"] == "metadata-defects-present"


def test_all_invalid_patch_is_empty_not_consistent(tmp_path):
    root = tmp_path / "pack"
    _patch(root, "hollow", z_grid=np.full((4, 4), -1.0, np.float32))
    row = census(root)["rows"][0]
    assert row["status"] == "empty"


def test_validity_rule_changes_counts_and_is_recorded(tmp_path):
    root = tmp_path / "pack"
    z = np.full((4, 4), 100.0, np.float32)
    z[0, 0] = 0.0  # valid under nonnegative-xyz, a hole under the audit rule
    _patch(root, "edge", z_grid=z, bbox=[[0, 0, 100], [6, 6, 100]])

    audit_rule = census(root, include_all_rows=True)
    upstream = census(root, validity="nonnegative-xyz", include_all_rows=True)

    assert audit_rule["validity_rule"] == "tifxyz"
    assert audit_rule["rows"][0]["valid_vertices"] == 15
    # the z==0 corner (0,0,0) is a vertex only under the upstream rule, and it
    # lies 100 voxels below the declared z range
    assert upstream["validity_rule"] == "nonnegative-xyz"
    assert upstream["rows"][0]["valid_vertices"] == 16
    assert upstream["rows"][0]["max_excess_voxels"] == 100.0
    assert upstream["summary"]["stale_axis_counts"]["z"] == 1
    assert audit_rule["summary"]["stale_axis_counts"]["z"] == 0


def test_positive_control_passes_and_detects_the_planted_654_voxel_defect():
    control = run_positive_control()
    assert control["passed"] is True
    assert control["detected_worst_excess_voxels"] == 654.0


def test_a_blind_census_fails_its_own_positive_control(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bbox_census,
        "compare_bbox",
        lambda declared, observed, tolerance_voxels: {
            "status": "consistent",
            "stale_axes": [],
            "metadata_bbox_xyz": [[-1e9] * 3, [1e9] * 3],
        },
    )
    assert run_positive_control()["passed"] is False

    result = census(_pack(tmp_path))
    assert result["verdict"] == "control-failed"
    out = tmp_path / "out.json"
    assert main(["--root", str(tmp_path / "pack"), "--out", str(out)]) == 2


def test_invalid_configuration_is_rejected(tmp_path):
    root = _pack(tmp_path)
    with pytest.raises(BBoxCensusError):
        census(root, validity="other")
    with pytest.raises(BBoxCensusError):
        census(root, tolerance_voxels=-1)
    with pytest.raises(BBoxCensusError):
        census(root, workers=0)
    with pytest.raises(BBoxCensusError):
        census(tmp_path / "does-not-exist")


def test_cli_is_create_only_and_gates_on_request(tmp_path, capsys):
    root = _pack(tmp_path)
    out = tmp_path / "result.json"

    assert main(["--root", str(root), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["summary"]["stale_patches"] == 2
    assert "METADATA-DEFECTS-PRESENT" in capsys.readouterr().out

    with pytest.raises(SystemExit) as error:
        main(["--root", str(root), "--out", str(out)])
    assert error.value.code == 2

    gated = tmp_path / "gated.json"
    assert main(["--root", str(root), "--out", str(gated), "--fail-on-defects"]) == 2


def test_clean_pack_exits_zero_even_when_gated(tmp_path):
    root = tmp_path / "pack"
    _patch(root, "one")
    _patch(root, "two", bbox=None)
    out = tmp_path / "clean.json"
    assert main(["--root", str(root), "--out", str(out), "--fail-on-defects"]) == 0
    assert json.loads(out.read_text())["verdict"] == "clean"
