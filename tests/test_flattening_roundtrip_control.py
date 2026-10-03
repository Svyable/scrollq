import importlib.util
from pathlib import Path

import numpy as np
import pytest

from scrollq.flattening_compare import compare_flattenings
from scrollq.obj_audit import parse_obj

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "artifacts" / "2026-10-03-flattening-tier0" / "roundtrip_control.py"


def _module():
    spec = importlib.util.spec_from_file_location("flattening_roundtrip_control", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_triangle_obj(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "v 0.12345678901234566 0 0",
                "v 1 0.25 0",
                "v 1 1 0.5",
                "v 0 1 0",
                "vt 0 0",
                "vt 1 0",
                "vt 1 1",
                "vt 0 1",
                "f 1/1 2/2 3/3",
                "f 1/1 3/3 4/4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_roundtrip_control_preserves_parsed_geometry_uvs_and_expected_hold(tmp_path):
    module = _module()
    source = _write_triangle_obj(tmp_path / "source.obj")
    candidate = tmp_path / "candidate.obj"

    summary = module.roundtrip_obj(source, candidate)
    before = parse_obj(source)
    after = parse_obj(candidate)

    assert summary == {"vertices": 4, "uvs": 4, "triangles": 2}
    assert np.array_equal(before["vertices"], after["vertices"])
    assert np.array_equal(before["uvs"], after["uvs"])
    assert np.array_equal(before["faces"], after["faces"])
    assert before["face_uvs"] == after["face_uvs"]

    report = compare_flattenings(
        source,
        candidate,
        candidate_method="canonical-obj-roundtrip-negative-control",
        implementation_ref="scrollq:test-fixture",
        implementation_license="MIT",
        min_p95_improvement_fraction=0.01,
    )

    assert report["status"] == "partial"
    assert report["decision"]["verdict"] == "HOLD"
    assert report["inputs"]["geometry_identical"] is True
    assert report["metrics"]["p95_improvement_fraction"] == pytest.approx(0.0)
    assert all(g["passed"] for g in report["gates"] if g["required"])


def test_roundtrip_control_rejects_polygon_inputs_that_would_be_triangulated(tmp_path):
    module = _module()
    source = tmp_path / "quad.obj"
    source.write_text(
        "\n".join(
            [
                "v 0 0 0",
                "v 1 0 0",
                "v 1 1 0",
                "v 0 1 0",
                "vt 0 0",
                "vt 1 0",
                "vt 1 1",
                "vt 0 1",
                "f 1/1 2/2 3/3 4/4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="triangle-only"):
        module.roundtrip_obj(source, tmp_path / "candidate.obj")


def test_roundtrip_control_source_compiles_and_declares_negative_control():
    text = SCRIPT.read_text(encoding="utf-8")
    compile(text, str(SCRIPT), "exec")

    assert "Expected result under scroliq-flatten-compare: HOLD" in text
    assert "not a parameterizer" in text


def test_roundtrip_control_workflow_is_non_promoting_and_json_only():
    workflow_path = ROOT / ".github" / "workflows" / "flattening-tier0-control.yml"
    text = workflow_path.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "Verify pinned public Tier-0 sources" in text
    assert "roundtrip_control.py" in text
    assert 'report["decision"]["verdict"] == "HOLD"' in text
    assert "--implementation-license MIT" in text
    assert r"\${id}" not in text
    assert "${id}.compare.json" in text
    assert "verification.json" in text
    assert "reports/*.compare.json" in text

    upload_block = text.split("- uses: actions/upload-artifact@v4", 1)[1]
    assert "*.obj" not in upload_block
    assert "*.tif" not in upload_block
    assert "*.tifxyz" not in upload_block
