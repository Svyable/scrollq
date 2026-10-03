import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "2026-10-03-flattening-tier0"
MANIFEST = ARTIFACT / "manifest.json"


def test_flattening_tier0_manifest_is_explicitly_non_promoting_and_licensed():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert data["diagnostic"] == "flattening-tier0-fixtures"
    assert data["promotion_eligible"] is False
    assert data["dataset_license"]["spdx"] == "CC-BY-NC-4.0"
    assert data["selection_freeze"]["candidate_results_observed"] is False
    assert "cannot PROMOTE" in data["selection_freeze"]["explicit_nonpromotion"]

    cases = data["cases"]
    assert len(cases) == 3
    assert {case["role"] for case in cases} == {
        "ordinary-curved-control",
        "tear-hole-stress",
        "high-distortion-stress",
    }


def test_flattening_tier0_sources_are_hash_pinned_public_objs_only():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    ids = set()
    for case in data["cases"]:
        assert case["id"] not in ids
        ids.add(case["id"])

        assert case["source_key"].endswith("_original.obj")
        assert "/segments/" in case["source_key"]
        assert len(case["sha256"]) == 64
        int(case["sha256"], 16)
        assert case["bytes"] > 0
        assert case["source_audit"].startswith(
            "artifacts/2026-10-01-corpus-mesh-audit/obj-reports/"
        )
        assert (ROOT / case["source_audit"]).is_file()

        expected = case["expected_audit"]
        assert expected["triangles"] > 0
        assert expected["components"] >= 1
        assert expected["boundary_loops"] >= 1
        assert expected["holes"] >= 0
        assert expected["uv_flips"] == 0
        assert expected["p95_symmetric_stretch"] >= 1.0


def test_flattening_tier0_roles_have_intended_stress_properties():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_role = {case["role"]: case for case in data["cases"]}

    ordinary = by_role["ordinary-curved-control"]["expected_audit"]
    holes = by_role["tear-hole-stress"]["expected_audit"]
    distortion = by_role["high-distortion-stress"]["expected_audit"]

    assert ordinary["components"] == 1
    assert ordinary["boundary_loops"] == 1

    assert holes["holes"] >= 10
    assert holes["boundary_loops"] > 1

    assert distortion["p95_symmetric_stretch"] > 2.0


def test_flattening_tier0_verifier_keeps_claim_boundary():
    path = ARTIFACT / "verify.py"
    text = path.read_text(encoding="utf-8")
    compile(text, str(path), "exec")

    assert '"promotion_eligible": False' in text
    assert "Tier-1 evidence remains mandatory" in text
    assert "downloaded Vesuvius Challenge mesh bytes" in text
