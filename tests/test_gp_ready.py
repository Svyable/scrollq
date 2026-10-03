from scrollq.gp_ready import evaluate_readiness


def _provenance(*, eligible=True):
    return {
        "eligible": eligible,
        "graph_sha256": "a" * 64,
        "error_count": 0 if eligible else 1,
        "errors": [] if eligible else [
            {
                "code": "GP_TEST_BLOCKER",
                "path": "submission",
                "message": "synthetic provenance failure",
            }
        ],
    }


def _evidence(status):
    claim_status = "pass" if status == "pass" else (
        "fail" if status == "fail" else "partial"
    )
    return {
        "status": status,
        "graph_sha256": "b" * 64,
        "error_count": 0,
        "errors": [],
        "required_claims": [
            {
                "claim": "flattening-isometry",
                "status": claim_status,
                "reason": "synthetic evidence state",
                "missing_mesh_ids": ["mesh:02"] if claim_status == "partial" else [],
            }
        ],
    }


def test_ready_requires_provenance_and_independent_evidence():
    report = evaluate_readiness(_provenance(), _evidence("pass"))
    assert report["status"] == "ready"
    assert report["ready"] is True


def test_missing_independent_evidence_is_unknown_not_pass():
    report = evaluate_readiness(_provenance(), _evidence("partial"))
    assert report["status"] == "unknown"
    assert report["ready"] is False
    assert report["unknowns"][0]["claim"] == "flattening-isometry"


def test_explicit_independent_failure_blocks():
    report = evaluate_readiness(_provenance(), _evidence("fail"))
    assert report["status"] == "blocked"
    assert report["ready"] is False
    assert any(item["code"] == "EVIDENCE_CLAIM_FAIL" for item in report["blockers"])


def test_provenance_failure_blocks_even_if_external_evidence_passes():
    report = evaluate_readiness(_provenance(eligible=False), _evidence("pass"))
    assert report["status"] == "blocked"
    assert any(item["code"] == "GP_TEST_BLOCKER" for item in report["blockers"])
