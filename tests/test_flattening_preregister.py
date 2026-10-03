import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scrollq.flattening_preregister import evaluate_spec, seal_spec


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
    else:
        raise ValueError(uv_mode)

    lines = [*(f"v {x} {y} {z}" for x, y, z in vertices)]
    lines.extend(f"vt {u} {v}" for u, v in uvs)
    lines.extend(faces)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _seal(tmp_path: Path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    spec = seal_spec(
        baseline,
        experiment_id="sealed-case-01",
        candidate_method="beltrami-coefficient-prolongation",
        source_ref="doi:10.1111/cgf.70341",
        implementation_ref="git:independent-mit-prototype",
        implementation_license="MIT",
        corpus_role="ordinary-curved-control",
        source_mesh_ref="public:fixture-01",
        min_p95_improvement_fraction=0.01,
    )
    return baseline, spec


def test_seal_spec_binds_baseline_and_rules_without_candidate_metrics(tmp_path):
    baseline, spec = _seal(tmp_path)

    assert spec["tool"] == "scroliq-flatten-plan"
    assert spec["selection_contract"]["ink_inputs_consumed"] is False
    assert spec["selection_contract"]["candidate_metrics_observed_when_sealed"] is False
    assert spec["baseline"]["sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()
    assert len(spec["baseline"]["geometry_sha256"]) == 64
    assert spec["candidate_method"]["implementation_license"] == "MIT"
    assert spec["thresholds"]["min_p95_improvement_fraction"] == pytest.approx(0.01)
    assert spec["corpus"]["role"] == "ordinary-curved-control"


def test_evaluate_spec_promotes_candidate_using_sealed_rules(tmp_path):
    baseline, spec = _seal(tmp_path)
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")

    result = evaluate_spec(spec, baseline, candidate, spec_sha256="a" * 64)

    assert result["status"] == "pass"
    assert result["decision"]["verdict"] == "PROMOTE"
    assert result["preregistration"]["binding_passed"] is True
    assert result["preregistration"]["threshold_source"] == "sealed-spec"
    assert result["preregistration"]["candidate_metadata_source"] == "sealed-spec"
    assert result["preregistration"]["spec_sha256"] == "a" * 64


def test_evaluate_spec_rejects_modified_baseline_even_if_candidate_is_good(tmp_path):
    baseline, spec = _seal(tmp_path)
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")

    _write_obj(baseline, uv_mode="stretched", z_offset=0.25)
    result = evaluate_spec(spec, baseline, candidate)

    assert result["status"] == "fail"
    assert result["decision"]["verdict"] == "REJECT"
    assert result["preregistration"]["binding_passed"] is False
    assert any("baseline OBJ SHA-256" in e for e in result["errors"])


def test_sealed_academic_only_candidate_is_still_rejected_by_license_gate(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")
    spec = seal_spec(
        baseline,
        experiment_id="academic-only-control",
        candidate_method="upstream-reference",
        implementation_ref="public-upstream",
        implementation_license="ACADEMIC-ONLY",
    )

    result = evaluate_spec(spec, baseline, candidate)

    assert result["decision"]["verdict"] == "REJECT"
    gates = {g["name"]: g for g in result["gates"]}
    assert gates["permissive_implementation_license"]["passed"] is False


def test_cli_seal_then_evaluate_round_trip(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")
    spec_path = tmp_path / "spec.json"
    result_path = tmp_path / "result.json"

    seal = subprocess.run(
        [
            sys.executable,
            "-m",
            "scrollq.flattening_preregister",
            "seal",
            "--baseline-obj",
            str(baseline),
            "--experiment-id",
            "cli-case",
            "--candidate-method",
            "beltrami-coefficient-prolongation",
            "--source-ref",
            "doi:10.1111/cgf.70341",
            "--implementation-ref",
            "git:independent-mit-prototype",
            "--implementation-license",
            "MIT",
            "--out",
            str(spec_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert seal.returncode == 0, seal.stderr

    evaluate = subprocess.run(
        [
            sys.executable,
            "-m",
            "scrollq.flattening_preregister",
            "evaluate",
            "--spec",
            str(spec_path),
            "--baseline-obj",
            str(baseline),
            "--candidate-obj",
            str(candidate),
            "--out",
            str(result_path),
            "--require-promote",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert evaluate.returncode == 0, evaluate.stderr

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["decision"]["verdict"] == "PROMOTE"
    assert result["preregistration"]["spec_sha256"] == hashlib.sha256(
        spec_path.read_bytes()
    ).hexdigest()


def test_cli_evaluate_has_no_threshold_or_implementation_override_flags(tmp_path):
    baseline = _write_obj(tmp_path / "baseline.obj", uv_mode="stretched")
    candidate = _write_obj(tmp_path / "candidate.obj", uv_mode="square")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            seal_spec(
                baseline,
                experiment_id="locked",
                candidate_method="candidate",
                implementation_ref="git:abc",
                implementation_license="MIT",
            )
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scrollq.flattening_preregister",
            "evaluate",
            "--spec",
            str(spec_path),
            "--baseline-obj",
            str(baseline),
            "--candidate-obj",
            str(candidate),
            "--out",
            str(tmp_path / "out.json"),
            "--max-p95-ratio",
            "99",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "unrecognized arguments" in proc.stderr
