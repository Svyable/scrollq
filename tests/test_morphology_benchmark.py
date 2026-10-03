import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
import tifffile

from scrollq import morphology_benchmark as mb


def _control():
    return {
        "schema_version": 1,
        "mode": "source_benchmark",
        "source": {
            "dataset_id": "scrollprize/profilometer",
            "revision": "a" * 40,
            "dataset_license": "CC BY-NC 4.0",
            "dataset_license_evidence": "https://example.org/data-license",
            "paper_url": "https://example.org/paper",
            "paper_license": "CC BY-NC-ND 4.0",
            "paper_license_evidence": "https://example.org/paper-license",
            "source_papyri": ["PHerc. 248", "PHerc. 250", "PHerc. 500P2"],
        },
        "sampling": {
            "dataset_native_um_xy": [0.68, 0.68],
            "manuscript_native_um_xy": [0.34, 0.34],
            "discrepancy_status": "unresolved",
        },
        "design": {
            "descriptors": [
                "local-gradient-rank",
                "curvature-rank",
                "fiber-relative-roughness",
            ],
            "source_split": "leave-one-papyrus-out",
            "learned_classifier": False,
            "source_labels_used_for_target_training": False,
            "paper_adapted_material_in_repo": False,
            "missingness_mask_control": True,
            "label_permutation_control": True,
            "uses_absolute_micron_thresholds": False,
        },
    }


def _write_json(path: Path, value) -> str:
    raw = (json.dumps(value, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _spec(control_sha: str):
    return {
        "schema_version": 1,
        "tool": "scroliq-morphology-benchmark",
        "experiment_id": "synthetic",
        "control_manifest_sha256": control_sha,
        "source_revision": "a" * 40,
        "source_split": "leave-one-papyrus-out",
        "expected_sample_count": 6,
        "descriptors": [
            "local-gradient-rank",
            "curvature-rank",
            "fiber-relative-roughness",
        ],
        "sampling": {
            "policy": "label-blind-interior-grid-v1",
            "max_sampled_pixels_per_sample": 1000,
            "border_pixels": 1,
            "min_sampled_ink_pixels": 2,
            "min_sampled_papyrus_pixels": 2,
        },
        "direction_rule": "median-training-sample-mean-rank-delta",
        "heldout_metric": "pooled-pixel-auroc",
        "controls": {
            "label_permutation": {
                "method": "deterministic-toroidal-label-roll-v1",
                "seed": 17,
            },
            "missingness": {
                "source": "raw-height-nonfinite-z",
                "metric": "discriminative-auroc=max(auc,1-auc)",
            },
        },
        "advance_rule": {
            "min_heldout_auc_each_papyrus": 0.5,
            "max_label_permutation_abs_auc_from_chance": 0.5,
            "max_missingness_discriminative_auc": 1.0,
        },
        "selection_contract": {
            "learned_classifier": False,
            "uses_absolute_micron_thresholds": False,
            "heldout_labels_choose_descriptor_direction": False,
            "candidate_renders_or_ocr_consumed": False,
            "target_ct_consumed": False,
        },
    }


def _write_sample(root: Path, papyrus_dir: str, papyrus_id: str, sample: str):
    d = root / "data" / papyrus_dir
    d.mkdir(parents=True, exist_ok=True)
    h = w = 9
    yy, xx = np.mgrid[:h, :w]
    label = ((xx >= 4) & (yy >= 2) & (yy <= 6))
    # Different smooth background slopes across samples plus a local ink
    # perturbation. The test only requires a valid reproducible benchmark, not
    # a particular descriptor to win.
    height = (1000 + 11 * yy + 7 * xx + label.astype(int) * (20 + yy)).astype(
        np.uint16
    )
    height_path = d / f"{sample}_z.tif"
    label_path = d / f"{sample}_label.png"
    raw_path = d / f"{sample}.txt"
    tifffile.imwrite(height_path, height)
    Image.fromarray((label * 255).astype(np.uint8)).save(label_path)

    lines = ["X;Y;Z\n"]
    for y in range(h):
        for x in range(w):
            # One ink and one background missing value keeps the control
            # nontrivial without making it predictive by construction.
            missing = (y, x) in {(3, 5), (7, 2)}
            z = "nan" if missing else f"{float(height[y, x]):.1f}"
            lines.append(f"{x};{y};{z}\n")
    raw_path.write_text("".join(lines), encoding="utf-8")
    return {
        "papyrus_dir": papyrus_dir,
        "papyrus_id": papyrus_id,
        "sample_id": sample,
        "acquisition_date": "2026-01-01",
        "width_px": str(w),
        "height_px": str(h),
        "pixel_count": str(h * w),
        "x_extent_um": "1",
        "y_extent_um": "1",
        "lateral_sampling_x_um": "0.68",
        "lateral_sampling_y_um": "0.68",
        "raw_height_txt": str(raw_path.relative_to(root)),
        "normalized_height_tif": str(height_path.relative_to(root)),
        "brightfield_tif": "",
        "label_png": str(label_path.relative_to(root)),
    }


def _dataset(tmp_path: Path):
    rows = []
    for papyrus_dir, papyrus_id in (
        ("pherc0248", "PHerc. 248"),
        ("pherc0250", "PHerc. 250"),
        ("pherc0500p2", "PHerc. 500P2"),
    ):
        for suffix in ("a", "b"):
            rows.append(
                _write_sample(
                    tmp_path,
                    papyrus_dir,
                    papyrus_id,
                    f"{papyrus_dir}-{suffix}",
                )
            )
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return manifest


def _inputs(tmp_path: Path):
    control_path = tmp_path / "control.json"
    control_sha = _write_json(control_path, _control())
    spec_path = tmp_path / "spec.json"
    _write_json(spec_path, _spec(control_sha))
    dataset_manifest = _dataset(tmp_path)
    return spec_path, control_path, dataset_manifest


def test_auc_is_tie_corrected():
    scores = np.array([0.0, 0.0, 1.0, 1.0])
    labels = np.array([0, 1, 0, 1], dtype=bool)
    assert mb._auc(scores, labels) == pytest.approx(0.5)


def test_rank01_is_deterministic_with_ties():
    x = np.array([5, 1, 5, 9], dtype=float)
    a = mb._rank01(x)
    b = mb._rank01(x.copy())
    assert np.array_equal(a, b)
    assert a[0] == a[2]
    assert a.min() >= 0 and a.max() <= 1


def test_permutation_shift_is_stable_and_nonzero():
    assert mb._permutation_shift("sample-x", 100, 80, 7) == mb._permutation_shift(
        "sample-x", 100, 80, 7
    )
    dy, dx = mb._permutation_shift("sample-x", 100, 80, 7)
    assert 0 < dy < 100 and 0 < dx < 80


def test_source_benchmark_roundtrip_is_partial_and_never_authorizes_target(tmp_path):
    spec, control, dataset = _inputs(tmp_path)
    result = mb.run_benchmark(
        spec_path=spec,
        control_manifest_path=control,
        dataset_manifest_path=dataset,
        data_root=tmp_path,
    )
    assert result["status"] == "partial"
    assert result["target_transfer_authorized"] is False
    assert len(result["folds"]) == 3
    assert result["sampling"]["actual_sample_count"] == 6
    assert set(result["decisions"]) == {
        "local-gradient-rank",
        "curvature-rank",
        "fiber-relative-roughness",
    }
    assert all(len(sample["hashes"]["raw_height_txt"]) == 64 for sample in result["samples"])


def test_control_manifest_hash_mismatch_fails_before_benchmark(tmp_path):
    spec, control, dataset = _inputs(tmp_path)
    value = json.loads(spec.read_text())
    value["control_manifest_sha256"] = "0" * 64
    spec.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(mb.BenchmarkError, match="control manifest SHA-256"):
        mb.run_benchmark(
            spec_path=spec,
            control_manifest_path=control,
            dataset_manifest_path=dataset,
            data_root=tmp_path,
        )


def test_raw_txt_row_count_mismatch_fails_closed(tmp_path):
    spec, control, dataset = _inputs(tmp_path)
    rows = list(csv.DictReader(dataset.open()))
    raw = tmp_path / rows[0]["raw_height_txt"]
    raw.write_text("X;Y;Z\n0;0;1\n", encoding="utf-8")
    with pytest.raises(mb.BenchmarkError, match="data-row count"):
        mb.run_benchmark(
            spec_path=spec,
            control_manifest_path=control,
            dataset_manifest_path=dataset,
            data_root=tmp_path,
        )


def test_cli_create_only_output(tmp_path, capsys):
    spec, control, dataset = _inputs(tmp_path)
    out = tmp_path / "result.json"
    args = [
        "--spec",
        str(spec),
        "--control-manifest",
        str(control),
        "--dataset-manifest",
        str(dataset),
        "--data-root",
        str(tmp_path),
        "--out",
        str(out),
    ]
    assert mb.main(args) == 1
    before = out.read_bytes()
    assert mb.main(args) == 2
    assert out.read_bytes() == before
    assert "refusing to overwrite" in capsys.readouterr().err
