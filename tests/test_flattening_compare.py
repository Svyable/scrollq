import json
import subprocess
import sys
from pathlib import Path

import pytest

import numpy as np

from scrollq.flattening_compare import _uv_seam_edges, compare_flattenings
from scrollq.obj_audit import parse_obj


def _write_obj(path: Path, *, uv_mode: str = "square", z_offset: float = 0.0) -> Path:
    vertices = [
        (0.0, 0.0, z_offset),
        (1.0, 0.0, z_offset),
        (1.0, 1.0, z_offset),
        (0.0, 1.0, z_offset),
    ]
    if uv_mode == "stretched":
        uvs = [(0.0, 0.0), (2.0, 0.0), (2.0, 0.5), (0.0, 0.5)]
        faces = ["f 1/1 2/2 3/3", "f 1/1 3/3 4/4"]
    elif uv_mode == "square":
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        faces = ["f 1/1 2/2 3/3", "f 1/1 3/3 4/4"]
    elif uv_mode == "one-flip":
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        faces = ["f 1/1 2/2 3/3", "f 1/1 3/4 4/3"]
    elif uv_mode == "none":
        uvs = []
        faces = ["f 1 2 3", "f 1 3 4"]
    else:
        raise ValueError(uv_mode)

    lines = [*(f"v {x} {y} {z}" for x, y, z in vertices)]
    lines.extend(f"vt {u} {v}" for u, v in uvs)
    lines.extend(faces)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _compare(tmp_path, candidate_mode="square", **kwargs):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode=candidate_mode)
    return compare_flattenings(
        baseline,
        candidate,
        candidate_method="beltrami-prolongation-independent-prototype",
        source_ref="doi:10.1111/cgf.70341",
        implementation_ref="git:deadbeef",
        implementation_license="MIT",
        **kwargs,
    )


def test_promotes_same_geometry_with_materially_better_injective_uvs(tmp_path):
    report = _compare(tmp_path)

    assert report["status"] == "pass"
    assert report["decision"]["verdict"] == "PROMOTE"
    assert report["inputs"]["geometry_identical"] is True
    assert report["selection_contract"]["ink_inputs_consumed"] is False
    assert report["metrics"]["candidate"]["flipped_uv_triangles"] == 0
    assert report["metrics"]["candidate"]["p95_symmetric_stretch"] == pytest.approx(1.0)
    assert report["metrics"]["baseline"]["p95_symmetric_stretch"] == pytest.approx(2.0)
    assert report["metrics"]["p95_improvement_fraction"] == pytest.approx(0.5)


def test_holds_safe_candidate_when_improvement_is_below_predeclared_threshold(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="square")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")

    report = compare_flattenings(
        baseline,
        candidate,
        candidate_method="control",
        implementation_ref="git:abc",
        implementation_license="MIT",
        min_p95_improvement_fraction=0.01,
    )

    assert report["status"] == "partial"
    assert report["decision"]["verdict"] == "HOLD"
    assert all(g["passed"] for g in report["gates"] if g["required"])


def test_rejects_uv_foldover_even_when_3d_geometry_is_identical(tmp_path):
    report = _compare(tmp_path, candidate_mode="one-flip")

    assert report["decision"]["verdict"] == "REJECT"
    gate = {g["name"]: g for g in report["gates"]}
    assert gate["geometry_identity"]["passed"] is True
    assert gate["candidate_zero_uv_foldovers"]["passed"] is False


def test_rejects_changed_3d_geometry(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square", z_offset=0.25)

    report = compare_flattenings(
        baseline,
        candidate,
        candidate_method="not-the-same-surface",
        implementation_ref="git:abc",
        implementation_license="MIT",
    )

    assert report["decision"]["verdict"] == "REJECT"
    assert report["inputs"]["geometry_identical"] is False
    assert any("exact ordered 3-D" in e for e in report["errors"])


def test_rejects_unverified_or_nonpermissive_implementation_license(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")

    report = compare_flattenings(
        baseline,
        candidate,
        candidate_method="external-binary",
        implementation_ref="release:1",
        implementation_license="UNVERIFIED",
    )

    assert report["decision"]["verdict"] == "REJECT"
    gate = {g["name"]: g for g in report["gates"]}
    assert gate["permissive_implementation_license"]["passed"] is False


def test_rejects_candidate_without_uv_parameterization(tmp_path):
    report = _compare(tmp_path, candidate_mode="none")

    assert report["decision"]["verdict"] == "REJECT"
    assert any("no measured UV-to-3D isometry" in e for e in report["errors"])


def test_cli_require_promote_emits_machine_readable_report(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")
    out = tmp_path / "compare.json"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scrollq.flattening_compare",
            "--baseline-obj",
            str(baseline),
            "--candidate-obj",
            str(candidate),
            "--candidate-method",
            "beltrami-prolongation-independent-prototype",
            "--source-ref",
            "doi:10.1111/cgf.70341",
            "--implementation-ref",
            "git:deadbeef",
            "--implementation-license",
            "MIT",
            "--out",
            str(out),
            "--require-promote",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["decision"]["verdict"] == "PROMOTE"


def _write_curved_sheet(path: Path, *, mode: str, n: int = 8) -> Path:
    """Quarter-cylinder patch. ``shared`` is one anisotropic chart; ``shattered``
    lays every triangle out isometrically as its own island."""
    theta = np.linspace(0.0, np.pi / 2, n)
    height = np.linspace(0.0, 3.0, n)
    verts = np.array([[np.cos(t), np.sin(t), z] for z in height for t in theta])
    tris = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j
            tris += [(a, b, c), (a, c, d)]
    lines = [f"v {x:.9f} {y:.9f} {z:.9f}" for x, y, z in verts]
    if mode == "shared":
        lines += [f"vt {1.5 * j / (n - 1) * np.pi / 2:.9f} {height[i]:.9f}"
                  for i in range(n) for j in range(n)]
        lines += [f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}" for a, b, c in tris]
    else:
        faces = []
        for k, (a, b, c) in enumerate(tris):
            e1, e2 = verts[b] - verts[a], verts[c] - verts[a]
            u = float(np.linalg.norm(e1))
            x = float(e1 @ e2) / u
            y = float(np.sqrt(max(e2 @ e2 - x * x, 0.0)))
            ox, oy = float(k % 20), float(k // 20)
            lines += [f"vt {ox:.9f} {oy:.9f}", f"vt {ox + u:.9f} {oy:.9f}",
                      f"vt {ox + x:.9f} {oy + y:.9f}"]
            faces.append(f"f {a+1}/{3*k+1} {b+1}/{3*k+2} {c+1}/{3*k+3}")
        lines += faces
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _compare_files(baseline, candidate):
    return compare_flattenings(
        baseline,
        candidate,
        candidate_method="fragmentation-control",
        implementation_ref="git:control",
        implementation_license="MIT",
    )


def test_rejects_candidate_that_wins_by_shattering_the_atlas(tmp_path):
    baseline = _write_curved_sheet(tmp_path / "baseline.obj", mode="shared")
    candidate = _write_curved_sheet(tmp_path / "candidate.obj", mode="shattered")

    report = _compare_files(baseline, candidate)

    gate = {g["name"]: g for g in report["gates"]}
    # Everything the pre-seam gate looked at is satisfied, with a real "improvement"...
    assert gate["geometry_identity"]["passed"] is True
    assert gate["candidate_zero_uv_foldovers"]["passed"] is True
    assert gate["p95_isometry_nonregression"]["passed"] is True
    assert report["metrics"]["candidate"]["p95_symmetric_stretch"] == pytest.approx(1.0, abs=1e-6)
    assert report["metrics"]["p95_improvement_fraction"] > 0.01
    # ...so only the seam gate stands between that and PROMOTE.
    assert gate["candidate_no_new_uv_seams"]["passed"] is False
    assert report["metrics"]["uv_seams"]["baseline_edges"] == 0
    assert report["metrics"]["uv_seams"]["candidate_new_edges"] > 0
    assert report["decision"]["verdict"] == "REJECT"


def test_candidate_with_fewer_cuts_than_the_baseline_is_allowed(tmp_path):
    baseline = tmp_path / "baseline.obj"  # stretched, and cut along the shared diagonal
    baseline.write_text(
        "\n".join(
            [
                "v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0",
                "vt 0 0", "vt 2 0", "vt 2 0.5",
                "vt 3 0", "vt 5 0.5", "vt 3 0.5",
                "f 1/1 2/2 3/3",
                "f 1/4 3/5 4/6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")  # continuous

    report = _compare_files(baseline, candidate)

    assert report["metrics"]["uv_seams"] == {
        "baseline_edges": 1,
        "candidate_edges": 0,
        "candidate_new_edges": 0,
    }
    assert report["decision"]["verdict"] == "PROMOTE"


def test_uv_seam_edges_compares_coordinates_not_vt_indices(tmp_path):
    continuous = parse_obj(_write_obj(tmp_path / "a.obj", uv_mode="square"))
    assert _uv_seam_edges(continuous) == set()

    # Same coordinates, but the second face uses its own duplicated vt rows.
    duplicated = tmp_path / "dup.obj"
    duplicated.write_text(
        "\n".join(
            [
                "v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0",
                "vt 0 0", "vt 1 0", "vt 1 1", "vt 0 0", "vt 1 1", "vt 0 1",
                "f 1/1 2/2 3/3",
                "f 1/4 3/5 4/6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert _uv_seam_edges(parse_obj(duplicated)) == set()

    # Move one endpoint of the shared diagonal in the second face: that edge is a cut.
    cut = tmp_path / "cut.obj"
    cut.write_text(duplicated.read_text().replace("vt 1 1\nvt 0 1", "vt 1.5 1\nvt 0 1"),
                   encoding="utf-8")
    assert _uv_seam_edges(parse_obj(cut)) == {(0, 2)}

    assert _uv_seam_edges(parse_obj(_write_obj(tmp_path / "n.obj", uv_mode="none"))) == set()
