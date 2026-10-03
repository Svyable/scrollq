import copy

from scrollq.evidence_ledger import validate_evidence_ledger


def _entry(ident, claim, *, status="pass", mesh_ids=None):
    return {
        "id": ident,
        "claim": claim,
        "status": status,
        "tool": "independent-tool",
        "artifact_url": "https://example.org/evidence/report.json",
        "sha256": "a" * 64,
        "scope": {"mesh_ids": list(mesh_ids or [])},
        "producer": {
            "repository": "https://github.com/example/independent-tool",
            "commit": "b" * 40,
            "command": "independent-tool --json report.json",
        },
    }


def _ledger():
    return {
        "schema_version": 1,
        "diagnostic": "grand-prize-evidence-ledger",
        "volume_id": "eligible-volume",
        "entries": [
            _entry("flat", "flattening-isometry", mesh_ids=["mesh:01", "mesh:02"]),
            _entry("cross", "mesh-self-intersection", mesh_ids=["mesh:01", "mesh:02"]),
            _entry("hand", "render-handedness", mesh_ids=["mesh:01", "mesh:02"]),
            _entry("spiral", "spiral-held-out"),
        ],
    }


def test_complete_required_independent_evidence_passes():
    report = validate_evidence_ledger(
        _ledger(),
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "pass"
    assert report["ready"] is True
    assert report["error_count"] == 0
    assert {item["status"] for item in report["required_claims"]} == {"pass"}


def test_missing_mesh_coverage_stays_partial_not_clean():
    ledger = _ledger()
    ledger["entries"][0]["scope"]["mesh_ids"] = ["mesh:01"]

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "partial"
    assert report["ready"] is False
    claim = next(
        item for item in report["required_claims"]
        if item["claim"] == "flattening-isometry"
    )
    assert claim["missing_mesh_ids"] == ["mesh:02"]


def test_explicit_failure_blocks_even_when_other_evidence_passes():
    ledger = _ledger()
    ledger["entries"][2]["status"] = "fail"

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    claim = next(
        item for item in report["required_claims"]
        if item["claim"] == "render-handedness"
    )
    assert claim["failed_evidence_ids"] == ["hand"]


def test_wrong_exact_volume_fails_closed():
    report = validate_evidence_ledger(
        _ledger(),
        expected_volume_id="different-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_VOLUME_MISMATCH" in {
        item["code"] for item in report["errors"]
    }


def test_unknown_mesh_reference_is_a_structural_error():
    ledger = _ledger()
    ledger["entries"][0]["scope"]["mesh_ids"].append("mesh:not-submitted")

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_SCOPE_UNKNOWN_MESH" in {
        item["code"] for item in report["errors"]
    }


def test_duplicate_evidence_ids_fail():
    ledger = _ledger()
    duplicate = copy.deepcopy(ledger["entries"][0])
    ledger["entries"].append(duplicate)

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_DUPLICATE_ID" in {
        item["code"] for item in report["errors"]
    }
