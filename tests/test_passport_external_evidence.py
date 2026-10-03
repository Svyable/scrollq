from scrollq.passport import build_passport


VOLUME_ROOT = (
    "community-uploads/forrest/volcomp/PHercTEST/volumes/"
    "20250728140407-9.362um-1.2m-113keV-masked.zarr"
)


def _volume():
    return {
        "root": VOLUME_ROOT,
        "ok": True,
        "score": 70.0,
        "metrics": {"chunks_decoded": 4},
        "components": {},
        "sampling": {"requested": 4, "decoded": 4, "complete": True},
    }


def _mesh():
    return {
        "diagnostic": "tifxyz-mesh-audit",
        "volume_root": VOLUME_ROOT,
        "status": "pass",
        "tifxyz_path": "/tmp/mesh",
        "grid": {
            "valid_vertices": 100,
            "enclosed_invalid_components": 0,
            "valid_vertex_components": {"components": 1},
        },
        "bbox": {},
        "spacing": {},
        "quads": {"valid_quads": 80},
        "ct_preflight": {},
        "self_intersection": {},
        "findings": [],
        "error_count": 0,
        "warning_count": 0,
    }


def _dossier(*, volume_root=VOLUME_ROOT, level="coordinate-exact", included=True):
    return {
        "schema_version": 1,
        "diagnostic": "external-mesh-evidence-dossier",
        "status": "bound" if included else "partial",
        "surface": {
            "volume_root": volume_root,
            "segment": "seg",
        },
        "binding": {
            "level": level,
            "coordinates_match": level in {"coordinate-exact", "semantic-exact"},
        },
        "external_source": {
            "tool": "windcheck",
            "repository": "https://github.com/joe-carr-data/windcheck",
            "commit": "deadbeef",
        },
        "external_measurement": {
            "status": "included" if included else "excluded",
            "subject": "same-published-original" if included else "derived-base",
            "input_transverse_total": 3333 if included else None,
        },
        "claims": {
            "nonlocal_transverse_self_intersection": {
                "status": "measured" if included else "unknown",
                "input_transverse_total": 3333 if included else None,
            }
        },
        "limitations": ["external evidence remains scope-limited"],
    }


def test_passport_carries_coordinate_exact_external_measurement():
    passport = build_passport(
        _volume(),
        mesh_audit=_mesh(),
        external_mesh_evidence=_dossier(),
    )

    external = passport["stages"]["mesh"]["external_evidence"]
    assert external["status"] == "measured"
    assert external["binding"]["level"] == "coordinate-exact"
    assert external["measurement"]["input_transverse_total"] == 3333
    assert any(
        action["open_problem"] == "mesh-connectivity"
        and action["priority"] == "high"
        and "3333 transverse contacts" in action["action"]
        for action in passport["next_actions"]
    )


def test_passport_rejects_external_dossier_for_another_volume():
    passport = build_passport(
        _volume(),
        mesh_audit=_mesh(),
        external_mesh_evidence=_dossier(volume_root="different-volume"),
    )

    external = passport["stages"]["mesh"]["external_evidence"]
    assert external["status"] == "excluded"
    assert "different volume root" in external["reason"]
    assert not any(
        "independently content-bound nonlocal census" in action["action"]
        for action in passport["next_actions"]
    )


def test_passport_does_not_upgrade_path_only_external_evidence():
    passport = build_passport(
        _volume(),
        mesh_audit=_mesh(),
        external_mesh_evidence=_dossier(level="path-only"),
    )

    external = passport["stages"]["mesh"]["external_evidence"]
    assert external["status"] == "excluded"
    assert external["binding"]["level"] == "path-only"
    assert "not content-bound strongly enough" in external["reason"]


def test_passport_keeps_derived_base_measurement_partial():
    passport = build_passport(
        _volume(),
        mesh_audit=_mesh(),
        external_mesh_evidence=_dossier(included=False),
    )

    external = passport["stages"]["mesh"]["external_evidence"]
    assert external["status"] == "partial"
    assert external["measurement"]["subject"] == "derived-base"
    assert not any(
        "independently content-bound nonlocal census" in action["action"]
        for action in passport["next_actions"]
    )
