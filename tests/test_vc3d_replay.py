from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from scrollq.vc3d_replay import VC3DError, render_column, verify_receipt


VOLUME_ID = "20250521134555-8.64um-test-volume"


def _write_mesh(root: Path, *, column: int = 1, volume_id: str = VOLUME_ID) -> Path:
    mesh = root / f"column_{column:02d}.tifxyz"
    mesh.mkdir()
    (mesh / "meta.json").write_text(
        json.dumps(
            {
                "format": "tifxyz",
                "target_volume": f"/data/{volume_id}.zarr",
                "scroll_source": "PHercTEST",
                "scale": [0.05, 0.05],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for name, payload in (
        ("x.tif", b"x-grid"),
        ("y.tif", b"y-grid"),
        ("z.tif", b"z-grid"),
    ):
        (mesh / name).write_bytes(payload)
    return mesh


def _write_fake_vc(root: Path) -> Path:
    binary = root / "vc_render_tifxyz"
    binary.write_text(
        """#!/usr/bin/env python3
import sys
from pathlib import Path
from PIL import Image

if "--help" in sys.argv:
    print("vc_render_tifxyz: Render volume data using segmentation surfaces")
    print("--volume --segmentation --scale --group-idx --tif-output --voxel-size")
    raise SystemExit(0)

def value(flag):
    i = sys.argv.index(flag)
    return sys.argv[i + 1]

out = Path(value("--tif-output"))
out.mkdir(parents=True, exist_ok=True)
Image.new("L", (32, 20), 73).save(out / "00.tif")
print("Rendering:", value("--segmentation"), "from", value("--volume"))
print("scale", value("--scale"), "group", value("--group-idx"))
print("voxel", value("--voxel-size"), value("--voxel-unit"))
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def _render(root: Path):
    mesh = _write_mesh(root)
    binary = _write_fake_vc(root)
    receipt = render_column(
        root_dir=root,
        binary=str(binary),
        vc_commit="a" * 40,
        volume=f"/eligible/{VOLUME_ID}.zarr",
        volume_id=VOLUME_ID,
        mesh=mesh,
        column=1,
        base_voxel_size_um=8.64,
        group_idx=0,
        scale=1.0,
        tif_output_dir="raw/column_01",
        receipt_path="evidence/column_01.vc3d.json",
        log_path="evidence/column_01.vc3d.log",
        extra_args=["--auto-crop", "--surface-interpolation", "smooth"],
    )
    return mesh, binary, receipt


def test_render_receipt_binds_binary_mesh_volume_command_and_output(tmp_path):
    mesh, binary, receipt = _render(tmp_path)

    assert receipt["tool"] == "scroliq-vc3d"
    assert receipt["column"] == 1
    assert receipt["vc3d"]["commit"] == "a" * 40
    assert receipt["vc3d"]["binary"]["name"] == "vc_render_tifxyz"
    assert receipt["inputs"]["volume"]["volume_id"] == VOLUME_ID
    assert receipt["inputs"]["mesh"]["path"] == "column_01.tifxyz"
    assert receipt["inputs"]["mesh"]["target_volume"].endswith(
        f"{VOLUME_ID}.zarr"
    )
    assert receipt["render"]["num_slices"] == 1
    assert receipt["render"]["extra_args"] == [
        "--auto-crop",
        "--surface-interpolation",
        "smooth",
    ]
    assert "--voxel-size" in receipt["render"]["argv"]
    assert "micrometer" in receipt["render"]["argv"]
    assert receipt["output"]["path"] == "raw/column_01/00.tif"
    assert receipt["output"]["width"] == 32
    assert receipt["output"]["height"] == 20
    assert receipt["output"]["mode"] == "L"
    assert (tmp_path / receipt["log"]["path"]).read_text().startswith("Rendering:")

    report = verify_receipt(
        "evidence/column_01.vc3d.json",
        root_dir=tmp_path,
        binary=str(binary),
    )
    assert report["valid"] is True
    assert report["errors"] == []


@pytest.mark.parametrize(
    "extra",
    [
        ["--volume", "/wrong.zarr"],
        ["--scale=4"],
        ["--group-idx", "2"],
        ["--num-slices", "9"],
        ["--tif-output", "elsewhere"],
        ["--voxel-size", "1"],
        ["--zarr-output", "other.zarr"],
    ],
)
def test_render_rejects_overrides_of_receipt_critical_flags(tmp_path, extra):
    mesh = _write_mesh(tmp_path)
    binary = _write_fake_vc(tmp_path)

    with pytest.raises(VC3DError, match="controlled"):
        render_column(
            root_dir=tmp_path,
            binary=str(binary),
            vc_commit="b" * 40,
            volume=f"/eligible/{VOLUME_ID}.zarr",
            volume_id=VOLUME_ID,
            mesh=mesh,
            column=1,
            base_voxel_size_um=8.64,
            group_idx=0,
            scale=1.0,
            tif_output_dir="raw",
            receipt_path="receipt.json",
            log_path="render.log",
            extra_args=extra,
        )


def test_render_rejects_mesh_for_wrong_volume(tmp_path):
    mesh = _write_mesh(tmp_path, volume_id="different-volume")
    binary = _write_fake_vc(tmp_path)

    with pytest.raises(VC3DError, match="exact eligible volume"):
        render_column(
            root_dir=tmp_path,
            binary=str(binary),
            vc_commit="c" * 40,
            volume=f"/eligible/{VOLUME_ID}.zarr",
            volume_id=VOLUME_ID,
            mesh=mesh,
            column=1,
            base_voxel_size_um=8.64,
            group_idx=0,
            scale=1.0,
            tif_output_dir="raw",
            receipt_path="receipt.json",
            log_path="render.log",
        )


def test_render_rejects_column_name_mismatch(tmp_path):
    mesh = _write_mesh(tmp_path, column=2)
    binary = _write_fake_vc(tmp_path)

    with pytest.raises(VC3DError, match="does not match mesh name"):
        render_column(
            root_dir=tmp_path,
            binary=str(binary),
            vc_commit="d" * 40,
            volume=f"/eligible/{VOLUME_ID}.zarr",
            volume_id=VOLUME_ID,
            mesh=mesh,
            column=1,
            base_voxel_size_um=8.64,
            group_idx=0,
            scale=1.0,
            tif_output_dir="raw",
            receipt_path="receipt.json",
            log_path="render.log",
        )


def test_verifier_detects_raw_render_tampering(tmp_path):
    _, binary, receipt = _render(tmp_path)
    Image.new("L", (32, 20), 99).save(tmp_path / receipt["output"]["path"])

    report = verify_receipt(
        "evidence/column_01.vc3d.json",
        root_dir=tmp_path,
        binary=str(binary),
    )

    assert report["valid"] is False
    assert any("raw render sha256 mismatch" in error for error in report["errors"])


def test_verifier_detects_mesh_tampering(tmp_path):
    mesh, binary, _ = _render(tmp_path)
    (mesh / "x.tif").write_bytes(b"tampered")

    report = verify_receipt(
        "evidence/column_01.vc3d.json",
        root_dir=tmp_path,
        binary=str(binary),
    )

    assert report["valid"] is False
    assert any("mesh sha256 mismatch" in error for error in report["errors"])


def test_verifier_detects_log_tampering(tmp_path):
    _, binary, receipt = _render(tmp_path)
    with (tmp_path / receipt["log"]["path"]).open("ab") as fh:
        fh.write(b"tampered\n")

    report = verify_receipt(
        "evidence/column_01.vc3d.json",
        root_dir=tmp_path,
        binary=str(binary),
    )

    assert report["valid"] is False
    assert any("render log" in error and "mismatch" in error for error in report["errors"])


def test_verifier_detects_binary_tampering(tmp_path):
    _, binary, _ = _render(tmp_path)
    binary.write_text(binary.read_text() + "\n# tampered\n", encoding="utf-8")
    binary.chmod(0o755)

    report = verify_receipt(
        "evidence/column_01.vc3d.json",
        root_dir=tmp_path,
        binary=str(binary),
    )

    assert report["valid"] is False
    assert any("binary" in error and "mismatch" in error for error in report["errors"])


def test_render_rejects_receipt_inside_tiff_output_dir(tmp_path):
    mesh = _write_mesh(tmp_path)
    binary = _write_fake_vc(tmp_path)

    with pytest.raises(VC3DError, match="receipt may not live inside"):
        render_column(
            root_dir=tmp_path,
            binary=str(binary),
            vc_commit="e" * 40,
            volume=f"/eligible/{VOLUME_ID}.zarr",
            volume_id=VOLUME_ID,
            mesh=mesh,
            column=1,
            base_voxel_size_um=8.64,
            group_idx=0,
            scale=1.0,
            tif_output_dir="raw",
            receipt_path="raw/receipt.json",
            log_path="render.log",
        )


def test_render_rejects_symlink_output_directory(tmp_path):
    mesh = _write_mesh(tmp_path)
    binary = _write_fake_vc(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "raw"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(VC3DError, match="not a symlink"):
        render_column(
            root_dir=tmp_path,
            binary=str(binary),
            vc_commit="f" * 40,
            volume=f"/eligible/{VOLUME_ID}.zarr",
            volume_id=VOLUME_ID,
            mesh=mesh,
            column=1,
            base_voxel_size_um=8.64,
            group_idx=0,
            scale=1.0,
            tif_output_dir=link,
            receipt_path="receipt.json",
            log_path="render.log",
        )
