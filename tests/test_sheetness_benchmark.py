import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scrollq import sheetness_benchmark as bench


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(
    tmp_path: Path,
    *,
    bad_control=False,
    high_wrong_wrap=False,
    decision=None,
):
    response = np.zeros((5, 5, 5), dtype=np.float32)
    normals = np.zeros((5, 5, 5, 3), dtype=np.float32)

    response[2, 2, 2] = 0.9
    response[1, 2, 2] = 0.4
    response[3, 2, 2] = 0.95 if high_wrong_wrap else 0.3
    normals[2, 2, 2] = [1, 0, 0]

    response[2, 3, 2] = 0.8
    response[1, 3, 2] = np.nan if bad_control else 0.2
    response[3, 3, 2] = 0.90 if high_wrong_wrap else 0.1
    normals[2, 3, 2] = [-1, 0, 0]

    response_path = tmp_path / "x.sheetness.npy"
    normal_path = tmp_path / "x.normal-zyx.npy"
    np.save(response_path, response, allow_pickle=False)
    np.save(normal_path, normals, allow_pickle=False)

    cutout_sha = "a" * 64
    volume_root = "community-uploads/example/PHerc0813/eligible.zarr"
    source_attestation = {
        "algorithm": "zpa-metadata-semantics-v1",
        "state": "PRESENT",
        "metadata_semantics_sha256": "b" * 64,
        "axes": ["z", "y", "x"],
    }
    cutout_manifest = {
        "schema": "scroliq-ct-cutout/1",
        "status": "measured",
        "volume_root": volume_root,
        "ct_url": f"https://example.test/{volume_root}",
        "level": 0,
        "coordinate_space": "level0-voxel-index",
        "source_attestation": source_attestation,
        "zpa_report": {
            "sha256": "c" * 64,
            "integrity": "PASS",
        },
        "bbox_zyx_half_open": {
            "start": [100, 200, 300],
            "stop": [105, 205, 305],
        },
        "local_to_global": {
            "kind": "integer-translation",
            "start_zyx": [100, 200, 300],
        },
        "source_chunks": {"missing_count": 0},
        "cutout": {
            "sha256": cutout_sha,
            "shape_zyx": [5, 5, 5],
            "dtype": "uint8",
        },
    }
    cutout_manifest_path = tmp_path / "cutout.json"
    cutout_manifest_path.write_text(json.dumps(cutout_manifest, sort_keys=True))

    report = {
        "schema_version": 1,
        "kind": "sheetness",
        "input": {"sha256": cutout_sha, "shape_zyx": [5, 5, 5]},
        "method": "method",
        "parameters": {"sigmas": [1.0]},
        "normalization": {"enabled": False},
        "response": {"output_sha256": _sha(response_path)},
        "normal": {"output_sha256": _sha(normal_path)},
    }
    report_path = tmp_path / "x.sheetness.json"
    report_path.write_text(json.dumps(report))

    rule = decision or {
        "min_localization_completeness": 1.0,
        "min_surface_beats_offset_fraction": 1.0,
        "min_median_surface_offset_margin": 0.2,
        "min_wrong_wrap_completeness": 1.0,
        "min_normal_completeness": 1.0,
        "min_median_abs_cosine": 0.99,
    }
    spec = {
        "schema_version": 3,
        "volume_root": volume_root,
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": "b" * 64,
        },
        "input_sha256": cutout_sha,
        "cutout_manifest_sha256": _sha(cutout_manifest_path),
        "sheetness_report_sha256": _sha(report_path),
        "decision_rule": rule,
        "groups": [
            {
                "id": "g1",
                "surface": {
                    "zyx": [2, 2, 2],
                    "reference_normal_zyx": [1, 0, 0],
                },
                "controls": [
                    {
                        "id": "g1-off",
                        "role": "normal-offset",
                        "zyx": [1, 2, 2],
                    },
                    {
                        "id": "g1-wrong",
                        "role": "wrong-wrap",
                        "zyx": [3, 2, 2],
                    },
                ],
            },
            {
                "id": "g2",
                "surface": {
                    "zyx": [2, 3, 2],
                    "reference_normal_zyx": [1, 0, 0],
                },
                "controls": [
                    {
                        "id": "g2-off",
                        "role": "normal-offset",
                        "zyx": [1, 3, 2],
                    },
                    {
                        "id": "g2-wrong",
                        "role": "wrong-wrap",
                        "zyx": [3, 3, 2],
                    },
                ],
            },
        ],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec, sort_keys=True))
    return (
        spec_path,
        cutout_manifest_path,
        report_path,
        response_path,
        normal_path,
    )


def test_passes_frozen_surface_vs_control_benchmark(tmp_path):
    paths = _bundle(tmp_path)
    result = bench.run(*paths)
    assert result["schema"] == "scroliq-sheetness-benchmark/3"
    assert result["status"] == "pass"
    assert result["metrics"]["group_count"] == 2
    assert result["metrics"]["surface_beats_offset_fraction"] == 1.0
    assert result["metrics"]["localization_completeness"] == 1.0
    assert result["metrics"]["wrong_wrap_completeness"] == 1.0
    assert result["metrics"]["normal_completeness"] == 1.0
    assert result["metrics"]["median_abs_cosine"] == pytest.approx(1.0)
    assert result["metrics"]["median_surface_minus_best_normal_offset"] == pytest.approx(0.55)
    assert result["metrics"]["median_wrong_wrap_sheetness"] == pytest.approx(0.2)
    assert result["engine"]["stochastic"] is False
    assert result["inputs"]["global_bbox_zyx_half_open"]["start"] == [100, 200, 300]
    assert result["inputs"]["zpa_report_sha256"] == "c" * 64
    assert result["groups"][0]["surface"]["global_zyx"] == [102.0, 202.0, 302.0]
    assert result["groups"][0]["controls"][0]["global_zyx"] == [101.0, 202.0, 302.0]
    assert len(result["spec"]["canonical_sha256"]) == 64


def test_failed_probe_stays_in_denominator(tmp_path):
    paths = _bundle(tmp_path, bad_control=True)
    result = bench.run(*paths)
    assert result["status"] == "fail"
    assert result["metrics"]["localization_complete_count"] == 1
    assert result["metrics"]["localization_completeness"] == 0.5
    assert result["metrics"]["surface_beats_offset_count"] == 1
    assert result["metrics"]["surface_beats_offset_fraction"] == 0.5
    assert result["metrics"]["wrong_wrap_completeness"] == 1.0
    row = result["groups"][1]
    assert row["localization_complete"] is False
    assert row["controls"][0]["failure"] == "non-finite"


def test_wrong_wrap_is_ambiguity_evidence_not_a_negative(tmp_path):
    paths = _bundle(tmp_path, high_wrong_wrap=True)
    result = bench.run(*paths)

    assert result["status"] == "pass"
    assert result["metrics"]["surface_beats_offset_fraction"] == 1.0
    assert result["metrics"]["median_wrong_wrap_sheetness"] == pytest.approx(0.925)
    assert all(
        row["surface_beats_all_normal_offsets"]
        for row in result["groups"]
    )


def test_report_hash_is_bound_by_frozen_spec(tmp_path):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    payload = json.loads(report.read_text())
    payload["parameters"]["sigmas"] = [2.0]
    report.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="report sha256"):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_array_hashes_are_bound_by_report(tmp_path):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    arr = np.load(response, allow_pickle=False)
    arr[0, 0, 0] = 0.5
    np.save(response, arr, allow_pickle=False)
    with pytest.raises(ValueError, match="response array sha256"):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_surface_normal_sign_is_irrelevant(tmp_path):
    paths = _bundle(tmp_path)
    result = bench.run(*paths)
    assert result["groups"][1]["surface"]["predicted_normal_abs_cosine"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "mutator, message",
    [
        (
            lambda s: s["groups"][0]["controls"].pop(),
            "missing required control roles",
        ),
        (lambda s: s["groups"][0].update(id="g2"), "duplicate group id"),
        (
            lambda s: s["source_attestation"].update(state="UNKNOWN"),
            "source_attestation.state must be PRESENT",
        ),
    ],
)
def test_invalid_specs_fail_closed(tmp_path, mutator, message):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    payload = json.loads(spec.read_text())
    mutator(payload)
    spec.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=message):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_cutout_manifest_is_frozen_and_spatially_bound(tmp_path):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    payload = json.loads(cutout_manifest.read_text())
    payload["bbox_zyx_half_open"]["start"] = [99, 200, 300]
    cutout_manifest.write_text(json.dumps(payload, sort_keys=True))
    with pytest.raises(ValueError, match="cutout manifest sha256"):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_cutout_manifest_source_attestation_must_match_spec(tmp_path):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    manifest = json.loads(cutout_manifest.read_text())
    manifest["source_attestation"]["metadata_semantics_sha256"] = "c" * 64
    cutout_manifest.write_text(json.dumps(manifest, sort_keys=True))

    frozen = json.loads(spec.read_text())
    frozen["cutout_manifest_sha256"] = _sha(cutout_manifest)
    spec.write_text(json.dumps(frozen, sort_keys=True))

    with pytest.raises(ValueError, match="source_attestation"):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_cutout_manifest_bbox_and_shape_must_agree(tmp_path):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    manifest = json.loads(cutout_manifest.read_text())
    manifest["bbox_zyx_half_open"]["stop"] = [106, 205, 305]
    cutout_manifest.write_text(json.dumps(manifest, sort_keys=True))

    frozen = json.loads(spec.read_text())
    frozen["cutout_manifest_sha256"] = _sha(cutout_manifest)
    spec.write_text(json.dumps(frozen, sort_keys=True))

    with pytest.raises(ValueError, match="bbox extent"):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_cli_returns_one_for_valid_negative_result(tmp_path, capsys):
    paths = _bundle(tmp_path, bad_control=True)
    code = bench.main(
        [
            "--spec", str(paths[0]),
            "--cutout-manifest", str(paths[1]),
            "--report", str(paths[2]),
            "--response", str(paths[3]),
            "--normal", str(paths[4]),
            "--require-pass",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"


def test_cli_returns_two_for_invalid_bundle(tmp_path, capsys):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    spec.write_text("{}")
    code = bench.main(
        [
            "--spec", str(spec),
            "--cutout-manifest", str(cutout_manifest),
            "--report", str(report),
            "--response", str(response),
            "--normal", str(normal),
        ]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"


def test_continuous_probe_uses_trilinear_sampling():
    response = np.zeros((3, 3, 3), dtype=np.float64)
    for z in range(3):
        response[z, :, :] = z

    value, failure = bench._value_at(response, (0.5, 1.25, 1.75))
    assert failure is None
    assert value == pytest.approx(0.5)


def test_continuous_normal_interpolation_is_eigenvector_sign_safe():
    normals = np.zeros((2, 2, 2, 3), dtype=np.float64)
    normals[:] = [1.0, 0.0, 0.0]
    normals[0, 0, 0] = [-1.0, 0.0, 0.0]
    normals[1, 1, 1] = [-1.0, 0.0, 0.0]

    cosine, failure = bench._normal_at(
        normals,
        (0.5, 0.5, 0.5),
        np.asarray([1.0, 0.0, 0.0]),
    )
    assert failure is None
    assert cosine == pytest.approx(1.0)


def test_fractional_probe_coordinates_are_reported_in_global_ct_space(tmp_path):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    payload = json.loads(spec.read_text())
    payload["groups"][0]["surface"]["zyx"] = [2.25, 2.5, 2.75]
    payload["groups"][0]["controls"][0]["zyx"] = [1.25, 2.5, 2.75]
    spec.write_text(json.dumps(payload, sort_keys=True))

    result = bench.run(spec, cutout_manifest, report, response, normal)
    assert result["groups"][0]["surface"]["global_zyx"] == [
        102.25,
        202.5,
        302.75,
    ]


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda m: m["zpa_report"].update(integrity="WARN"), "PASS ZPA"),
        (lambda m: m["zpa_report"].update(sha256="bad"), "zpa_report.sha256"),
        (
            lambda m: m["source_attestation"].update(axes=["x", "y", "z"]),
            "source_attestation.axes",
        ),
    ],
)
def test_cutout_manifest_retains_zpa_proof(tmp_path, mutation, message):
    spec, cutout_manifest, report, response, normal = _bundle(tmp_path)
    manifest = json.loads(cutout_manifest.read_text())
    mutation(manifest)
    cutout_manifest.write_text(json.dumps(manifest, sort_keys=True))

    frozen = json.loads(spec.read_text())
    frozen["cutout_manifest_sha256"] = _sha(cutout_manifest)
    spec.write_text(json.dumps(frozen, sort_keys=True))

    with pytest.raises(ValueError, match=message):
        bench.run(spec, cutout_manifest, report, response, normal)


def test_result_retains_zpa_report_hash(tmp_path):
    result = bench.run(*_bundle(tmp_path))
    assert result["inputs"]["zpa_report_sha256"] == "c" * 64
