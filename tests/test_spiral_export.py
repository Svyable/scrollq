import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scrollq.spiral_export import SpiralExportError, export_checkpoint, prepare_export
from scrollq.spiral_run import run_baseline


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _villa(tmp_path, *, exporter_mode="tifxyz"):
    root = tmp_path / "villa"
    spiral = root / "spiral-fitting"
    lasagna = root / "lasagna" / "configs"
    spiral.mkdir(parents=True)
    lasagna.mkdir(parents=True)

    (spiral / "fit_spiral.py").write_text(
        "import os, pathlib\n"
        "run=pathlib.Path(os.environ['FIT_SPIRAL_RUN_DIR'])\n"
        "(run/'checkpoint_fitted.ckpt').write_bytes(b'checkpoint-v1')\n"
    )
    if exporter_mode == "tifxyz":
        body = (
            "import argparse, json, pathlib, numpy as np\n"
            "from PIL import Image\n"
            "p=argparse.ArgumentParser()\n"
            "p.add_argument('checkpoint'); p.add_argument('output')\n"
            "p.add_argument('--umbilicus'); p.add_argument('--lasagna-dir')\n"
            "p.add_argument('--device'); p.add_argument('--voxel-size-um', type=float)\n"
            "p.add_argument('--chunk-size'); a=p.parse_args()\n"
            "assert a.voxel_size_um == 9.362\n"
            "out=pathlib.Path(a.output); out.mkdir()\n"
            "yy,xx=np.mgrid[0:5,0:5]\n"
            "x=(xx*2).astype(np.float32); y=(yy*2).astype(np.float32)\n"
            "z=np.full((5,5),10.0,dtype=np.float32)\n"
            "[Image.fromarray(arr).save(out/name) for name,arr in "
            "[('x.tif',x),('y.tif',y),('z.tif',z)]]\n"
            "(out/'meta.json').write_text(json.dumps("
            "{'format':'tifxyz','scale':[0.5,0.5],'bbox':[[0,0,10],[8,8,10]]}))\n"
        )
    else:
        body = (
            "import argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('checkpoint'); p.add_argument('output')\n"
            "p.add_argument('--umbilicus'); p.add_argument('--lasagna-dir')\n"
            "p.add_argument('--device'); p.add_argument('--voxel-size-um'); p.add_argument('--chunk-size')\n"
            "p.parse_args()\n"
            "print('exit zero without export')\n"
        )
    (spiral / "flatten_spiral_checkpoint.py").write_text(body)
    (root / "lasagna" / "fit_service.py").write_text("print('fixture')\n")
    (lasagna / "flatten_fast_nofilter.json").write_text("{}\n")

    _git(root, "init")
    _git(root, "config", "user.email", "test@example.org")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _dataset_and_recipe(tmp_path, villa_commit):
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
    (root / "umbilicus.json").write_text('{"fixture":"published"}\n')
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
        "software": {
            "villa_commit": villa_commit,
            "dataset_assembler_commit": "b" * 40,
        },
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
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe))
    return root, recipe_path


def _successful_fit(tmp_path, *, exporter_mode="tifxyz"):
    villa, commit = _villa(tmp_path, exporter_mode=exporter_mode)
    dataset, recipe = _dataset_and_recipe(tmp_path, commit)
    run_dir = tmp_path / "run"
    fit = run_baseline(
        dataset=dataset,
        recipe_path=recipe,
        villa_root=villa,
        run_dir=run_dir,
        python_executable=sys.executable,
    )
    assert fit["success"] is True
    return villa, dataset, run_dir


def test_official_export_receipts_exact_fit_and_tifxyz(tmp_path):
    villa, dataset, run_dir = _successful_fit(tmp_path)
    output = tmp_path / "baseline.tifxyz"
    evidence = tmp_path / "export-evidence"

    receipt = export_checkpoint(
        run_dir=run_dir,
        dataset=dataset,
        villa_root=villa,
        output=output,
        evidence_dir=evidence,
        python_executable=sys.executable,
        device="cpu",
    )

    assert receipt["success"] is True
    assert receipt["prize_volume_id"] == "20250821151701"
    assert receipt["voxel_size_um"] == pytest.approx(9.362)
    assert "--voxel-size-um" in receipt["command"]
    assert receipt["command"][receipt["command"].index("--voxel-size-um") + 1] == "9.362"
    assert receipt["output"]["tifxyz_audit_status"] != "fail"
    assert len(receipt["output"]["tree_sha256"]) == 64
    assert receipt["villa"]["flatten_spiral_checkpoint_sha256"] == _sha256(
        villa / "spiral-fitting" / "flatten_spiral_checkpoint.py"
    )
    assert json.loads((evidence / "spiral-export.receipt.json").read_text())["success"] is True


def test_tampered_checkpoint_blocks_before_export(tmp_path):
    villa, dataset, run_dir = _successful_fit(tmp_path)
    (run_dir / "checkpoint_fitted.ckpt").write_bytes(b"tampered")
    with pytest.raises(SpiralExportError, match="checkpoint bytes"):
        prepare_export(
            run_dir=run_dir,
            dataset=dataset,
            villa_root=villa,
            output=tmp_path / "out.tifxyz",
            evidence_dir=tmp_path / "evidence",
            python_executable=sys.executable,
            device="cpu",
            chunk_size=65536,
        )
    assert not (tmp_path / "out.tifxyz").exists()
    assert not (tmp_path / "evidence").exists()


def test_recipe_voxel_drift_to_villa_default_is_rejected(tmp_path):
    villa, dataset, run_dir = _successful_fit(tmp_path)
    recipe_path = run_dir / "spiral-run.recipe.json"
    recipe = json.loads(recipe_path.read_text())
    recipe["scroll_spec_expected"]["voxel_size_um"] = 9.6
    recipe_path.write_text(json.dumps(recipe))
    run_receipt_path = run_dir / "spiral-run.receipt.json"
    run_receipt = json.loads(run_receipt_path.read_text())
    run_receipt["recipe"]["copy_sha256"] = _sha256(recipe_path)
    run_receipt_path.write_text(json.dumps(run_receipt))
    with pytest.raises(SpiralExportError, match="9.362"):
        prepare_export(
            run_dir=run_dir,
            dataset=dataset,
            villa_root=villa,
            output=tmp_path / "out.tifxyz",
            evidence_dir=tmp_path / "evidence",
            python_executable=sys.executable,
            device="cpu",
            chunk_size=65536,
        )


def test_zero_exit_without_usable_tifxyz_is_failed_receipt(tmp_path):
    villa, dataset, run_dir = _successful_fit(tmp_path, exporter_mode="no-output")
    evidence = tmp_path / "evidence"
    receipt = export_checkpoint(
        run_dir=run_dir,
        dataset=dataset,
        villa_root=villa,
        output=tmp_path / "out.tifxyz",
        evidence_dir=evidence,
        python_executable=sys.executable,
        device="cpu",
    )
    assert receipt["return_code"] == 0
    assert receipt["success"] is False
    assert receipt["output"]["tifxyz_audit_status"] is None
    assert json.loads((evidence / "spiral-export.receipt.json").read_text())["success"] is False


def test_export_refuses_existing_output_or_evidence(tmp_path):
    villa, dataset, run_dir = _successful_fit(tmp_path)
    output = tmp_path / "existing.tifxyz"
    output.mkdir()
    with pytest.raises(SpiralExportError, match="overwrite existing TIFXYZ"):
        prepare_export(
            run_dir=run_dir,
            dataset=dataset,
            villa_root=villa,
            output=output,
            evidence_dir=tmp_path / "evidence",
            python_executable=sys.executable,
            device="cpu",
            chunk_size=65536,
        )
