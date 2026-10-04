from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scrollq import submission_dry_run as dry


def _kwargs(tmp_path: Path) -> dict:
    return {
        "manifest_path": tmp_path / "provenance.json",
        "root_dir": tmp_path,
        "methodology_path": "METHODOLOGY.md",
        "system_requirements_path": "SYSTEM_REQUIREMENTS.md",
        "human_input_log_path": "human-input.json",
        "vc3d_workflow_path": "VC3D_WORKFLOW.md",
        "false_positive_mitigation_path": "FALSE_POSITIVES.md",
        "legibility_ledger_path": "legibility.json",
        "docker_run_command": (
            "docker run --rm "
            "ghcr.io/svyable/scrollq@sha256:" + "a" * 64
        ),
    }


def _fake_result(archive: Path, payload: bytes) -> dict:
    archive.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "archive": str(archive),
        "archive_sha256": digest,
        "manifest_sha256": "b" * 64,
        "graph_sha256": "c" * 64,
        "file_count": 17,
    }


def test_dry_run_requires_two_identical_verified_builds(tmp_path, monkeypatch):
    calls = []

    def fake_build(*, out_path, **kwargs):
        archive = Path(out_path)
        calls.append((archive.name, kwargs))
        return _fake_result(archive, b"deterministic-package")

    def fake_verify(path):
        payload = Path(path).read_bytes()
        return {
            "valid": True,
            "archive_sha256": hashlib.sha256(payload).hexdigest(),
            "errors": [],
        }

    monkeypatch.setattr(dry, "build_package", fake_build)
    monkeypatch.setattr(dry, "verify_package", fake_verify)

    report = dry.run_dry_run(**_kwargs(tmp_path))

    assert report["passed"] is True
    assert report["failure_stage"] is None
    assert report["deterministic_rebuild"]["passed"] is True
    assert len(report["builds"]) == 2
    assert all(row["verified"] is True for row in report["builds"])
    assert calls[0][1]["docker_run_command"] == calls[1][1]["docker_run_command"]


def test_dry_run_fails_on_nondeterministic_archive_bytes(tmp_path, monkeypatch):
    counter = {"value": 0}

    def fake_build(*, out_path, **kwargs):
        counter["value"] += 1
        payload = f"package-{counter['value']}".encode("ascii")
        return _fake_result(Path(out_path), payload)

    monkeypatch.setattr(dry, "build_package", fake_build)
    monkeypatch.setattr(
        dry,
        "verify_package",
        lambda path: {
            "valid": True,
            "archive_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "errors": [],
        },
    )

    report = dry.run_dry_run(**_kwargs(tmp_path))

    assert report["passed"] is False
    assert report["failure_stage"] == "deterministic-rebuild"
    assert report["deterministic_rebuild"]["passed"] is False
    assert "different archive SHA-256" in report["errors"][0]


def test_dry_run_preserves_package_failure_as_receipt(tmp_path, monkeypatch):
    def fake_build(**kwargs):
        raise dry.PackageError("GP_TEST_BLOCKER")

    monkeypatch.setattr(dry, "build_package", fake_build)

    report = dry.run_dry_run(**_kwargs(tmp_path))

    assert report["passed"] is False
    assert report["failure_stage"] == "build-1"
    assert report["errors"] == ["GP_TEST_BLOCKER"]
    assert report["builds"] == []


def test_dry_run_fails_when_production_verifier_fails(tmp_path, monkeypatch):
    def fake_build(*, out_path, **kwargs):
        return _fake_result(Path(out_path), b"package")

    monkeypatch.setattr(dry, "build_package", fake_build)
    monkeypatch.setattr(
        dry,
        "verify_package",
        lambda path: {
            "valid": False,
            "archive_sha256": "d" * 64,
            "errors": ["tampered member"],
        },
    )

    report = dry.run_dry_run(**_kwargs(tmp_path))

    assert report["passed"] is False
    assert report["failure_stage"] == "verify-1"
    assert report["builds"][0]["verified"] is False
    assert report["errors"] == ["tampered member"]


def test_write_report_is_create_only(tmp_path):
    out = tmp_path / "dry-run.json"
    report = {"passed": True}
    dry._write_report(out, report)
    assert json.loads(out.read_text(encoding="utf-8")) == report

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        dry._write_report(out, report)
