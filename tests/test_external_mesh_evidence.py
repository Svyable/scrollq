from copy import deepcopy

from scrollq.external_mesh_evidence import bind_windcheck_release


VOLUME_ROOT = (
    "community-uploads/forrest/volcomp/PHerc0139/volumes/"
    "20250728140407-9.362um-1.2m-113keV-masked.zarr"
)


def _mesh():
    return {
        "diagnostic": "tifxyz-mesh-audit",
        "volume_root": VOLUME_ROOT,
        "tifxyz_path": "/tmp/seg.tifxyz",
        "status": "partial",
        "provenance": {
            "meta.json": {"sha256": "m" * 64, "bytes": 1},
            "x.tif": {"sha256": "a" * 64, "bytes": 2},
            "y.tif": {"sha256": "b" * 64, "bytes": 3},
            "z.tif": {"sha256": "c" * 64, "bytes": 4},
        },
        "grid": {
            "shape_yx": [10, 12],
            "valid_vertices": 100,
        },
        "findings": [{"kind": "normal-reversal", "severity": "review"}],
    }


def _index(*, base_kind="original"):
    original = {"x": "a" * 64, "y": "b" * 64, "z": "c" * 64, "mask": None}
    input_hashes = dict(original)
    if base_kind != "original":
        input_hashes["x"] = "d" * 64
    return {
        "schema": "release_index/v1",
        "segments": {
            "seg": {
                "segment": "seg",
                "scroll": "PHerc0139",
                "volume": "20250728140407",
                "voxel_um": 9.362,
                "base_kind": base_kind,
                "input_hashes": input_hashes,
                "original_hashes": original,
                "grid_shape": [10, 12],
                "n_valid_vertices": 100,
                "status": "transverse_clean",
                "disposition": "transformed",
                "certificate": "certificate.json",
                "certificate_sha256": "e" * 64,
                "policy_version": "policy-v1",
                "policy_hash": "f" * 16,
                "census": {
                    "input_transverse_total": 3333,
                    "output_transverse_total": 0,
                    "geometry_status": "transverse_clean_certified",
                    "recensus_clean_both_diagonals": True,
                },
                "retention": {"headline_retained_fraction": 0.9975},
                "fragmentation": {"core_gate_pass": True},
            }
        },
    }


def _bind(index=None):
    return bind_windcheck_release(
        _mesh(),
        index or _index(),
        segment="seg",
        scroll="PHerc0139",
        volume_id="20250728140407",
        source_sha256="1" * 64,
        commit="deadbeef",
    )


def test_matching_original_is_coordinate_exact_and_imports_census():
    dossier = _bind()

    assert dossier["status"] == "bound"
    assert dossier["binding"]["level"] == "coordinate-exact"
    assert dossier["binding"]["coordinates_match"] is True
    assert dossier["binding"]["mask_match"] is True
    assert dossier["binding"]["metadata_match"] is None
    assert dossier["binding"]["grid_shape_match"] is True
    assert dossier["binding"]["valid_vertex_count_match"] is True
    assert dossier["external_measurement"]["status"] == "included"
    assert dossier["external_measurement"]["subject"] == "same-published-original"
    assert dossier["external_measurement"]["input_transverse_total"] == 3333
    assert (
        dossier["claims"]["nonlocal_transverse_self_intersection"]
        ["input_transverse_total"]
        == 3333
    )


def test_coordinate_hash_mismatch_excludes_external_measurement():
    index = _index()
    index["segments"]["seg"]["input_hashes"]["z"] = "9" * 64

    dossier = _bind(index)

    assert dossier["status"] == "excluded"
    assert dossier["binding"]["level"] == "mismatch"
    assert dossier["binding"]["coordinates_match"] is False
    assert dossier["external_measurement"]["status"] == "excluded"
    assert dossier["claims"]["nonlocal_transverse_self_intersection"]["status"] == "unknown"


def test_mask_presence_is_part_of_coordinate_identity():
    mesh = _mesh()
    mesh["provenance"]["mask.tif"] = {"sha256": "7" * 64, "bytes": 5}

    dossier = bind_windcheck_release(
        mesh,
        _index(),
        segment="seg",
        scroll="PHerc0139",
        volume_id="20250728140407",
    )

    assert dossier["status"] == "excluded"
    assert dossier["binding"]["level"] == "mismatch"
    assert dossier["binding"]["mask_match"] is False


def test_derived_base_can_bind_original_identity_but_not_import_derived_census():
    dossier = _bind(_index(base_kind="displacement_repaired"))

    assert dossier["status"] == "partial"
    assert dossier["binding"]["level"] == "coordinate-exact"
    assert dossier["binding"]["external_hash_subject"] == "original_hashes"
    assert dossier["binding"]["measurement_subject"] == "derived-base"
    assert dossier["external_measurement"]["status"] == "excluded"
    assert "derived base" in dossier["external_measurement"]["reason"]
    assert dossier["claims"]["nonlocal_transverse_self_intersection"]["status"] == "unknown"


def test_scroll_or_volume_mismatch_fails_closed():
    index = _index()
    index["segments"]["seg"]["volume"] = "other"

    dossier = _bind(index)

    assert dossier["status"] == "excluded"
    assert dossier["binding"]["level"] == "mismatch"
    assert dossier["external_measurement"]["status"] == "excluded"


def test_unsupported_release_schema_is_not_guessed():
    index = _index()
    index["schema"] = "unknown/v9"

    dossier = _bind(index)

    assert dossier["status"] == "excluded"
    assert dossier["binding"]["level"] == "unbound"
    assert "unsupported" in dossier["binding"]["reason"]


def test_local_volume_selector_must_match_declared_volume():
    mesh = deepcopy(_mesh())
    mesh["volume_root"] = mesh["volume_root"].replace("20250728140407", "20250728140000")

    dossier = bind_windcheck_release(
        mesh,
        _index(),
        segment="seg",
        scroll="PHerc0139",
        volume_id="20250728140407",
    )

    assert dossier["status"] == "excluded"
    assert dossier["binding"]["level"] == "mismatch"
