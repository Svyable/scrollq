import json
import os
import subprocess
import sys

import numpy as np
import pytest

from scrollq.spiral_run import SpiralRunError, prepare_run, run_baseline


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _villa(tmp_path):
    root = tmp_path / "villa"
    spiral = root / "spiral-fitting"
    spiral.mkdir(parents=True)
    (spiral / "fit_spiral.py").write_text(
        "import os, pathlib, sys\n"
        "run=pathlib.Path(os.environ['FIT_SPIRAL_RUN_DIR'])\n"
        "print('fake official fitter')\n"
        "print('loaded 480117 tracks within z-roi [11000, 12000)')\n"
        "print('fitting 0 patches')\n"
        "print(os.environ['FIT_SPIRAL_CONFIG_OVERRIDES'], file=sys.stderr)\n"
        "(run/'checkpoint_fitted.ckpt').write_bytes(b'checkpoint')\n"
        "(run/'satisfaction_metrics_fitted.json').write_text('{}')\n"
    )
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.org")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _dataset(tmp_path, villa_commit):
    root = tmp_path / "dataset"
    tracks = root / "tracks"
    lasagna = root / "lasagna_inputs"
    tracks.mkdir(parents=True)
    lasagna.mkdir()
    dbm = tracks / "tracks.dbm"
    dbm.write_bytes(b"tracks")
    fixed_ns = 1_700_000_000_123_456_789
    os.utime(dbm, ns=(fixed_ns, fixed_ns))
    np.savez(
        tracks / "tracks.crossings.npz",
        metadata=np.array(json.dumps({
            "db_signature": [[dbm.name, dbm.stat().st_size, dbm.stat().st_mtime_ns]]
        })),
    )
    (tracks / "tracks.extract.json").write_text(
        json.dumps({"source": "PHerc0826/20250821151701/tracks"})
    )
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
    for name in ("las_008_nx.ome.zarr", "las_008_ny.ome.zarr", "las_008_grad_mag.ome.zarr"):
        group = lasagna / name / "2"
        group.mkdir(parents=True)
        (group / ".zarray").write_text(json.dumps({"shape": shape, "dtype": "|u1"}))
    for sidecar in (
        lasagna / "las_008_nx.ome.zarr.respool_g2_pair",
        lasagna / "las_008_grad_mag.ome.zarr.respool_g2",
    ):
        sidecar.mkdir()
        (sidecar / "meta.json").write_text(json.dumps({"array_shape": shape}))
    recipe = {
        "schema_version": 1,
        "scroll": "PHerc0826",
        "prize_volume_id": "20250821151701",
        "software": {"villa_commit": villa_commit, "dataset_assembler_commit": "b" * 40},
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
            "expected_reference_context": {
                "documented_tracks_loaded_with_input_use_tracks_true": 480117,
            },
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
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe))
    return root, recipe_path


def test_prepare_requires_exact_clean_villa(tmp_path):
    villa, commit = _villa(tmp_path)
    dataset, recipe = _dataset(tmp_path, "0" * 40)
    with pytest.raises(SpiralRunError, match="HEAD mismatch"):
        prepare_run(
            dataset=dataset, recipe_path=recipe, villa_root=villa,
            run_dir=tmp_path / "run", python_executable=sys.executable, cache_dir=None
        )
    document = json.loads(recipe.read_text())
    document["software"]["villa_commit"] = commit
    recipe.write_text(json.dumps(document))
    (villa / "dirty.txt").write_text("untracked")
    with pytest.raises(SpiralRunError, match="dirty"):
        prepare_run(
            dataset=dataset, recipe_path=recipe, villa_root=villa,
            run_dir=tmp_path / "run", python_executable=sys.executable, cache_dir=None
        )


def test_runner_executes_and_receipts_outputs(tmp_path):
    villa, commit = _villa(tmp_path)
    dataset, recipe = _dataset(tmp_path, commit)
    run_dir = tmp_path / "run"
    receipt = run_baseline(
        dataset=dataset, recipe_path=recipe, villa_root=villa,
        run_dir=run_dir, python_executable=sys.executable
    )
    assert receipt["success"] is True
    assert receipt["return_code"] == 0
    assert receipt["villa"]["commit"] == commit
    assert receipt["checkpoint"]["present"] is True
    assert receipt["supervision"]["ok"] is True
    assert receipt["supervision"]["tracks"]["unique_counts"] == [480117]
    assert receipt["supervision"]["tracks"]["reference_count_match"] is True
    assert receipt["supervision"]["patches"]["unique_counts"] == [0]
    assert json.loads((run_dir / "spiral-run.receipt.json").read_text())["success"] is True
    assert {"checkpoint_fitted.ckpt", "satisfaction_metrics_fitted.json"} <= {
        row["path"] for row in receipt["outputs"]
    }


def test_zero_exit_without_checkpoint_is_failure(tmp_path):
    villa, _ = _villa(tmp_path)
    (villa / "spiral-fitting" / "fit_spiral.py").write_text("print('no checkpoint')\n")
    _git(villa, "add", ".")
    _git(villa, "commit", "-m", "no checkpoint")
    commit = _git(villa, "rev-parse", "HEAD")
    dataset, recipe = _dataset(tmp_path, commit)
    receipt = run_baseline(
        dataset=dataset, recipe_path=recipe, villa_root=villa,
        run_dir=tmp_path / "run", python_executable=sys.executable
    )
    assert receipt["return_code"] == 0
    assert receipt["success"] is False
    assert receipt["checkpoint"]["present"] is False


def test_checkpoint_with_zero_track_supervision_is_failure(tmp_path):
    villa, _ = _villa(tmp_path)
    (villa / "spiral-fitting" / "fit_spiral.py").write_text(
        "import os, pathlib\n"
        "run=pathlib.Path(os.environ['FIT_SPIRAL_RUN_DIR'])\n"
        "print('loaded 0 tracks within z-roi [11000, 12000)')\n"
        "print('fitting 0 patches')\n"
        "(run/'checkpoint_fitted.ckpt').write_bytes(b'checkpoint')\n"
    )
    _git(villa, "add", ".")
    _git(villa, "commit", "-m", "zero track supervision")
    commit = _git(villa, "rev-parse", "HEAD")
    dataset, recipe = _dataset(tmp_path, commit)

    receipt = run_baseline(
        dataset=dataset, recipe_path=recipe, villa_root=villa,
        run_dir=tmp_path / "run", python_executable=sys.executable
    )

    assert receipt["return_code"] == 0
    assert receipt["checkpoint"]["present"] is True
    assert receipt["success"] is False
    assert receipt["supervision"]["ok"] is False
    assert receipt["supervision"]["tracks"]["unique_counts"] == [0]
    assert any(
        row["name"] == "tracks_positive" and row["ok"] is False
        for row in receipt["supervision"]["checks"]
    )


def test_checkpoint_with_unexpected_patch_supervision_is_failure(tmp_path):
    villa, _ = _villa(tmp_path)
    (villa / "spiral-fitting" / "fit_spiral.py").write_text(
        "import os, pathlib\n"
        "run=pathlib.Path(os.environ['FIT_SPIRAL_RUN_DIR'])\n"
        "print('loaded 480117 tracks within z-roi [11000, 12000)')\n"
        "print('fitting 1 patches')\n"
        "(run/'checkpoint_fitted.ckpt').write_bytes(b'checkpoint')\n"
    )
    _git(villa, "add", ".")
    _git(villa, "commit", "-m", "unexpected patch supervision")
    commit = _git(villa, "rev-parse", "HEAD")
    dataset, recipe = _dataset(tmp_path, commit)

    receipt = run_baseline(
        dataset=dataset, recipe_path=recipe, villa_root=villa,
        run_dir=tmp_path / "run", python_executable=sys.executable
    )

    assert receipt["return_code"] == 0
    assert receipt["checkpoint"]["present"] is True
    assert receipt["success"] is False
    assert receipt["supervision"]["tracks"]["reference_count_match"] is True
    assert receipt["supervision"]["patches"]["unique_counts"] == [1]
    assert any(
        row["name"] == "patches_disabled_effective" and row["ok"] is False
        for row in receipt["supervision"]["checks"]
    )


def test_preflight_failure_prevents_run_directory_creation(tmp_path):
    villa, commit = _villa(tmp_path)
    dataset, recipe = _dataset(tmp_path, commit)
    spec = json.loads((dataset / "spiral-scroll.json").read_text())
    spec["name"] = "WRONG"
    (dataset / "spiral-scroll.json").write_text(json.dumps(spec))
    run_dir = tmp_path / "run"
    with pytest.raises(SpiralRunError, match="preflight blocked"):
        run_baseline(
            dataset=dataset, recipe_path=recipe, villa_root=villa,
            run_dir=run_dir, python_executable=sys.executable
        )
    assert not run_dir.exists()
