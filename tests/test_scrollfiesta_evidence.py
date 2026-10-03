from copy import deepcopy

from scrollq.scrollfiesta_evidence import normalize_scrollfiesta_release


def _report():
    return {
        "schema": "scrollfiesta-public-release-check-v1",
        "date": "2026-09-30",
        "scroll": "PHerc0139",
        "region": "4x5x5",
        "mesh_pile": "head/mesh/dump",
        "cube_count": 100,
        "chunk_size": 128,
        "bounds_zyx_half_open": [[4352, 4864], [3072, 3712], [2560, 3200]],
        "configuration": {
            "path": "configs/default.json",
            "sha256_lf": "a" * 64,
            "axis_path": "configs/axis.csv",
            "axis_sha256_lf": "b" * 64,
            "text_hash_rule": "SHA-256 after CRLF-to-LF normalization",
        },
        "audit": {
            "audit_complete": True,
            "geometry_qualified": False,
            "whole_scroll_qualified": False,
            "source_preserved": True,
            "source_faces": 916995,
            "accounted_source_faces": 916995,
            "represented_source_faces": 646199,
            "source_area": 8147925.8,
            "represented_area": 3860933.9,
            "coverage": 0.4738548223,
            "placed_charts": 356,
            "unplaced_charts": 406,
            "excluded_charts": 21,
            "invalid_faces": 0,
            "strict_bad_faces": 0,
            "sigma_min": 0.772681,
            "sigma_max": 1.25,
            "overlapping_triangle_pairs": 171,
            "self_overlapping_pairs": 0,
            "obligations": 1507,
            "passing_seams": 126,
            "unresolved_seams": 1381,
            "source_region_coherence": 0.999999999999993,
            "qualification_contract": (
                "85% original area, continuity within recorded source regions, "
                "all represented required seams"
            ),
            "minimum_coverage": 0.85,
            "minimum_source_region_coherence": 0.99,
            "source_decoded_sha256": "c" * 64,
            "field_sha256": "d" * 64,
            "obligations_sha256": "e" * 64,
        },
        "preview": {
            "source": "stage6_repaired.vmesh",
            "vmesh_sha256": "f" * 64,
            "raw_source": "PHerc0139-4x5x5/cubes_RAW",
            "normal_range_vox": 4,
            "normal_samples": 9,
            "coverage": {
                "complete": False,
                "complete_over_painted_faces": True,
                "expected_chunks": 216,
                "loaded_chunks": 100,
                "missing_chunks": 116,
                "faces_unpainted_missing_raw": 18456,
            },
            "grid": {"shape_hw": [642, 11170]},
            "full_png_sha256": "1" * 64,
            "figure_sha256": "2" * 64,
        },
        "validation": {
            "cmake_release_build": "pass",
            "native_quadribbon_build": "pass",
            "install_check": "pass",
            "ctest_passed": 16,
            "ctest_failed": 0,
        },
        "boundary": (
            "Partial, geometry-unqualified reference check; "
            "not a reproduction of the August atlas or quadribbon exhibits."
        ),
    }


def test_public_unqualified_release_stays_unqualified():
    evidence = normalize_scrollfiesta_release(
        _report(), expected_scroll="PHerc0139", expected_region="4x5x5"
    )

    assert evidence["status"] == "measured"
    q = evidence["claims"]["producer_qualification"]
    assert q["geometry_qualified"] is False
    assert q["whole_scroll_qualified"] is False
    assert evidence["claims"]["geometry"]["coverage"] == 0.4738548223
    assert evidence["claims"]["geometry"]["overlapping_triangle_pairs"] == 171
    assert evidence["claims"]["ct_texture"]["status"] == "partial"
    assert evidence["grand_prize_scope"]["status"] == "not-established"

    codes = {row["code"] for row in evidence["findings"]}
    assert "SCROLLFIESTA_GEOMETRY_UNQUALIFIED" in codes
    assert "SCROLLFIESTA_COVERAGE_BELOW_PRODUCER_GATE" in codes
    assert "SCROLLFIESTA_OVERLAPS_REMAIN" in codes
    assert "SCROLLFIESTA_CT_BAKE_INCOMPLETE" in codes


def test_scope_mismatch_excludes_measurements():
    evidence = normalize_scrollfiesta_release(
        _report(), expected_scroll="PHerc1447"
    )

    assert evidence["status"] == "excluded"
    assert evidence["claims"] == {}
    assert evidence["findings"][0]["code"] == "SCROLLFIESTA_SCOPE_MISMATCH"


def test_unknown_schema_fails_closed():
    report = _report()
    report["schema"] = "scrollfiesta-release-v99"

    evidence = normalize_scrollfiesta_release(report)

    assert evidence["status"] == "excluded"
    assert evidence["claims"] == {}
    assert evidence["findings"][0]["code"] == "SCROLLFIESTA_SCHEMA_UNSUPPORTED"


def test_incomplete_audit_is_partial():
    report = _report()
    report["audit"]["audit_complete"] = False

    evidence = normalize_scrollfiesta_release(report)

    assert evidence["status"] == "partial"
    assert any(
        row["code"] == "SCROLLFIESTA_AUDIT_INCOMPLETE"
        for row in evidence["findings"]
    )


def test_local_qualified_geometry_still_does_not_become_grand_prize_proof():
    report = deepcopy(_report())
    report["audit"]["geometry_qualified"] = True
    report["audit"]["coverage"] = 0.90
    report["audit"]["overlapping_triangle_pairs"] = 0

    evidence = normalize_scrollfiesta_release(report)

    assert evidence["claims"]["producer_qualification"]["geometry_qualified"] is True
    assert evidence["grand_prize_scope"]["status"] == "not-established"
    reasons = " ".join(evidence["grand_prize_scope"]["reasons"])
    assert "100% recto coverage" in reasons
    assert "70% per-column" in reasons
