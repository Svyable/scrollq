import json

from scrollq import target_gate


def _artifact(volume_id: str, name: str = "evidence") -> dict:
    return {
        "kind": name,
        "uri": f"https://example.invalid/evidence/{name}.json",
        "sha256": "a" * 64,
        "volume_id": volume_id,
        "claim": f"{name} evidence for exact eligible volume",
    }


def _document(
    *,
    scroll: str = "PHerc0800",
    volume_id: str = "20250521135224",
    root_volume_id: str | None = None,
) -> dict:
    root_volume_id = root_volume_id or volume_id
    prerequisites = {
        stage: {
            "state": "pass",
            "rationale": f"{stage} cleared",
            "artifacts": [_artifact(volume_id, stage)],
        }
        for stage in target_gate.REQUIRED_STAGES
    }
    return {
        "schema_version": 1,
        "as_of": "2026-10-03",
        "candidate": {
            "scroll": scroll,
            "volume_id": volume_id,
            "volume_root": (
                f"community-uploads/forrest/volcomp/{scroll}/volumes/"
                f"{root_volume_id}-masked.zarr"
            ),
        },
        "prerequisites": prerequisites,
    }


def test_complete_exact_volume_gate_is_ready_without_ranking():
    report = target_gate.evaluate_target_gate(_document())

    assert report["status"] == "ready-to-freeze"
    assert report["blocking_checks"] == []
    assert report["unknown_checks"] == []
    assert report["ranking"] is None
    assert len(report["manifest_sha256"]) == 64
    assert len(report["manifest_target_sha256"]) == 64
    assert report["checks"][0]["id"] == "exact_volume_identity"
    assert report["checks"][0]["state"] == "pass"


def test_same_scroll_wrong_volume_is_blocked():
    document = _document(
        scroll="PHerc1203",
        volume_id="20260319130212",
    )
    report = target_gate.evaluate_target_gate(document)

    assert report["status"] == "blocked"
    assert "exact_volume_identity" in report["blocking_checks"]
    identity = report["checks"][0]
    assert identity["eligible_volume_id"] == "20250820131727"
    assert any("does not equal eligible" in reason for reason in identity["reasons"])


def test_missing_prerequisite_stays_provisional():
    document = _document()
    del document["prerequisites"]["ink_validation"]

    report = target_gate.evaluate_target_gate(document)

    assert report["status"] == "provisional"
    assert report["blocking_checks"] == []
    assert report["unknown_checks"] == ["ink_validation"]


def test_declared_pass_without_artifact_fails_closed():
    document = _document()
    document["prerequisites"]["heldout_geometry"]["artifacts"] = []

    report = target_gate.evaluate_target_gate(document)

    assert report["status"] == "blocked"
    assert "heldout_geometry" in report["blocking_checks"]
    check = next(row for row in report["checks"] if row["id"] == "heldout_geometry")
    assert "pass requires at least one hash-pinned evidence artifact" in check["reasons"]


def test_cross_volume_artifact_fails_closed():
    document = _document()
    document["prerequisites"]["vc3d_handoff"]["artifacts"][0]["volume_id"] = (
        "20250821151723"
    )

    report = target_gate.evaluate_target_gate(document)

    assert report["status"] == "blocked"
    check = next(row for row in report["checks"] if row["id"] == "vc3d_handoff")
    assert any("must equal candidate volume_id" in reason for reason in check["reasons"])


def test_explicit_failed_control_remains_blocking():
    document = _document()
    document["prerequisites"]["ink_validation"] = {
        "state": "fail",
        "rationale": "normal-offset falsification control did not localize to the surface",
        "artifacts": [_artifact("20250521135224", "ink-negative-control")],
    }

    report = target_gate.evaluate_target_gate(document)

    assert report["status"] == "blocked"
    check = next(row for row in report["checks"] if row["id"] == "ink_validation")
    assert check["declared_state"] == "fail"
    assert check["state"] == "fail"


def test_cli_writes_report_and_uses_gate_exit_code(tmp_path, capsys):
    input_path = tmp_path / "target.json"
    out = tmp_path / "gate.json"
    input_path.write_text(json.dumps(_document()), encoding="utf-8")

    assert target_gate.main(["--in", str(input_path), "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == "ready-to-freeze"

    assert target_gate.main(["--in", str(input_path), "--out", str(out)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().out


def test_manifest_binding_changes_when_manifest_changes():
    document = _document()
    baseline = target_gate.evaluate_target_gate(document)
    changed = json.loads(json.dumps(target_gate.DEFAULT_MANIFEST))
    changed["as_of"] = "2099-01-01"
    rebound = target_gate.evaluate_target_gate(document, manifest=changed)

    assert baseline["manifest_sha256"] != rebound["manifest_sha256"]
    assert baseline["manifest_target_sha256"] == rebound["manifest_target_sha256"]


def test_repository_artifact_hash_is_verified(tmp_path):
    evidence = tmp_path / "artifacts" / "evidence.json"
    evidence.parent.mkdir()
    evidence.write_bytes(b"frozen evidence\n")

    document = _document()
    artifact = document["prerequisites"]["heldout_geometry"]["artifacts"][0]
    artifact["uri"] = "artifacts/evidence.json"
    import hashlib
    artifact["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()

    report = target_gate.evaluate_target_gate(document, repo_root=tmp_path)

    assert report["status"] == "ready-to-freeze"


def test_repository_artifact_hash_mismatch_fails_closed(tmp_path):
    evidence = tmp_path / "artifacts" / "evidence.json"
    evidence.parent.mkdir()
    evidence.write_bytes(b"actual evidence\n")

    document = _document()
    artifact = document["prerequisites"]["heldout_geometry"]["artifacts"][0]
    artifact["uri"] = "artifacts/evidence.json"
    artifact["sha256"] = "0" * 64

    report = target_gate.evaluate_target_gate(document, repo_root=tmp_path)

    assert report["status"] == "blocked"
    assert "heldout_geometry" in report["blocking_checks"]
    check = next(row for row in report["checks"] if row["id"] == "heldout_geometry")
    assert any("does not match repository artifact bytes" in reason for reason in check["reasons"])


def test_missing_repository_artifact_fails_closed(tmp_path):
    document = _document()
    artifact = document["prerequisites"]["vc3d_handoff"]["artifacts"][0]
    artifact["uri"] = "artifacts/missing.json"

    report = target_gate.evaluate_target_gate(document, repo_root=tmp_path)

    assert report["status"] == "blocked"
    assert "vc3d_handoff" in report["blocking_checks"]
    check = next(row for row in report["checks"] if row["id"] == "vc3d_handoff")
    assert any("repository artifact is unreadable" in reason for reason in check["reasons"])
