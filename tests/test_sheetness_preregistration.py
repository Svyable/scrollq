import hashlib
import json
from pathlib import Path

import pytest

from scrollq import sheetness_preregistration as pre
from scrollq.sheetness import METHOD


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(surface_id: str):
    return {
        "surface_id": surface_id,
        "source_url": f"https://example.test/{surface_id}.tifxyz",
        "coordinate_sha256": {
            "x.tif": "1" * 64,
            "y.tif": "2" * 64,
            "z.tif": "3" * 64,
        },
        "meta_sha256": "4" * 64,
    }


def _prereg():
    return {
        "schema": pre.SCHEMA,
        "benchmark_schema": pre.BENCHMARK_SCHEMA,
        "experiment_id": "pherc0139-w035-reference-v1",
        "phase": "reference",
        "volume_root": (
            "PHerc0139/volumes/"
            "20250728140407-9.362um-1.2m-113keV-masked.zarr"
        ),
        "ct_url": (
            "https://example.test/PHerc0139/volumes/"
            "20250728140407-9.362um-1.2m-113keV-masked.zarr"
        ),
        "zpa_report_sha256": "a" * 64,
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": "b" * 64,
            "axes": ["z", "y", "x"],
        },
        "cutout_bbox_zyx_half_open": {
            "start": [90, 190, 290],
            "stop": [111, 211, 311],
        },
        "engine": {
            "method": METHOD,
            "sigmas": [0.8, 1.2, 1.8],
            "beta": 0.5,
            "gamma": 0.1,
            "bright_object": True,
            "scale_objectness": False,
            "normalize": True,
            "lower_percentile": 1.0,
            "upper_percentile": 99.0,
            "write_normal": True,
        },
        "decision_rule": {
            "min_score_completeness": 1.0,
            "min_normal_offset_win_fraction": 0.8,
            "min_median_normal_offset_margin": 0.0,
            "min_normal_completeness": 1.0,
            "min_median_abs_cosine": 0.8,
        },
        "selection_rule": {
            "algorithm": "geometry-only-interior-probe-v1",
            "ct_intensity_used": False,
            "sheetness_outputs_used": False,
            "parameters": {
                "interior_margin_grid_cells": 8,
                "wrong_wrap_max_distance_voxels": 32.0,
            },
        },
        "stop_rules": [
            "Publish a valid negative result without retuning this preregistration.",
            "Do not inspect target-scroll sheetness until the reference disposition is frozen.",
        ],
        "groups": [
            {
                "id": "g1",
                "surface": {
                    "global_zyx": [100.0, 200.0, 300.0],
                    "reference_normal_zyx": [1.0, 0.0, 0.0],
                    "source": _source("w035"),
                },
                "controls": [
                    {
                        "id": "g1-minus",
                        "role": "normal-offset",
                        "global_zyx": [98.0, 200.0, 300.0],
                        "derivation": {"sign": -1, "distance_voxels": 2.0},
                    },
                    {
                        "id": "g1-plus",
                        "role": "normal-offset",
                        "global_zyx": [102.0, 200.0, 300.0],
                        "derivation": {"sign": 1, "distance_voxels": 2.0},
                    },
                    {
                        "id": "g1-wrong",
                        "role": "wrong-wrap",
                        "global_zyx": [101.0, 201.0, 301.0],
                        "source": _source("w039"),
                    },
                ],
            }
        ],
    }


def _cutout_manifest():
    p = _prereg()
    return {
        "schema": "scroliq-ct-cutout/1",
        "status": "measured",
        "volume_root": p["volume_root"],
        "ct_url": p["ct_url"],
        "level": 0,
        "coordinate_space": "level0-voxel-index",
        "source_attestation": p["source_attestation"],
        "zpa_report": {
            "sha256": p["zpa_report_sha256"],
            "integrity": "PASS",
        },
        "bbox_zyx_half_open": p["cutout_bbox_zyx_half_open"],
        "source_chunks": {"missing_count": 0},
        "cutout": {
            "sha256": "c" * 64,
            "shape_zyx": [21, 21, 21],
            "dtype": "uint8",
        },
    }


def _sheetness_report():
    p = _prereg()
    return {
        "schema_version": 1,
        "kind": "sheetness",
        "input": {
            "sha256": "c" * 64,
            "shape_zyx": [21, 21, 21],
        },
        "method": p["engine"]["method"],
        "parameters": {
            "sigmas": p["engine"]["sigmas"],
            "beta": p["engine"]["beta"],
            "gamma": p["engine"]["gamma"],
            "bright_object": p["engine"]["bright_object"],
            "scale_objectness": p["engine"]["scale_objectness"],
        },
        "normalization": {
            "enabled": True,
            "lower_percentile": 1.0,
            "upper_percentile": 99.0,
            "lower_value": 2.0,
            "upper_value": 240.0,
        },
        "response": {"output_sha256": "d" * 64},
        "normal": {"output_sha256": "e" * 64},
    }


def test_valid_preregistration_normalizes_geometry_only_contract():
    got = pre.validate_preregistration(_prereg())
    assert got["benchmark_schema"] == pre.BENCHMARK_SCHEMA
    assert got["selection_rule"]["ct_intensity_used"] is False
    assert got["selection_rule"]["sheetness_outputs_used"] is False
    assert got["groups"][0]["controls"][0]["derivation"] == {
        "kind": "normal-offset",
        "sign": -1,
        "distance_voxels": 2.0,
    }


def test_validation_receipt_binds_raw_and_canonical_identity():
    p = _prereg()
    receipt = pre.validation_receipt(p, file_sha256="f" * 64)
    assert receipt["status"] == "valid"
    assert receipt["preregistration_file_sha256"] == "f" * 64
    assert len(receipt["preregistration_canonical_sha256"]) == 64
    assert receipt["contains_ct_response_values"] is False

    reordered = {key: p[key] for key in reversed(list(p))}
    other = pre.validation_receipt(reordered, file_sha256="0" * 64)
    assert (
        other["preregistration_canonical_sha256"]
        == receipt["preregistration_canonical_sha256"]
    )


@pytest.mark.parametrize("key", sorted(pre._FORBIDDEN_RESULT_KEYS))
def test_result_derived_top_level_fields_are_rejected(key):
    p = _prereg()
    p[key] = "post-result"
    with pytest.raises(pre.PreregistrationError, match="result-derived"):
        pre.validate_preregistration(p)


def test_normal_offsets_must_be_symmetric_geometry_derivations():
    p = _prereg()
    p["groups"][0]["controls"][0]["global_zyx"][0] = 97.9
    with pytest.raises(pre.PreregistrationError, match="normal-offset derivation"):
        pre.validate_preregistration(p)

    p = _prereg()
    p["groups"][0]["controls"][0]["derivation"]["sign"] = 1
    with pytest.raises(pre.PreregistrationError, match="symmetric"):
        pre.validate_preregistration(p)


def test_wrong_wrap_must_be_different_hash_pinned_surface():
    p = _prereg()
    p["groups"][0]["controls"][2]["source"] = _source("w035")
    with pytest.raises(pre.PreregistrationError, match="different surface"):
        pre.validate_preregistration(p)

    p = _prereg()
    p["groups"][0]["controls"][2]["source"]["coordinate_sha256"]["x.tif"] = "bad"
    with pytest.raises(pre.PreregistrationError, match="lowercase 64-hex"):
        pre.validate_preregistration(p)


def test_selection_must_be_geometry_only():
    p = _prereg()
    p["selection_rule"]["ct_intensity_used"] = True
    with pytest.raises(pre.PreregistrationError, match="ct_intensity_used"):
        pre.validate_preregistration(p)

    p = _prereg()
    p["selection_rule"]["sheetness_outputs_used"] = True
    with pytest.raises(pre.PreregistrationError, match="sheetness_outputs_used"):
        pre.validate_preregistration(p)


def test_finalize_adds_only_measured_bindings_and_local_coordinates():
    p = _prereg()
    spec = pre.finalize_spec(
        p,
        preregistration_file_sha256="f" * 64,
        cutout_manifest=_cutout_manifest(),
        cutout_manifest_file_sha256="1" * 64,
        sheetness_report=_sheetness_report(),
        sheetness_report_file_sha256="2" * 64,
    )
    assert spec["schema_version"] == int(pre.BENCHMARK_SCHEMA.rsplit("/", 1)[1])
    assert spec["preregistration"]["file_sha256"] == "f" * 64
    assert spec["input_sha256"] == "c" * 64
    assert spec["cutout_manifest_sha256"] == "1" * 64
    assert spec["sheetness_report_sha256"] == "2" * 64
    assert spec["groups"][0]["surface"]["zyx"] == [10.0, 10.0, 10.0]
    assert spec["groups"][0]["surface"]["frozen_global_zyx"] == [
        100.0,
        200.0,
        300.0,
    ]
    assert spec["groups"][0]["controls"][0]["zyx"] == [8.0, 10.0, 10.0]
    assert spec["decision_rule"] == pre.validate_preregistration(p)["decision_rule"]


@pytest.mark.parametrize(
    "mutator, message",
    [
        (
            lambda m: m.update(volume_root="PHerc0139/volumes/other.zarr"),
            "volume_root drifted",
        ),
        (
            lambda m: m["bbox_zyx_half_open"]["start"].__setitem__(0, 89),
            "cutout bbox drifted",
        ),
        (
            lambda m: m["zpa_report"].update(sha256="9" * 64),
            "ZPA report hash drifted",
        ),
        (
            lambda m: m["source_attestation"].update(
                metadata_semantics_sha256="8" * 64
            ),
            "source_attestation.metadata_semantics_sha256 drifted",
        ),
    ],
)
def test_finalize_rejects_cutout_provenance_drift(mutator, message):
    manifest = _cutout_manifest()
    mutator(manifest)
    with pytest.raises(pre.PreregistrationError, match=message):
        pre.finalize_spec(
            _prereg(),
            preregistration_file_sha256="f" * 64,
            cutout_manifest=manifest,
            cutout_manifest_file_sha256="1" * 64,
            sheetness_report=_sheetness_report(),
            sheetness_report_file_sha256="2" * 64,
        )


@pytest.mark.parametrize(
    "mutator, message",
    [
        (
            lambda r: r["parameters"].update(beta=0.6),
            "parameters drifted",
        ),
        (
            lambda r: r["normalization"].update(lower_percentile=2.0),
            "lower normalization percentile drifted",
        ),
        (
            lambda r: r.update(normal=None),
            "normal output is required",
        ),
        (
            lambda r: r["input"].update(sha256="9" * 64),
            "input hash does not match",
        ),
    ],
)
def test_finalize_rejects_engine_or_input_drift(mutator, message):
    report = _sheetness_report()
    mutator(report)
    with pytest.raises(pre.PreregistrationError, match=message):
        pre.finalize_spec(
            _prereg(),
            preregistration_file_sha256="f" * 64,
            cutout_manifest=_cutout_manifest(),
            cutout_manifest_file_sha256="1" * 64,
            sheetness_report=report,
            sheetness_report_file_sha256="2" * 64,
        )


def test_finalize_rejects_probe_outside_frozen_cutout():
    p = _prereg()
    p["groups"][0]["surface"]["global_zyx"] = [90.0, 190.0, 290.0]
    # Rebuild symmetric offsets around the moved surface so preregistration is valid.
    p["groups"][0]["controls"][0]["global_zyx"] = [88.0, 190.0, 290.0]
    p["groups"][0]["controls"][1]["global_zyx"] = [92.0, 190.0, 290.0]
    with pytest.raises(pre.PreregistrationError, match="interpolation domain"):
        pre.finalize_spec(
            p,
            preregistration_file_sha256="f" * 64,
            cutout_manifest=_cutout_manifest(),
            cutout_manifest_file_sha256="1" * 64,
            sheetness_report=_sheetness_report(),
            sheetness_report_file_sha256="2" * 64,
        )


def test_cli_validate_and_finalize_are_create_only(tmp_path, capsys):
    prereg = tmp_path / "prereg.json"
    prereg.write_text(json.dumps(_prereg(), sort_keys=True))
    receipt = tmp_path / "receipt.json"

    assert pre.main(["validate", "--prereg", str(prereg), "--out", str(receipt)]) == 0
    assert json.loads(receipt.read_text())["status"] == "valid"
    with pytest.raises(FileExistsError):
        pre.main(["validate", "--prereg", str(prereg), "--out", str(receipt)])

    cutout = tmp_path / "cutout.json"
    report = tmp_path / "sheetness.json"
    cutout.write_text(json.dumps(_cutout_manifest(), sort_keys=True))
    report.write_text(json.dumps(_sheetness_report(), sort_keys=True))
    spec = tmp_path / "spec.json"
    assert (
        pre.main(
            [
                "finalize",
                "--prereg",
                str(prereg),
                "--cutout-manifest",
                str(cutout),
                "--sheetness-report",
                str(report),
                "--out",
                str(spec),
            ]
        )
        == 0
    )
    assert json.loads(spec.read_text())["schema_version"] == int(
        pre.BENCHMARK_SCHEMA.rsplit("/", 1)[1]
    )
