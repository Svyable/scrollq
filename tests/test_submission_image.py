import hashlib
import json

import pytest
from PIL import Image

from scrollq.submission_image import (
    build_banner,
    decorate_column,
    vc_render_um_per_pixel,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vc_render_physical_scale_formula():
    assert vc_render_um_per_pixel(9.362, 0, 1.0) == pytest.approx(9.362)
    assert vc_render_um_per_pixel(9.362, 1, 2.0) == pytest.approx(9.362)
    assert vc_render_um_per_pixel(9.362, 2, 1.0) == pytest.approx(37.448)


@pytest.mark.parametrize(
    ("base", "group_idx", "scale"),
    [(0, 0, 1), (9.362, -1, 1), (9.362, 0, 0)],
)
def test_vc_render_physical_scale_rejects_invalid_inputs(base, group_idx, scale):
    with pytest.raises(ValueError):
        vc_render_um_per_pixel(base, group_idx, scale)


def test_column_image_has_computed_one_cm_bar_and_proof(tmp_path):
    src = tmp_path / "raw.tif"
    dst = tmp_path / "column_01.tif"
    meta = tmp_path / "column_01.scale.json"
    Image.new("L", (180, 24), 17).save(src)

    proof = decorate_column(
        src,
        dst,
        base_voxel_size_um=100.0,
        group_idx=0,
        render_scale=1.0,
        column=1,
        metadata_path=meta,
    )

    assert proof["vc_render_tifxyz"]["micrometers_per_output_pixel"] == 100.0
    assert proof["scale_bar"]["pixels"] == 100
    assert proof["scale_bar"]["centimeters"] == 1
    assert proof["input"]["sha256"] == _sha(src)
    assert proof["output"]["sha256"] == _sha(dst)
    assert json.loads(meta.read_text()) == proof

    with Image.open(dst) as image:
        assert image.size == (180, 72)
        # Source render is copied byte-for-byte in pixel values.
        assert image.getpixel((10, 10)) == 17
        # 100-pixel white bar begins at x=16.
        y = proof["scale_bar"]["y"]
        assert image.getpixel((16, y)) == 255
        assert image.getpixel((115, y)) == 255
        assert image.getpixel((116, y)) == 0


def test_column_image_fails_if_true_one_cm_bar_cannot_fit(tmp_path):
    src = tmp_path / "raw.tif"
    Image.new("L", (80, 20), 0).save(src)

    with pytest.raises(ValueError, match="needs 100 px"):
        decorate_column(
            src,
            tmp_path / "column_01.tif",
            base_voxel_size_um=100.0,
            group_idx=0,
            render_scale=1.0,
            column=1,
        )


def test_column_generator_refuses_overwrite(tmp_path):
    src = tmp_path / "raw.tif"
    dst = tmp_path / "column_01.tif"
    Image.new("L", (180, 20), 0).save(src)
    Image.new("L", (10, 10), 0).save(dst)

    with pytest.raises(FileExistsError):
        decorate_column(
            src,
            dst,
            base_voxel_size_um=100.0,
            group_idx=0,
            render_scale=1.0,
            column=1,
        )


def test_banner_sorts_columns_and_overlays_numbers(tmp_path):
    c2 = tmp_path / "column_02.tif"
    c1 = tmp_path / "column_01.tif"
    Image.new("L", (30, 20), 40).save(c2)
    Image.new("L", (20, 20), 80).save(c1)
    out = tmp_path / "banner.tif"
    meta = tmp_path / "banner.json"

    proof = build_banner([c2, c1], out, metadata_path=meta, max_column_height=20)

    assert [row["column"] for row in proof["columns"]] == [1, 2]
    assert proof["column_numbers_overlaid"] is True
    assert proof["output"]["sha256"] == _sha(out)
    assert json.loads(meta.read_text()) == proof
    with Image.open(out) as image:
        assert image.size == (20 + 8 + 30, 28 + 20)
        # First column content starts after the label strip.
        assert image.getpixel((5, 30)) == (80, 80, 80)
        # Label pixels are white against the black strip.
        assert max(image.getpixel((x, 8))[0] for x in range(4, 24)) == 255


def test_banner_requires_consecutive_column_numbers(tmp_path):
    c1 = tmp_path / "column_01.tif"
    c3 = tmp_path / "column_03.tif"
    Image.new("L", (20, 20), 0).save(c1)
    Image.new("L", (20, 20), 0).save(c3)

    with pytest.raises(ValueError, match="consecutive"):
        build_banner([c1, c3], tmp_path / "banner.tif")
