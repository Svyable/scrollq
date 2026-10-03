import hashlib
import json

import pytest

from scrollq.model_release import (
    DATA_LICENSE,
    ReleaseValidationError,
    audit_release,
    main,
    validate_release_manifest,
)


def _manifest(tmp_path, *, pseudo=True):
    release = tmp_path / "release"
    release.mkdir()
    train = release / "train.tar"
    pseudo_data = release / "pseudo.tar"
    stage0 = release / "stage0.ckpt"
    final = release / "final.ckpt"
    train.write_bytes(b"train")
    pseudo_data.write_bytes(b"pseudo")
    stage0.write_bytes(b"stage0")
    final.write_bytes(b"final")

    datasets = [
        {
            "id": "train0",
            "role": "training",
            "public_url": "https://example.org/train0",
            "license": DATA_LICENSE,
            "sha256": hashlib.sha256(train.read_bytes()).hexdigest(),
            "path": "release/train.tar",
        }
    ]
    checkpoints = [
        {
            "id": "final",
            "role": "final",
            "stage": 0,
            "public_url": "https://example.org/final",
            "license": DATA_LICENSE if pseudo else "MIT",
            "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
            "path": "release/final.ckpt",
            "training_dataset_ids": ["train0"],
            "parent_checkpoint_ids": [],
        }
    ]
    runs = [
        {
            "id": "train-final",
            "kind": "training",
            "checkpoint_id": "final",
            "public_url": "https://example.org/runs/train-final",
            "public": True,
            "stochastic": True,
            "random_seed": 7,
        },
        {
            "id": "infer-final",
            "kind": "inference",
            "checkpoint_id": "final",
            "public_url": "https://example.org/runs/infer-final",
            "public": True,
            "stochastic": False,
        },
    ]

    if pseudo:
        datasets.append(
            {
                "id": "pseudo1",
                "role": "pseudo-label",
                "public_url": "https://example.org/pseudo1",
                "license": DATA_LICENSE,
                "sha256": hashlib.sha256(pseudo_data.read_bytes()).hexdigest(),
                "path": "release/pseudo.tar",
                "producer_checkpoint_id": "stage0",
            }
        )
        checkpoints = [
            {
                "id": "stage0",
                "role": "intermediate",
                "stage": 0,
                "public_url": "https://example.org/stage0",
                "license": DATA_LICENSE,
                "sha256": hashlib.sha256(stage0.read_bytes()).hexdigest(),
                "path": "release/stage0.ckpt",
                "training_dataset_ids": ["train0"],
                "parent_checkpoint_ids": [],
            },
            {
                "id": "final",
                "role": "final",
                "stage": 1,
                "public_url": "https://example.org/final",
                "license": DATA_LICENSE,
                "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
                "path": "release/final.ckpt",
                "training_dataset_ids": ["train0", "pseudo1"],
                "parent_checkpoint_ids": ["stage0"],
            },
        ]
        runs.extend(
            [
                {
                    "id": "train-stage0",
                    "kind": "training",
                    "checkpoint_id": "stage0",
                    "public_url": "https://example.org/runs/train-stage0",
                    "public": True,
                    "stochastic": False,
                },
                {
                    "id": "infer-stage0",
                    "kind": "inference",
                    "checkpoint_id": "stage0",
                    "public_url": "https://example.org/runs/infer-stage0",
                    "public": True,
                    "stochastic": True,
                    "random_seed": 11,
                },
            ]
        )

    return {
        "schema_version": 1,
        "id": "release-v1",
        "visibility": "public",
        "code": {
            "repository": "https://github.com/Svyable/scrollq",
            "commit": "a" * 40,
        },
        "pseudo_labeling": pseudo,
        "datasets": datasets,
        "checkpoints": checkpoints,
        "final_checkpoint_id": "final",
        "runs": runs,
    }


def test_valid_pseudo_label_release_hashes_all_artifacts(tmp_path):
    manifest = _manifest(tmp_path)
    report = audit_release(manifest, root=tmp_path)
    assert report["release_ready"] is True
    assert report["summary"] == {
        "datasets": 2,
        "checkpoints": 2,
        "runs": 4,
        "pseudo_labeling": True,
    }
    assert all(row["ok"] for row in report["checks"])


def test_dataset_license_is_fixed(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["datasets"][0]["license"] = "MIT"
    with pytest.raises(ReleaseValidationError, match="CC-BY-NC-4.0"):
        validate_release_manifest(manifest)


def test_pseudo_label_dataset_requires_producer(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["datasets"][1].pop("producer_checkpoint_id")
    with pytest.raises(ReleaseValidationError, match="producer_checkpoint_id"):
        validate_release_manifest(manifest)


def test_pseudo_labeling_requires_checkpoint_license(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["checkpoints"][0]["license"] = "MIT"
    with pytest.raises(ReleaseValidationError, match="all checkpoints"):
        validate_release_manifest(manifest)


def test_stochastic_run_requires_seed(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["runs"][0].pop("random_seed")
    with pytest.raises(ReleaseValidationError, match="random_seed"):
        validate_release_manifest(manifest)


def test_hash_mismatch_blocks_release(tmp_path):
    manifest = _manifest(tmp_path, pseudo=False)
    manifest["checkpoints"][0]["sha256"] = "0" * 64
    report = audit_release(manifest, root=tmp_path)
    assert report["release_ready"] is False
    failed = [row for row in report["checks"] if not row["ok"]]
    assert len(failed) == 1
    assert "mismatch" in failed[0]["detail"]


def test_metadata_only_allows_remote_only_artifacts(tmp_path):
    manifest = _manifest(tmp_path, pseudo=False)
    manifest["datasets"][0].pop("path")
    manifest["checkpoints"][0].pop("path")
    report = audit_release(manifest, root=tmp_path, require_local=False)
    assert report["release_ready"] is True


def test_cli_writes_report_and_refuses_overwrite(tmp_path):
    manifest = _manifest(tmp_path, pseudo=False)
    manifest_path = tmp_path / "manifest.json"
    out = tmp_path / "validation.json"
    manifest_path.write_text(json.dumps(manifest))
    args = [
        "--manifest",
        str(manifest_path),
        "--root",
        str(tmp_path),
        "--out",
        str(out),
        "--format",
        "json",
    ]
    assert main(args) == 0
    assert json.loads(out.read_text())["release_ready"] is True
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        main(args)
