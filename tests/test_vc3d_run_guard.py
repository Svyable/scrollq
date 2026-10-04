import hashlib
import json
import shutil
import sys

import numpy as np
import pytest
from PIL import Image

from scrollq.vc3d_run_guard import VC3DRunGuardError, main, run_guarded


def _surface(root, *, n=5, shift=0.0, z0=10.0, bbox="exact", extra_meta=None):
    """An n x n planar grid with 2-voxel spacing at z = z0.

    ``bbox="exact"`` declares the true bounds; a list overrides them and
    ``None`` omits the field.
    """
    root.mkdir()
    yy, xx = np.mgrid[0:n, 0:n]
    x = (xx * 2 + shift).astype(np.float32)
    y = (yy * 2).astype(np.float32)
    z = np.full((n, n), z0, dtype=np.float32)
    for name, arr in (("x.tif", x), ("y.tif", y), ("z.tif", z)):
        Image.fromarray(arr).save(root / name)
    meta = {"format": "tifxyz", "scale": [0.5, 0.5]}
    if bbox == "exact":
        meta["bbox"] = [[shift, 0, z0], [(n - 1) * 2 + shift, (n - 1) * 2, z0]]
    elif bbox is not None:
        meta["bbox"] = bbox
    meta.update(extra_meta or {})
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
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


def test_missing_executable_records_null_identity_and_fails_closed(tmp_path):
    command = ["definitely-not-a-real-vc3d-command-scrollq"]
    report = run_guarded(
        command,
        output_tifxyz=tmp_path / "missing",
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=10.0,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["proof_gate_pass"] is False
    assert report["process"]["return_code"] is None
    assert report["process"]["launch_error"]
    assert report["executable"] == {
        "requested": command[0],
        "resolved": None,
        "sha256": None,
    }


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


# --- producer-success semantic validation --------------------------------


def _run(tmp_path, command, output, **kwargs):
    return run_guarded(
        command,
        output_tifxyz=output,
        volume_root="PHerc-test/volumes/exact.zarr",
        voxel_size_um=kwargs.pop("voxel_size_um", 10.0),
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
        **kwargs,
    )


def _gate(report, name):
    return next(g for g in report["gates"] if g["name"] == name)


def _volume_meta(tmp_path, **fields):
    path = tmp_path / "volume-meta.json"
    path.write_text(json.dumps({"voxelsize": 7.91, **fields}), encoding="utf-8")
    return path


def test_verdict_separates_ok_semantic_and_process_failure(tmp_path):
    source = _surface(tmp_path / "source")
    ok = _run(tmp_path, _copy_command(source, tmp_path / "ok"), tmp_path / "ok")
    assert ok["verdict"] == "PRODUCER_OK"
    assert ok["failed_gates"] == []

    sub = tmp_path / "semantic"
    sub.mkdir()
    semantic = _run(
        sub, [sys.executable, "-c", "print('success')"], sub / "missing"
    )
    assert semantic["verdict"] == "PRODUCER_SEMANTIC_FAILURE"
    assert "new_output_present" in semantic["failed_gates"]

    sub = tmp_path / "process"
    sub.mkdir()
    process = _run(
        sub,
        [sys.executable, "-c", "raise SystemExit(7)"],
        sub / "missing",
    )
    assert process["verdict"] == "PRODUCER_PROCESS_FAILURE"

    sub = tmp_path / "launch"
    sub.mkdir()
    launch = _run(sub, ["definitely-not-a-real-vc3d-command-scrollq"], sub / "x")
    assert launch["verdict"] == "PRODUCER_PROCESS_FAILURE"


def test_reported_vc3d_failure_shape_is_a_semantic_failure(tmp_path):
    # Reported shape: the producer writes a surface, judges its own (wrongly
    # computed) area too small, removes the directory, and still exits 0.
    output = tmp_path / "grown.tifxyz"
    code = (
        "import pathlib,shutil,sys;"
        "out=pathlib.Path(sys.argv[1]); out.mkdir();"
        "(out/'meta.json').write_text('{}');"
        "shutil.rmtree(out);"
        "print('grow complete')"
    )
    report = _run(tmp_path, [sys.executable, "-c", code, str(output)], output)

    assert report["process"]["return_code"] == 0
    assert report["verdict"] == "PRODUCER_SEMANTIC_FAILURE"
    assert report["process"]["exit_zero_but_postcondition_failed"] is True
    assert report["proof_gate_pass"] is False


def test_wrong_declared_voxel_size_is_contradicted_by_volume_meta(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    meta = _volume_meta(tmp_path)
    report = _run(
        tmp_path,
        _copy_command(source, output),
        output,
        voxel_size_um=10.0,
        volume_meta=meta,
    )

    gate = _gate(report, "voxel_spacing_verified")
    assert gate["observed"] == "contradicted"
    assert gate["passed"] is False
    assert report["verdict"] == "PRODUCER_SEMANTIC_FAILURE"
    source_row = report["output"]["physical"]["voxel_spacing"]["sources"][0]
    assert source_row["voxelsize_um"] == 7.91 and source_row["agrees"] is False
    assert len(source_row["sha256"]) == 64


def test_agreeing_volume_meta_verifies_spacing(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    report = _run(
        tmp_path,
        _copy_command(source, output),
        output,
        voxel_size_um=7.91,
        volume_meta=_volume_meta(tmp_path),
        require_verified_voxel_spacing=True,
    )

    assert report["verdict"] == "PRODUCER_OK"
    gate = _gate(report, "voxel_spacing_verified")
    assert gate["observed"] == "verified" and gate["evaluated"] is True


def test_requiring_verified_spacing_without_a_source_is_refused(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    with pytest.raises(VC3DRunGuardError, match="independent source"):
        _run(
            tmp_path,
            _copy_command(source, output),
            output,
            require_verified_voxel_spacing=True,
        )
    assert not (tmp_path / "stdout.log").exists()


def test_unexercised_gates_are_listed_not_silently_passed(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    report = _run(tmp_path, _copy_command(source, output), output)

    assert report["verdict"] == "PRODUCER_OK"
    assert set(report["unevaluated_gates"]) == {
        "voxel_spacing_verified",
        "extent_within_volume",
        "output_differs_from_inputs",
        "ct_volume_binding",
    }
    assert "unevaluated_gates" in report["limitations"]


def test_area_is_recomputed_from_vertices_not_producer_metadata(tmp_path):
    honest = _surface(tmp_path / "honest")
    lying = _surface(
        tmp_path / "lying",
        extra_meta={"area_cm2": 0.0, "voxelsize": 0.0001, "area_vx2": 1},
    )
    reports = []
    for name, src in (("honest", honest), ("lying", lying)):
        sub = tmp_path / f"run-{name}"
        sub.mkdir()
        reports.append(_run(sub, _copy_command(src, sub / "out"), sub / "out"))

    assert reports[0]["output"]["surface_area_cm2"] > 0
    assert (
        reports[0]["output"]["surface_area_cm2"]
        == reports[1]["output"]["surface_area_cm2"]
    )
    assert "no area" in reports[0]["output"]["physical"]["area_basis"]


def test_extent_is_recorded_in_voxels_and_microns(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    report = _run(tmp_path, _copy_command(source, output), output)

    extent = report["output"]["extent"]
    assert extent["observed_bbox_xyz"] == [[0.0, 0.0, 10.0], [8.0, 8.0, 10.0]]
    assert extent["extent_voxels_xyz"] == [8.0, 8.0, 0.0]
    assert extent["extent_um_xyz"] == [80.0, 80.0, 0.0]
    assert extent["declared_bbox"]["status"] == "consistent"


def test_stale_declared_bbox_fails_even_though_geometry_is_valid(tmp_path):
    # Valid vertices at z=700 against a declared box ending at z=46: the same
    # shape as the reported stale-in-Z metadata (654 slices beyond the bound).
    stale = _surface(tmp_path / "stale", z0=700.0, bbox=[[0, 0, 10], [8, 8, 46]])
    output = tmp_path / "output"
    report = _run(tmp_path, _copy_command(stale, output), output)

    gate = _gate(report, "spatial_metadata_consistent")
    assert gate["passed"] is False
    assert gate["observed"] == "stale"
    assert gate["stale_axes"] == ["z"]
    assert gate["max_excess_voxels"] == 654.0
    assert report["verdict"] == "PRODUCER_SEMANTIC_FAILURE"
    assert report["output"]["audit"]["grid"]["valid_vertices"] == 25


def test_subvoxel_bbox_rounding_is_not_staleness_but_tolerance_is_adjustable(
    tmp_path,
):
    rounded = _surface(tmp_path / "rounded", bbox=[[0, 0, 10], [7.6, 8, 10]])
    output = tmp_path / "output"
    report = _run(tmp_path, _copy_command(rounded, output), output)
    assert _gate(report, "spatial_metadata_consistent")["passed"] is True

    sub = tmp_path / "strict"
    sub.mkdir()
    strict = _run(
        sub,
        _copy_command(rounded, sub / "out"),
        sub / "out",
        bbox_tolerance_voxels=0.1,
    )
    assert _gate(strict, "spatial_metadata_consistent")["passed"] is False


def test_missing_declared_bbox_is_not_a_stale_bbox(tmp_path):
    bare = _surface(tmp_path / "bare", bbox=None)
    output = tmp_path / "output"
    report = _run(tmp_path, _copy_command(bare, output), output)

    gate = _gate(report, "spatial_metadata_consistent")
    assert gate["passed"] is True and gate["observed"] == "undeclared"
    assert report["output"]["extent"]["observed_bbox_xyz"] is not None


def test_extent_must_lie_inside_declared_volume(tmp_path):
    source = _surface(tmp_path / "source")
    output = tmp_path / "output"
    outside = _run(
        tmp_path,
        _copy_command(source, output),
        output,
        voxel_size_um=7.91,
        volume_meta=_volume_meta(tmp_path, width=100, height=100, slices=5),
    )
    gate = _gate(outside, "extent_within_volume")
    assert gate["evaluated"] is True and gate["passed"] is False
    assert outside["verdict"] == "PRODUCER_SEMANTIC_FAILURE"

    sub = tmp_path / "inside"
    sub.mkdir()
    inside = _run(
        sub,
        _copy_command(source, sub / "out"),
        sub / "out",
        voxel_size_um=7.91,
        volume_meta=_volume_meta(sub, width=100, height=100, slices=100),
    )
    assert _gate(inside, "extent_within_volume")["passed"] is True
    assert inside["verdict"] == "PRODUCER_OK"


def test_volume_meta_without_voxelsize_is_rejected_before_launch(tmp_path):
    source = _surface(tmp_path / "source")
    meta = tmp_path / "volume-meta.json"
    meta.write_text(json.dumps({"width": 10}), encoding="utf-8")
    with pytest.raises(VC3DRunGuardError, match="voxelsize"):
        _run(
            tmp_path,
            _copy_command(source, tmp_path / "output"),
            tmp_path / "output",
            volume_meta=meta,
        )
    assert not (tmp_path / "stdout.log").exists()


def test_noop_copy_of_declared_input_is_a_semantic_failure(tmp_path):
    seed = _surface(tmp_path / "seed")
    output = tmp_path / "output"
    report = _run(
        tmp_path, _copy_command(seed, output), output, input_tifxyz=[seed]
    )

    gate = _gate(report, "output_differs_from_inputs")
    assert gate["evaluated"] is True and gate["passed"] is False
    assert gate["observed"][0]["identical_geometry"] is True
    assert report["verdict"] == "PRODUCER_SEMANTIC_FAILURE"
    assert report["inputs"]["tifxyz"][0]["coordinate_sha256"] == (
        report["output"]["geometry"]["coordinate_sha256"]
    )


def test_reencoded_copy_with_new_uuid_is_still_a_noop(tmp_path):
    seed = _surface(tmp_path / "seed")
    output = tmp_path / "output"
    code = (
        "import json,pathlib,sys,numpy as np;"
        "from PIL import Image;"
        "src=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2]); out.mkdir();"
        "[Image.fromarray(np.array(Image.open(src/n))).save(out/n,compression='tiff_deflate')"
        " for n in ('x.tif','y.tif','z.tif')];"
        "m=json.loads((src/'meta.json').read_text()); m['uuid']='regenerated';"
        "(out/'meta.json').write_text(json.dumps(m))"
    )
    report = _run(
        tmp_path,
        [sys.executable, "-c", code, str(seed), str(output)],
        output,
        input_tifxyz=[seed],
    )

    # The re-encode really happened (bytes differ) and the output decoded, so
    # the failure below is the digest comparison, not a crashed producer.
    assert report["process"]["return_code"] == 0
    assert report["output"]["audit"]["status"] in ("pass", "partial")
    assert report["output"]["audit"]["provenance"]["x.tif"]["sha256"] != (
        hashlib.sha256((seed / "x.tif").read_bytes()).hexdigest()
    )
    gate = _gate(report, "output_differs_from_inputs")
    assert gate["passed"] is False
    assert gate["observed"][0]["identical_geometry"] is True


def test_genuinely_changed_geometry_passes_the_input_relation(tmp_path):
    seed = _surface(tmp_path / "seed")
    grown = _surface(tmp_path / "grown", n=7)
    output = tmp_path / "output"
    report = _run(
        tmp_path,
        _copy_command(grown, output),
        output,
        input_tifxyz=[seed],
        input_relation="grows",
    )

    gate = _gate(report, "output_differs_from_inputs")
    assert gate["passed"] is True and gate["relation"] == "grows"
    assert gate["observed"][0]["input_valid_vertices"] == 25
    assert report["output"]["geometry"]["valid_vertices"] == 49
    assert report["verdict"] == "PRODUCER_OK"


def test_grows_relation_rejects_a_shifted_same_size_surface(tmp_path):
    seed = _surface(tmp_path / "seed")
    shifted = _surface(tmp_path / "shifted", shift=3.0)
    output = tmp_path / "output"

    differs = _run(
        tmp_path,
        _copy_command(shifted, output),
        output,
        input_tifxyz=[seed],
    )
    assert _gate(differs, "output_differs_from_inputs")["passed"] is True

    sub = tmp_path / "grows"
    sub.mkdir()
    grows = _run(
        sub,
        _copy_command(shifted, sub / "out"),
        sub / "out",
        input_tifxyz=[seed],
        input_relation="grows",
    )
    assert _gate(grows, "output_differs_from_inputs")["passed"] is False


def test_producer_that_mutates_its_input_in_place_is_caught(tmp_path):
    seed = _surface(tmp_path / "seed")
    grown = _surface(tmp_path / "grown", n=7)
    output = tmp_path / "output"
    code = (
        "import pathlib,shutil,sys,numpy as np;"
        "from PIL import Image;"
        "seed=pathlib.Path(sys.argv[1]);"
        "x=np.array(Image.open(seed/'x.tif'))+1;"
        "Image.fromarray(x.astype(np.float32)).save(seed/'x.tif');"
        "shutil.copytree(sys.argv[2],sys.argv[3])"
    )
    report = _run(
        tmp_path,
        [sys.executable, "-c", code, str(seed), str(grown), str(output)],
        output,
        input_tifxyz=[seed],
    )

    assert _gate(report, "output_differs_from_inputs")["passed"] is True
    gate = _gate(report, "inputs_unmodified")
    assert gate["passed"] is False
    assert report["verdict"] == "PRODUCER_SEMANTIC_FAILURE"


def test_unreadable_or_missing_input_refuses_to_launch(tmp_path):
    with pytest.raises(VC3DRunGuardError, match="not a directory"):
        _run(
            tmp_path,
            [sys.executable, "-c", "pass"],
            tmp_path / "output",
            input_tifxyz=[tmp_path / "nope"],
        )
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(VC3DRunGuardError, match="unreadable"):
        _run(
            tmp_path,
            [sys.executable, "-c", "pass"],
            tmp_path / "output",
            input_tifxyz=[empty],
        )
    assert not (tmp_path / "stdout.log").exists()


def test_invalid_relation_and_tolerance_are_rejected(tmp_path):
    with pytest.raises(VC3DRunGuardError, match="input_relation"):
        _run(tmp_path, [sys.executable, "-c", "pass"], tmp_path / "o",
             input_relation="supersets")
    with pytest.raises(VC3DRunGuardError, match="bbox_tolerance"):
        _run(tmp_path, [sys.executable, "-c", "pass"], tmp_path / "o",
             bbox_tolerance_voxels=-1)


def test_cli_threads_new_flags_and_reports_verdict(tmp_path, capsys):
    seed = _surface(tmp_path / "seed")
    out = tmp_path / "receipt.json"
    status = main(
        [
            "--output-tifxyz", str(tmp_path / "output"),
            "--volume-root", "PHerc-test/volumes/exact.zarr",
            "--voxel-size-um", "7.91",
            "--stdout-log", str(tmp_path / "stdout.log"),
            "--stderr-log", str(tmp_path / "stderr.log"),
            "--out", str(out),
            "--input-tifxyz", str(seed),
            "--input-relation", "grows",
            "--volume-meta", str(_volume_meta(tmp_path)),
            "--require-verified-voxel-spacing",
            "--",
            *_copy_command(seed, tmp_path / "output"),
        ]
    )
    capsys.readouterr()

    assert status == 2
    receipt = json.loads(out.read_text())
    assert receipt["schema_version"] == 2
    assert receipt["verdict"] == "PRODUCER_SEMANTIC_FAILURE"
    assert receipt["failed_gates"] == ["output_differs_from_inputs"]
    assert receipt["thresholds"]["input_relation"] == "grows"
