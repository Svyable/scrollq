import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from scrollq import sheetness_plan as plan


def _write_float_tiff(path: Path, array: np.ndarray) -> None:
    Image.fromarray(np.asarray(array, dtype=np.float32), mode="F").save(path)


def _surface(tmp_path: Path, token="20250728140407") -> Path:
    root = tmp_path / f"reference-on-{token}-9.362um.tifxyz"
    root.mkdir()
    h, w = 7, 9
    yy, xx = np.mgrid[:h, :w]
    # Flat sheet at global Z=10 in TIFXYZ XYZ convention.
    _write_float_tiff(root / "x.tif", 5.0 + xx)
    _write_float_tiff(root / "y.tif", 6.0 + yy)
    _write_float_tiff(root / "z.tif", np.full((h, w), 10.0))
    (root / "meta.json").write_text(
        json.dumps({"format": "tifxyz", "target_volume": token}),
        encoding="utf-8",
    )
    return root


def _zpa(tmp_path: Path, root: str) -> Path:
    path = tmp_path / "zpa.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.3.0",
                "tool": "zarr-pyramid-audit",
                "root": root,
                "integrity": "PASS",
                "source_attestation": {
                    "algorithm": "zpa-metadata-semantics-v1",
                    "state": "PRESENT",
                    "metadata_semantics_sha256": "b" * 64,
                    "axes": ["z", "y", "x"],
                },
                "levels": [
                    {
                        "index": 0,
                        "shape": [30, 30, 30],
                        "chunks": [4, 4, 4],
                        "dtype": "|u1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _build(tmp_path: Path, *, samples=3, offsets=(-2.0, 2.0), halo=2):
    token = "20250728140407"
    volume_root = f"PHerc0139/volumes/{token}-9.362um-1.2m-113keV-masked.zarr"
    surface = _surface(tmp_path, token)
    zpa = _zpa(tmp_path, volume_root)
    result = plan.build_plan(
        tifxyz=surface,
        zpa_report_path=zpa,
        volume_root=volume_root,
        surface_volume_token=token,
        binding_url="https://scrollprize.org/tutorial5",
        samples=samples,
        offsets=offsets,
        halo=halo,
        validate_report_fn=lambda _report: [],
    )
    return result, surface, zpa


def test_plan_is_geometry_only_and_deterministic(tmp_path):
    first, surface, zpa = _build(tmp_path)
    second = plan.build_plan(
        tifxyz=surface,
        zpa_report_path=zpa,
        volume_root=first["volume_root"],
        surface_volume_token="20250728140407",
        binding_url="https://scrollprize.org/tutorial5",
        samples=3,
        offsets=(-2.0, 2.0),
        halo=2,
        validate_report_fn=lambda _report: [],
    )

    assert first == second
    assert first["schema"] == "scroliq-sheetness-plan/1"
    assert first["protocol"]["sample_selection"]["uses_ct_intensity"] is False
    assert first["protocol"]["sample_selection"]["uses_sheetness_response"] is False
    assert first["protocol"]["sample_selection"]["random_state"] is None
    assert len(first["groups"]) == 3
    assert all(
        row["wrong_wrap"]["status"] == "pending-independent-geometry"
        for row in first["groups"]
    )


def test_flat_sheet_normals_and_offsets_are_in_global_zyx(tmp_path):
    result, _, _ = _build(tmp_path, samples=1, offsets=(-2.0, 2.0), halo=2)
    row = result["groups"][0]

    # Cross-product sign is arbitrary, so only the thin axis matters.
    normal = np.asarray(row["reference_normal_zyx"])
    assert abs(normal[0]) == pytest.approx(1.0)
    assert normal[1] == pytest.approx(0.0)
    assert normal[2] == pytest.approx(0.0)

    surface_z = row["surface_global_zyx"][0]
    offset_z = sorted(item["global_zyx"][0] for item in row["normal_offsets"])
    assert offset_z == pytest.approx([surface_z - 2.0, surface_z + 2.0])

    bbox = row["cutout_bbox_zyx_half_open"]
    assert bbox["start"][0] <= 6
    assert bbox["stop"][0] >= 15


def test_even_quantile_selection_spans_eligible_geometry(tmp_path):
    result, _, _ = _build(tmp_path, samples=3)
    ranks = result["protocol"]["sample_selection"]["selected_eligible_ranks"]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 3
    assert ranks[0] > 0
    assert ranks[-1] < result["protocol"]["sample_selection"]["eligible_vertex_count"]



def test_vectorized_two_pass_matches_scalar_candidate_order(tmp_path):
    result, surface, _zpa_path = _build(
        tmp_path, samples=4, offsets=(-2.0, 2.0), halo=2
    )
    xyz, valid, _info = plan._load_surface(surface)
    scalar_grid_yx = []
    source_shape = (30, 30, 30)
    offsets = (-2.0, 2.0)
    halo = 2

    h, w = valid.shape
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            normal_xyz = plan._normal_at_grid(xyz, valid, y, x)
            if normal_xyz is None:
                continue
            surface_xyz = np.asarray(xyz[y, x], dtype=np.float64)
            points = [plan._xyz_to_zyx(surface_xyz)]
            for distance in offsets:
                points.append(
                    plan._xyz_to_zyx(surface_xyz + distance * normal_xyz)
                )
            if plan._bbox_for_points(
                points, halo=halo, source_shape=source_shape
            ) is not None:
                scalar_grid_yx.append([y, x])

    ranks = result["protocol"]["sample_selection"]["selected_eligible_ranks"]
    assert result["protocol"]["sample_selection"]["implementation"] == (
        "row-vectorized-two-pass-v1"
    )
    assert [row["grid_yx"] for row in result["groups"]] == [
        scalar_grid_yx[rank] for rank in ranks
    ]

def test_source_binding_token_must_match_surface_and_volume(tmp_path):
    token = "20250728140407"
    volume_root = f"PHerc0139/volumes/{token}-9.362um-1.2m-113keV-masked.zarr"
    surface = _surface(tmp_path, "OTHER")
    zpa = _zpa(tmp_path, volume_root)

    with pytest.raises(plan.PlanError, match="not present"):
        plan.build_plan(
            tifxyz=surface,
            zpa_report_path=zpa,
            volume_root=volume_root,
            surface_volume_token=token,
            binding_url="https://scrollprize.org/tutorial5",
            samples=1,
            offsets=(-2.0, 2.0),
            halo=2,
            validate_report_fn=lambda _report: [],
        )


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda r: r.update(integrity="WARN"), "integrity must be PASS"),
        (lambda r: r.update(root="other.zarr"), "does not exactly match"),
        (
            lambda r: r["source_attestation"].update(axes=["x", "y", "z"]),
            "axes must be exactly",
        ),
    ],
)
def test_zpa_binding_fails_closed(tmp_path, mutation, message):
    token = "20250728140407"
    volume_root = f"PHerc0139/volumes/{token}-9.362um-1.2m-113keV-masked.zarr"
    surface = _surface(tmp_path, token)
    zpa = _zpa(tmp_path, volume_root)
    report = json.loads(zpa.read_text())
    mutation(report)
    zpa.write_text(json.dumps(report))

    with pytest.raises(plan.PlanError, match=message):
        plan.build_plan(
            tifxyz=surface,
            zpa_report_path=zpa,
            volume_root=volume_root,
            surface_volume_token=token,
            binding_url="https://scrollprize.org/tutorial5",
            samples=1,
            offsets=(-2.0, 2.0),
            halo=2,
            validate_report_fn=lambda _report: [],
        )


def test_offsets_require_both_sides_and_bounded_halo(tmp_path):
    result, surface, zpa = _build(tmp_path)
    with pytest.raises(plan.PlanError, match="negative and positive"):
        plan.build_plan(
            tifxyz=surface,
            zpa_report_path=zpa,
            volume_root=result["volume_root"],
            surface_volume_token="20250728140407",
            binding_url="https://scrollprize.org/tutorial5",
            samples=1,
            offsets=(2.0, 4.0),
            halo=2,
            validate_report_fn=lambda _report: [],
        )

    with pytest.raises(plan.PlanError, match="eligible surface vertices"):
        plan.build_plan(
            tifxyz=surface,
            zpa_report_path=zpa,
            volume_root=result["volume_root"],
            surface_volume_token="20250728140407",
            binding_url="https://scrollprize.org/tutorial5",
            samples=1,
            offsets=(-20.0, 20.0),
            halo=10,
            validate_report_fn=lambda _report: [],
        )


def test_cli_is_create_only(tmp_path, monkeypatch, capsys):
    result, surface, zpa = _build(tmp_path)
    out = tmp_path / "plan.json"
    args = [
        "--tifxyz", str(surface),
        "--zpa-report", str(zpa),
        "--volume-root", result["volume_root"],
        "--surface-volume-token", "20250728140407",
        "--binding-url", "https://scrollprize.org/tutorial5",
        "--samples", "2",
        "--offsets=-2,2",
        "--halo", "2",
        "--out", str(out),
    ]
    monkeypatch.setattr(plan, "validate_zpa_report", lambda _report: [])
    # main's default argument captured the original validator in build_plan, so
    # exercise create-only behavior with an existing target before validation.
    out.write_text("keep")
    assert plan.main(args) == 2
    assert out.read_text() == "keep"
    assert "refusing to overwrite" in capsys.readouterr().out
