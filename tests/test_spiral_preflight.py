import json
import os

import numpy as np

from scrollq.spiral_preflight import audit_spiral_dataset


def _fixture(tmp_path):
    root = tmp_path / "ds0826"
    tracks_dir = root / "tracks"
    lasagna = root / "lasagna_inputs"
    tracks_dir.mkdir(parents=True)
    lasagna.mkdir()

    dbm = tracks_dir / "tracks.dbm"
    dbm.write_bytes(b"tracks")
    fixed_ns = 1_700_000_000_123_456_789
    os.utime(dbm, ns=(fixed_ns, fixed_ns))

    metadata = {
        "db_signature": [[dbm.name, dbm.stat().st_size, dbm.stat().st_mtime_ns]]
    }
    np.savez(tracks_dir / "tracks.crossings.npz", metadata=np.array(json.dumps(metadata)))
    (tracks_dir / "tracks.extract.json").write_text(json.dumps({
        "source": "PHerc0826/20250821151701/tracks"
    }))
    (root / "umbilicus.json").write_text("{}")
    (root / "spiral-scroll.json").write_text(json.dumps({
        "schema_version": 1,
        "name": "PHerc0826",
        "voxel_size_um": 9.362,
        "spiral_outward_sense": "CW",
        "normal_zarr_group": "2",
        "lasagna_scale": 4,
        "paths": {"tracks_dbm": "tracks/tracks.dbm"},
    }))

    shape = [4, 5, 6]
    for name in ["las_008_nx.ome.zarr", "las_008_ny.ome.zarr", "las_008_grad_mag.ome.zarr"]:
        group = lasagna / name / "2"
        group.mkdir(parents=True)
        (group / ".zarray").write_text(json.dumps({"shape": shape, "dtype": "|u1"}))
    nx_sidecar = lasagna / "las_008_nx.ome.zarr.respool_g2_pair"
    grad_sidecar = lasagna / "las_008_grad_mag.ome.zarr.respool_g2"
    nx_sidecar.mkdir()
    grad_sidecar.mkdir()
    (nx_sidecar / "meta.json").write_text(json.dumps({"array_shape": shape}))
    (grad_sidecar / "meta.json").write_text(json.dumps({"array_shape": shape}))

    recipe = {
        "scroll": "PHerc0826",
        "prize_volume_id": "20250821151701",
        "scroll_spec_expected": {
            "voxel_size_um": 9.362,
            "spiral_outward_sense_candidate": "CW",
            "normal_zarr_group": "2",
            "lasagna_scale": 4,
        },
        "bounded_reproduction": {
            "z_range_half_open": [11000, 12000],
            "optimizer_num_training_steps": 30000,
            "optimizer_random_seed": 1,
            "config_overrides": {
                "z_begin": 11000,
                "z_end": 12000,
                "optimizer_num_training_steps": 30000,
                "optimizer_random_seed": 1,
                "input_use_tracks": True,
                "input_disable_patches": True,
                "loss_weight_shell_outer": 0,
                "loss_weight_shell_patch_radius": 0,
                "dense_spacing_mode": "grad_mag",
                "loss_weight_dense_spacing": 0,
            },
        },
    }
    return root, recipe


def test_ready_fixture_passes(tmp_path):
    root, recipe = _fixture(tmp_path)
    report = audit_spiral_dataset(root, recipe)
    assert report["ready_for_fit"] is True
    assert report["status"] == "ready"
    assert report["fit_environment"]["FIT_SPIRAL_CONFIG_OVERRIDES"]


def test_wrong_outward_sense_blocks(tmp_path):
    root, recipe = _fixture(tmp_path)
    spec_path = root / "spiral-scroll.json"
    spec = json.loads(spec_path.read_text())
    spec["spiral_outward_sense"] = "ACW"
    spec_path.write_text(json.dumps(spec))
    report = audit_spiral_dataset(root, recipe)
    assert report["ready_for_fit"] is False
    failed = {row["name"] for row in report["checks"] if not row["ok"]}
    assert "outward_sense" in failed


def test_crossings_signature_mismatch_blocks(tmp_path):
    root, recipe = _fixture(tmp_path)
    dbm = root / "tracks" / "tracks.dbm"
    os.utime(dbm, ns=(1_700_000_000_999_999_999, 1_700_000_000_999_999_999))
    report = audit_spiral_dataset(root, recipe)
    assert report["ready_for_fit"] is False
    failed = {row["name"] for row in report["checks"] if not row["ok"]}
    assert "crossings_db_signature" in failed


def test_missing_resident_pool_blocks(tmp_path):
    root, recipe = _fixture(tmp_path)
    (root / "lasagna_inputs" / "las_008_grad_mag.ome.zarr.respool_g2" / "meta.json").unlink()
    report = audit_spiral_dataset(root, recipe)
    assert report["ready_for_fit"] is False
    assert any(
        row["name"].startswith("resident_pool:") and not row["ok"]
        for row in report["checks"]
    )


def test_wrong_volume_provenance_blocks(tmp_path):
    root, recipe = _fixture(tmp_path)
    extract = root / "tracks" / "tracks.extract.json"
    extract.write_text(json.dumps({"source": "PHerc0826/WRONG/tracks"}))
    report = audit_spiral_dataset(root, recipe)
    assert report["ready_for_fit"] is False
    assert any(
        row["name"] == "exact_volume_in_track_provenance" and not row["ok"]
        for row in report["checks"]
    )
