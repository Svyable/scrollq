import os
import subprocess

import numpy as np
import pytest

from scrollq.subgrid_run import (
    SubgridRunError,
    run_candidate,
    validate_explicit_npz,
    verify_checkout,
)


MIT = """MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy.
"""


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _checkout(tmp_path, *, mode="valid"):
    root = tmp_path / "subgrid"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    (root / "LICENSE").write_text(MIT, encoding="utf-8")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "LICENSE", "README.md")
    _git(root, "commit", "-m", "fixture")
    commit = _git(root, "rev-parse", "HEAD")

    build = root / "build"
    build.mkdir()
    executable = build / "subgrid"
    if mode == "valid":
        body = """#!/bin/sh
OUT=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    OUT="$1"
  fi
  shift
done
cat > "$OUT" <<'EOF'
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
f 1 2 3
f 1 3 4
EOF
echo "non-even tets: 0"
"""
    elif mode == "missing":
        body = """#!/bin/sh
echo "non-even tets: 0"
exit 0
"""
    elif mode == "nonzero":
        body = """#!/bin/sh
OUT=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    OUT="$1"
  fi
  shift
done
cat > "$OUT" <<'EOF'
v 0 0 0
v 1 0 0
v 1 1 0
f 1 2 3
EOF
echo "non-even tets: 2"
exit 7
"""
    else:
        raise AssertionError(mode)
    executable.write_text(body, encoding="utf-8")
    executable.chmod(0o755)
    return root, commit


def _input(tmp_path):
    path = tmp_path / "hits.npz"
    np.savez(
        path,
        vertices=np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        ),
        tets=np.asarray([[0, 1, 2, 3]], dtype=np.int32),
        edges=np.asarray([[0, 1], [0, 2]], dtype=np.int32),
        isect_offsets=np.asarray([0, 1, 2], dtype=np.int32),
        isect_ts=np.asarray([0.25, 0.75], dtype=np.float64),
    )
    return path


def test_explicit_npz_contract_is_validated_before_launch(tmp_path):
    path = _input(tmp_path)
    evidence = validate_explicit_npz(path)
    assert evidence["vertices"] == 4
    assert evidence["tets"] == 1
    assert evidence["edges_with_intersections"] == 2
    assert evidence["intersections"] == 2
    assert evidence["normals_present"] is False

    bad = tmp_path / "bad.npz"
    np.savez(
        bad,
        vertices=np.zeros((4, 3), dtype=np.float64),
        tets=np.asarray([[0, 1, 2, 3]], dtype=np.int32),
        edges=np.asarray([[1, 0]], dtype=np.int32),
        isect_offsets=np.asarray([0, 1], dtype=np.int32),
        isect_ts=np.asarray([0.5], dtype=np.float64),
    )
    with pytest.raises(SubgridRunError, match="i < j"):
        validate_explicit_npz(bad)


def test_explicit_npz_rejects_unsorted_intersections(tmp_path):
    path = tmp_path / "unsorted.npz"
    np.savez(
        path,
        vertices=np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        ),
        tets=np.asarray([[0, 1, 2, 3]], dtype=np.int32),
        edges=np.asarray([[0, 1]], dtype=np.int32),
        isect_offsets=np.asarray([0, 2], dtype=np.int32),
        isect_ts=np.asarray([0.8, 0.2], dtype=np.float64),
    )
    with pytest.raises(SubgridRunError, match="not sorted"):
        validate_explicit_npz(path)


def test_verify_checkout_binds_clean_commit_binary_and_license(tmp_path):
    root, commit = _checkout(tmp_path)
    evidence = verify_checkout(root, expected_commit=commit)

    assert evidence["commit"] == commit
    assert evidence["license"] == "MIT"
    assert evidence["clean"] is True
    assert len(evidence["executable_sha256"]) == 64
    assert len(evidence["license_sha256"]) == 64


def test_verify_checkout_rejects_wrong_commit_and_dirty_tree(tmp_path):
    root, commit = _checkout(tmp_path)
    with pytest.raises(SubgridRunError, match="HEAD mismatch"):
        verify_checkout(root, expected_commit="0" * 40)

    (root / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(SubgridRunError, match="dirty"):
        verify_checkout(root, expected_commit=commit)


def test_valid_candidate_is_ink_blind_hash_bound_and_audited(tmp_path):
    root, commit = _checkout(tmp_path)
    input_npz = _input(tmp_path)
    output = tmp_path / "candidate.obj"
    report = run_candidate(
        checkout=root,
        expected_commit=commit,
        input_npz=input_npz,
        output_obj=output,
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["proof_gate_pass"] is True
    assert report["ink_blind"] is True
    assert report["experiment_role"] == "geometry_candidate_only"
    assert report["input"]["sha256"]
    assert report["output"]["sha256"]
    assert report["output"]["audit"]["mesh"]["triangles"] == 2
    assert report["output"]["audit"]["mesh"]["surface_area"] == pytest.approx(1.0)
    assert report["non_even_tets"]["value"] == 0
    assert all(gate["passed"] for gate in report["gates"])


def test_exit_zero_without_obj_fails_postcondition(tmp_path):
    root, commit = _checkout(tmp_path, mode="missing")
    report = run_candidate(
        checkout=root,
        expected_commit=commit,
        input_npz=_input(tmp_path),
        output_obj=tmp_path / "candidate.obj",
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["process"]["return_code"] == 0
    assert report["process"]["exit_zero_but_postcondition_failed"] is True
    assert report["proof_gate_pass"] is False


def test_nonzero_exit_cannot_be_rescued_by_valid_obj(tmp_path):
    root, commit = _checkout(tmp_path, mode="nonzero")
    report = run_candidate(
        checkout=root,
        expected_commit=commit,
        input_npz=_input(tmp_path),
        output_obj=tmp_path / "candidate.obj",
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
    )

    assert report["process"]["return_code"] == 7
    assert report["output"]["audit"]["status"] != "fail"
    assert report["non_even_tets"]["value"] == 2
    assert report["proof_gate_pass"] is False


def test_stale_output_is_rejected_before_launch(tmp_path):
    root, commit = _checkout(tmp_path)
    output = tmp_path / "candidate.obj"
    output.write_text("stale\n", encoding="utf-8")

    with pytest.raises(SubgridRunError, match="already exists"):
        run_candidate(
            checkout=root,
            expected_commit=commit,
            input_npz=_input(tmp_path),
            output_obj=output,
            stdout_log=tmp_path / "stdout.log",
            stderr_log=tmp_path / "stderr.log",
        )

    assert output.read_text(encoding="utf-8") == "stale\n"
    assert not (tmp_path / "stdout.log").exists()


def test_input_must_be_frozen_npz(tmp_path):
    root, commit = _checkout(tmp_path)
    bad = tmp_path / "hits.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(SubgridRunError, match="\.npz"):
        run_candidate(
            checkout=root,
            expected_commit=commit,
            input_npz=bad,
            output_obj=tmp_path / "candidate.obj",
            stdout_log=tmp_path / "stdout.log",
            stderr_log=tmp_path / "stderr.log",
        )
