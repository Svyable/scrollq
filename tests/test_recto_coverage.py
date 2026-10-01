from scrollq.recto_coverage import audit_recto_coverage


def _manifest():
    return {
        "schema_version": 1,
        "volume_root": "volume-A",
        "generated_by": {
            "command": "python -m pipeline.measure_recto --volume volume-A",
            "code_commit": "a" * 40,
        },
        "reference": {
            "surface_area": 100.0,
            "area_unit": "mm^2",
            "method": "Union-area inventory from the frozen reference recto segmentation",
            "artifact_url": "https://example.org/recto/reference.json",
            "sha256": "b" * 64,
        },
        "components": [
            {
                "id": "main",
                "kind": "main-sheet",
                "area": 80.0,
                "unrolled": True,
                "excluded": False,
                "mesh_ids": ["mesh:column-01"],
            },
            {
                "id": "detached-01",
                "kind": "detached-patch",
                "area": 15.0,
                "unrolled": True,
                "excluded": False,
                "mesh_ids": ["mesh:detached-01"],
            },
            {
                "id": "outer-01",
                "kind": "disconnected-outer-patch",
                "area": 5.0,
                "unrolled": False,
                "excluded": True,
                "mesh_ids": [],
                "exclusion_reason": "Disconnected outer patch below the permitted total-area limit.",
            },
        ],
    }


def _errors(result):
    return "\n".join(result["errors"])


def test_complete_declared_recto_with_small_outer_exclusion_passes():
    result = audit_recto_coverage(_manifest(), expected_volume_root="volume-A")

    assert result["status"] == "pass"
    assert result["coverage"]["declared_component_area"] == 100.0
    assert result["coverage"]["unrolled_area"] == 95.0
    assert result["coverage"]["excluded_disconnected_outer_patch_fraction"] == 0.05
    assert result["coverage"]["in_scope_unrolled_fraction"] == 1.0
    assert result["mesh_ids"] == ["mesh:column-01", "mesh:detached-01"]


def test_exactly_ten_percent_outer_exclusion_fails_strict_rule():
    manifest = _manifest()
    manifest["components"][0]["area"] = 75.0
    manifest["components"][2]["area"] = 10.0

    result = audit_recto_coverage(manifest)

    assert result["status"] == "fail"
    assert "less than 10%" in _errors(result)


def test_detached_patch_cannot_be_left_unrolled():
    manifest = _manifest()
    manifest["components"][1]["unrolled"] = False

    result = audit_recto_coverage(manifest)

    assert result["status"] == "fail"
    assert "kind='detached-patch' must be unrolled" in _errors(result)
    assert "not 100% unrolled" in _errors(result)


def test_only_disconnected_outer_patch_may_be_excluded():
    manifest = _manifest()
    manifest["components"][1]["unrolled"] = False
    manifest["components"][1]["excluded"] = True
    manifest["components"][1]["exclusion_reason"] = "skip it"

    result = audit_recto_coverage(manifest)

    assert result["status"] == "fail"
    assert "may be excluded only" in _errors(result)


def test_reused_mesh_id_fails_double_counting_guard():
    manifest = _manifest()
    manifest["components"][1]["mesh_ids"] = ["mesh:column-01"]

    result = audit_recto_coverage(manifest)

    assert result["status"] == "fail"
    assert "assigned to more than one recto component" in _errors(result)


def test_reference_area_must_balance_declared_components():
    manifest = _manifest()
    manifest["reference"]["surface_area"] = 101.0

    result = audit_recto_coverage(manifest)

    assert result["status"] == "fail"
    assert "does not match reference.surface_area" in _errors(result)


def test_volume_binding_fails_closed():
    result = audit_recto_coverage(_manifest(), expected_volume_root="volume-B")

    assert result["status"] == "fail"
    assert "does not match the requested exact CT root" in _errors(result)


def test_unrolled_component_requires_mesh_evidence():
    manifest = _manifest()
    manifest["components"][0]["mesh_ids"] = []

    result = audit_recto_coverage(manifest)

    assert result["status"] == "fail"
    assert "must name submitted mesh evidence" in _errors(result)
