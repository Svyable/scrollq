import json
import shutil
import sys

import numpy as np
import pytest
from PIL import Image

from scrollq.vc3d_run_guard import VC3DRunGuardError, main, run_guarded


def _surface(root):
    root.mkdir()
    yy, xx = np.mgrid[0:5, 0:5]
    x = (xx * 2).astype(np.float32)
    y = (yy * 2).astype(np.float32)
    z = np.full((5, 5), 10.0, dtype=np.float32)
    for name, arr in (("x.tif", x), ("y.tif", y), ("z.tif", z)):
        Image.fromarray(arr).save(root / name)
    (root / "meta.json").write_text(
        json.dumps(
            {
                "format": "tifxyz",
                "scale": [0.5, 0.5],
                "bbox": [[0, 0, 10], [8, 8, 10]],
            }
        ),
        encoding="utf-8",
    )
    return root


def _copy_command(source, destination):
    code = (
        "import shutil,sys;"
        "shutil.copytree(sys.argv[1],sys.argv[2]);"
        "print('created', sys.argv[2])"
    )
    return [sys.executable, "-c", code, str(source), str(destination)]


def test_exit_zero_requires_new_semantically_valid_surface(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    report = run_guarded(
        _copy_command(source, output),
        output_tifxyz=output,
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["proof_gate_pass"] is True
    assert report["status"] == "pass"
    assert report["process"]["return_code"] == 0
    assert report["process"]["exit_zero_but_postcondition_failed"] is False
    assert report["output"]["audit"]["grid"]["valid_vertices"] == 25
    assert report["output"]["audit"]["quads"]["valid_quads"] == 16
    assert report["output"]["surface_area_cm2"] > 0
    assert all(gate["passed"] for gate in report["gates"])


def test_exit_zero_missing_output_is_explicit_failure(tmp_path):
    report = run_guarded(
        [sys.executable, "-c", "print('success without output')"],
        output_tifxyz=tmp_path / "missing",
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["proof_gate_pass"] is False
    assert report["process"]["return_code"] == 0
    assert report["process"]["exit_zero_but_postcondition_failed"] is True
    gate = next(g for g in report["gates"] if g["name"] == "new_output_present")
    assert gate["passed"] is False


def test_empty_or_malformed_surface_cannot_pass(tmp_path):
    output = tmp_path / "output"
    code = "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir()"
    report = run_guarded(
        [sys.executable, "-c", code, str(output)],
        output_tifxyz=output,
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["proof_gate_pass"] is False
    assert report["output"]["audit"]["status"] == "fail"
    assert report["process"]["exit_zero_but_postcondition_failed"] is True


def test_nonzero_exit_cannot_be_rescued_by_output(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    code = (
        "import shutil,sys;"
        "shutil.copytree(sys.argv[1],sys.argv[2]);"
        "raise SystemExit(7)"
    )
    report = run_guarded(
        [sys.executable, "-c", code, str(source), str(output)],
        output_tifxyz=output,
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["output"]["audit"]["status"] == "pass"
    assert report["process"]["return_code"] == 7
    assert report["proof_gate_pass"] is False


def test_minimum_area_is_semantic_postcondition(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    report = run_guarded(
        _copy_command(source, output),
        output_tifxyz=output,
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
        min_area_cm2=1.0,
    )

    assert report["output"]["surface_area_cm2"] < 1.0
    assert report["proof_gate_pass"] is False
    gate = next(
        g for g in report["gates"] if g["name"] == "finite_positive_surface_area"
    )
    assert gate["passed"] is False


def test_existing_output_is_rejected_before_command_launch(tmp_path):
    source = _surface(tmp_path / "source")
    output = _surface(tmp_path / "output")
    with pytest.raises(VC3DRunGuardError, match="already exists"):
        run_guarded(
            _copy_command(source, output),
            output_tifxyz=output,
            volume_root="PHerc-test/volumes/exact.zarr",
            voxel_size_um=10.0,
            stdout_log=tmp_path / "stdout.log",
            stderr_log=tmp_path / "stderr.log",
        )
    assert not (tmp_path / "stdout.log").exists()


def test_require_ct_preflight_fails_when_not_supplied(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    report = run_guarded(
        _copy_command(source, output),
        output_tifxyz=output,
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
        require_ct_preflight=True,
    )

    assert report["proof_gate_pass"] is False
    gate = next(g for g in report["gates"] if g["name"] == "ct_volume_binding")
    assert gate["observed"] == "unknown"
    assert gate["passed"] is False


def test_cli_writes_create_only_receipt_and_returns_two_on_semantic_failure(
    tmp_path, capsys
):
    out = tmp_path / "receipt.json"
    status = main(
        [
            "--output-tifxyz",
            str(tmp_path / "missing"),
            "--volume-root",
            "PHerc-test/volumes/exact.zarr",
            "--voxel-size-um",
            "10",
            "--stdout-log",
            str(tmp_path / "stdout.log"),
            "--stderr-log",
            str(tmp_path / "stderr.log"),
            "--out",
            str(out),
            "--",
            sys.executable,
            "-c",
            "print('exit zero')",
        ]
    )
    assert status == 2
    report = json.loads(out.read_text())
    assert report["proof_gate"] == "PIPELINE_EXECUTION_INTEGRITY"
    assert report["process"]["exit_zero_but_postcondition_failed"] is True
    capsys.readouterr()

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--output-tifxyz",
                str(tmp_path / "other"),
                "--volume-root",
                "PHerc-test/volumes/exact.zarr",
                "--voxel-size-um",
                "10",
                "--stdout-log",
                str(tmp_path / "stdout2.log"),
                "--stderr-log",
                str(tmp_path / "stderr2.log"),
                "--out",
                str(out),
                "--",
                sys.executable,
                "-c",
                "print('again')",
            ]
        )
    assert error.value.code == 2
