import json
import subprocess
import sys
from pathlib import Path

import pytest

from scrollq.flattening_compare import compare_flattenings


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
        source_ref="doi:10.1111/cgf.70000",
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
            "doi:10.1111/cgf.70000",
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
