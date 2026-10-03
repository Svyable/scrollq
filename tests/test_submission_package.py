import hashlib
import json
import shutil
import zipfile

import pytest

import scrollq.submission_package as pkg


def _package_manifest():
    return {
        "schema_version": 7,
        "submission": {
            "scroll_id": "PHerc0813",
            "eligible_volume_id": "20250821151723",
            "human_input_hours": 1.5,
        },
        "code": {
            "docker_image": "ghcr.io/example/pipeline@sha256:" + "b" * 64,
        },
        "ct_volume": {
            "volume_id": "20250821151723",
            "zarr_audit": {
                "path": "evidence/zpa-report.json",
            }
        },
        "surfaces": [],
        "meshes": [
            {
                "id": "mesh:column-01",
                "path": "column_01.tifxyz",
                "column": 1,
                "sha256": "1" * 64,
            }
        ],
        "renders": [
            {
                "id": "render:column-01",
                "path": "column_01.tif",
                "column": 1,
                "mesh_id": "mesh:column-01",
                "sha256": "2" * 64,
                "vc3d_receipt": {
                    "tool": "scroliq-vc3d",
                    "path": "evidence/column_01.vc3d.json",
                    "sha256": "9" * 64,
                },
                "scale_proof": {
                    "tool": "scroliq-submission-image",
                    "path": "evidence/column_01.scale.json",
                    "sha256": "7" * 64,
                    "base_voxel_size_um": 9.362,
                    "group_idx": 0,
                    "render_scale": 1.0,
                    "micrometers_per_output_pixel": 9.362,
                    "scale_bar_pixels": 1068,
                },
            }
        ],
        "held_out_validations": [{"path": "validation/heldout.json"}],
        "banner": {"path": "banner.tif", "proof": {"path": "evidence/banner.json"}},
    }


def _write_tree(root):
    manifest = _package_manifest()
    (root / "evidence").mkdir(parents=True)
    (root / "validation").mkdir(parents=True)
    mesh = root / "column_01.tifxyz"
    mesh.mkdir(parents=True)

    (root / "evidence" / "zpa-report.json").write_bytes(b"zpa")
    raw_dir = root / "raw" / "column_01"
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "00.tif"
    raw_path.write_bytes(b"raw-ct-render")
    raw_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    log_path = root / "evidence" / "column_01.vc3d.log"
    log_path.write_bytes(b"vc3d render log\n")
    log_sha = hashlib.sha256(log_path.read_bytes()).hexdigest()

    scale_payload = {
        "schema_version": 1,
        "tool": "scroliq-submission-image",
        "operation": "column",
        "column": 1,
        "input": {
            "path": "00.tif",
            "sha256": raw_sha,
            "size_xy": [1200, 100],
        },
        "output": {
            "path": "column_01.tif",
            "sha256": "2" * 64,
            "size_xy": [1200, 148],
        },
        "vc_render_tifxyz": {
            "base_voxel_size_um": 9.362,
            "group_idx": 0,
            "render_scale": 1.0,
            "ds_scale": 1.0,
            "micrometers_per_output_pixel": 9.362,
            "formula": "base_voxel_size_um / (2**-group_idx) / render_scale",
        },
        "scale_bar": {
            "centimeters": 1,
            "micrometers": 10000,
            "pixels": 1068,
        },
    }
    scale_raw = json.dumps(scale_payload, sort_keys=True).encode("utf-8")
    (root / "evidence" / "column_01.scale.json").write_bytes(scale_raw)
    manifest["renders"][0]["scale_proof"]["sha256"] = hashlib.sha256(
        scale_raw
    ).hexdigest()

    receipt_payload = {
        "schema_version": 1,
        "tool": "scroliq-vc3d",
        "operation": "render-column",
        "column": 1,
        "vc3d": {
            "repository": "https://github.com/ScrollPrize/villa",
            "commit": "1" * 40,
            "binary": {
                "name": "vc_render_tifxyz",
                "size": 123456,
                "sha256": "a" * 64,
                "help_sha256": "b" * 64,
                "help_headline": "vc_render_tifxyz",
            },
        },
        "inputs": {
            "volume": {
                "path": "/eligible/20250821151723.zarr",
                "volume_id": "20250821151723",
                "base_voxel_size_um": 9.362,
            },
            "mesh": {
                "path": "column_01.tifxyz",
                "sha256": "1" * 64,
                "meta_sha256": "c" * 64,
                "target_volume": "20250821151723.zarr",
                "scale": [1.0, 1.0],
            },
        },
        "render": {
            "group_idx": 0,
            "scale": 1.0,
            "num_slices": 1,
            "tif_output_dir": "raw/column_01",
            "argv": [],
            "extra_args": [],
            "exit_code": 0,
        },
        "output": {
            "path": "raw/column_01/00.tif",
            "size": raw_path.stat().st_size,
            "sha256": raw_sha,
            "width": 1200,
            "height": 100,
            "mode": "L",
        },
        "log": {
            "path": "evidence/column_01.vc3d.log",
            "size": log_path.stat().st_size,
            "sha256": log_sha,
        },
        "receipt_path": "evidence/column_01.vc3d.json",
    }
    receipt_raw = json.dumps(receipt_payload, sort_keys=True).encode("utf-8")
    (root / "evidence" / "column_01.vc3d.json").write_bytes(receipt_raw)
    manifest["renders"][0]["vc3d_receipt"]["sha256"] = hashlib.sha256(
        receipt_raw
    ).hexdigest()

    (root / "evidence" / "banner.json").write_bytes(b"banner-proof")
    (root / "validation" / "heldout.json").write_bytes(b"heldout")
    (root / "column_01.tif").write_bytes(b"render")
    (root / "banner.tif").write_bytes(b"banner")
    (root / "unrelated.txt").write_bytes(b"must not be packaged")
    (root / "METHODOLOGY.md").write_text(
        "# Methodology\nReproduce the CT-to-surface-to-render pipeline.\n",
        encoding="utf-8",
    )
    (root / "SYSTEM_REQUIREMENTS.md").write_text(
        "# System requirements\nLinux, Docker, sufficient disk and GPU memory.\n",
        encoding="utf-8",
    )
    (root / "VC3D_WORKFLOW.md").write_text(
        "# VC3D workflow\nOpen the exact eligible volume and submitted TIFXYZ meshes.\n",
        encoding="utf-8",
    )
    (root / "FALSE_POSITIVES.md").write_text(
        "# False-positive mitigation\nUse held-out evidence and falsification controls.\n",
        encoding="utf-8",
    )
    (root / "human-input.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "description": "Review surface handoff",
                        "hours": 1.5,
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    characters = []
    for index in range(10):
        status = "legible" if index < 7 else "illegible"
        character = {
            "id": f"c{index + 1:02d}",
            "status": status,
            "bbox_xyxy": [index * 10, 0, index * 10 + 8, 14],
        }
        if status == "legible":
            character["reading"] = "α"
            character["interpolated"] = False
        characters.append(character)
    (root / "legibility.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scroll_id": "PHerc0813",
                "columns": [
                    {
                        "column": 1,
                        "render_id": "render:column-01",
                        "mesh_id": "mesh:column-01",
                        "render_sha256": "2" * 64,
                        "mesh_sha256": "1" * 64,
                        "counted": True,
                        "lines": [{"line": 1, "characters": characters}],
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (mesh / "meta.json").write_bytes(b"{}")
    (mesh / "x.tif").write_bytes(b"x")
    (mesh / "y.tif").write_bytes(b"y")
    (mesh / "z.tif").write_bytes(b"z")

    manifest_path = root / "provenance.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _passing_validation(manifest, *, root_dir=None, manifest_sha256=None):
    return {
        "validator": "scrollq.provenance",
        "validator_schema_version": 7,
        "manifest_sha256": manifest_sha256,
        "graph_sha256": "a" * 64,
        "eligible": True,
        "error_count": 0,
        "warning_count": 0,
        "errors": [],
        "warnings": [],
    }


def test_package_is_deterministic_and_only_contains_declared_artifacts(
    tmp_path, monkeypatch
):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    result1 = pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=first,
    )
    result2 = pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=second,
    )

    assert first.read_bytes() == second.read_bytes()
    assert result1["archive_sha256"] == result2["archive_sha256"]
    assert pkg.verify_package(first)["valid"] is True
    assert first.with_name("first.zip.sha256").is_file()

    with zipfile.ZipFile(first) as zf:
        ordered_names = zf.namelist()
        assert ordered_names == sorted(ordered_names)
        names = set(ordered_names)
        assert "unrelated.txt" not in names
        assert "provenance.json" in names
        assert "evidence/zpa-report.json" in names
        assert "evidence/column_01.scale.json" in names
        assert "evidence/column_01.vc3d.json" in names
        assert "evidence/column_01.vc3d.log" in names
        assert "raw/column_01/00.tif" in names
        assert "evidence/banner.json" in names
        assert "column_01.tifxyz/meta.json" in names
        assert "column_01.tifxyz/x.tif" in names
        assert "column_01.tifxyz/y.tif" in names
        assert "column_01.tifxyz/z.tif" in names
        assert "column_01.tif" in names
        assert "validation/heldout.json" in names
        assert "banner.tif" in names
        assert pkg.VALIDATION_PATH in names
        assert pkg.REVIEWER_CONTRACT_PATH in names
        assert pkg.LEGIBILITY_VALIDATION_PATH in names
        assert pkg.INDEX_PATH in names
        assert "METHODOLOGY.md" in names
        assert "SYSTEM_REQUIREMENTS.md" in names
        assert "human-input.json" in names
        assert "VC3D_WORKFLOW.md" in names
        assert "FALSE_POSITIVES.md" in names
        assert "legibility.json" in names
        legibility = json.loads(zf.read(pkg.LEGIBILITY_VALIDATION_PATH))
        assert legibility["passes_recorded_thresholds"] is True
        assert legibility["summary"]["legible_characters"] == 7
        assert legibility["summary"]["preserved_characters"] == 10
        index = json.loads(zf.read(pkg.INDEX_PATH))
        assert index["schema_version"] == 4
        assert index["vc3d_receipts"][0]["column"] == 1
        assert index["vc3d_receipts"][0]["raw_render_path"] == "raw/column_01/00.tif"
        assert index["vc3d_receipts"][0]["log_path"] == "evidence/column_01.vc3d.log"
        reviewer = json.loads(zf.read(pkg.REVIEWER_CONTRACT_PATH))
        assert reviewer["columns"]["meshes"] == [1]
        assert reviewer["columns"]["renders"] == [1]
        assert reviewer["human_input"]["ledger_hours"] == 1.5
        assert reviewer["materials"]["legibility_ledger"]["path"] == "legibility.json"
        assert reviewer["legibility"]["threshold"] == 0.70
        assert (
            reviewer["reproduction"]["docker_image"]
            in reviewer["reproduction"]["docker_run_command"]
        )


def test_package_verifier_rejects_extra_unindexed_member(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    archive = tmp_path / "submission.zip"
    pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=archive,
    )

    with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("injected.txt", b"not indexed")

    report = pkg.verify_package(archive)
    assert report["valid"] is False
    assert any("archive/index member mismatch" in error for error in report["errors"])


def test_package_verifier_rejects_reindexed_raw_vc3d_tampering(
    tmp_path, monkeypatch
):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    archive = tmp_path / "submission.zip"
    pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=archive,
    )

    rewritten = tmp_path / "reindexed-tamper.zip"
    with zipfile.ZipFile(archive, "r") as src:
        payloads = {name: src.read(name) for name in src.namelist()}

    forged = b"attacker-reindexed-raw-render"
    raw_name = "raw/column_01/00.tif"
    payloads[raw_name] = forged
    index = json.loads(payloads[pkg.INDEX_PATH])
    forged_sha = hashlib.sha256(forged).hexdigest()
    for row in index["files"]:
        if row["path"] == raw_name:
            row["size"] = len(forged)
            row["sha256"] = forged_sha
    index["vc3d_receipts"][0]["raw_render_sha256"] = forged_sha
    payloads[pkg.INDEX_PATH] = pkg._json_bytes(index)

    with zipfile.ZipFile(
        rewritten, "w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as dst:
        for name in sorted(payloads):
            dst.writestr(pkg._zip_info(name), payloads[name])

    report = pkg.verify_package(rewritten)

    assert report["valid"] is False
    assert any(
        "raw VC3D render hash mismatch" in error
        for error in report["errors"]
    )


def test_package_builder_refuses_failed_provenance(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = root / "provenance.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    def fail_validation(manifest, *, root_dir=None, manifest_sha256=None):
        return {
            "eligible": False,
            "errors": [{"code": "GP_TEST_FAILURE"}],
            "graph_sha256": "b" * 64,
        }

    monkeypatch.setattr(pkg, "validate_manifest", fail_validation)

    with pytest.raises(pkg.PackageError, match="GP_TEST_FAILURE"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "should-not-exist.zip",
        )
    assert not (tmp_path / "should-not-exist.zip").exists()


def test_package_builder_rejects_symlink_inside_tifxyz(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    mesh = root / "column_01.tifxyz"
    (mesh / "x.tif").unlink()
    target = tmp_path / "external-x.tif"
    target.write_bytes(b"x")
    link = mesh / "x.tif"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(pkg.PackageError, match="symlink"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "unsafe.zip",
        )


def test_package_archive_tampering_is_detected(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    archive = tmp_path / "submission.zip"
    pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=archive,
    )

    tampered = tmp_path / "tampered.zip"
    shutil.copyfile(archive, tampered)
    with zipfile.ZipFile(tampered, "a", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("banner.tif", b"tampered banner")

    report = pkg.verify_package(tampered)
    assert report["valid"] is False
    assert any(
        "duplicate member" in error or "sha256 mismatch" in error
        for error in report["errors"]
    )


def test_package_builder_refuses_overwrite(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    archive = tmp_path / "submission.zip"
    pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=archive,
    )
    original = archive.read_bytes()

    with pytest.raises(pkg.PackageError, match="refusing to overwrite"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=archive,
        )
    assert archive.read_bytes() == original


def test_verifier_rejects_nondeterministic_member_order_and_mode(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    archive = tmp_path / "submission.zip"
    pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=archive,
    )

    rewritten = tmp_path / "rewritten.zip"
    with zipfile.ZipFile(archive, "r") as src, zipfile.ZipFile(
        rewritten, "w", compression=zipfile.ZIP_STORED
    ) as dst:
        names = src.namelist()
        for i, name in enumerate(reversed(names)):
            payload = src.read(name)
            info = zipfile.ZipInfo(name, date_time=pkg.FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = ((0o100600 if i == 0 else pkg.FILE_MODE) & 0xFFFF) << 16
            dst.writestr(info, payload)

    report = pkg.verify_package(rewritten)
    assert report["valid"] is False
    assert any("lexicographic order" in error for error in report["errors"])
    assert any("file mode" in error for error in report["errors"])



def test_package_builder_rejects_human_input_ledger_mismatch(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)
    (root / "human-input.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [{"description": "Unlogged extra review", "hours": 2.0}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(pkg.PackageError, match="does not match"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "bad-hours.zip",
        )


def test_package_builder_rejects_noncontiguous_columns(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["meshes"].append({"path": "column_03.tifxyz", "column": 3})
    manifest["renders"].append({"path": "column_03.tif", "column": 3})
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    with pytest.raises(pkg.PackageError, match="consecutive starting at 1"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "gapped-columns.zip",
        )


def test_package_builder_requires_exact_pinned_docker_image_in_command(
    tmp_path, monkeypatch
):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    with pytest.raises(pkg.PackageError, match="exact digest-pinned"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "wrong-image.zip",
            docker_run_command="docker run --rm ghcr.io/example/pipeline:latest",
        )


def test_package_builder_rejects_empty_reviewer_material(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)
    (root / "METHODOLOGY.md").write_text("   \n", encoding="utf-8")

    with pytest.raises(pkg.PackageError, match="non-whitespace"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "empty-method.zip",
        )



def test_package_builder_refuses_failing_legibility_ledger(tmp_path, monkeypatch):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    ledger_path = root / "legibility.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    character = ledger["columns"][0]["lines"][0]["characters"][6]
    character["status"] = "illegible"
    character.pop("reading")
    character.pop("interpolated")
    ledger_path.write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(pkg.PackageError, match="LEGIBILITY_BELOW_70_PERCENT"):
        pkg.build_package(
            manifest_path=manifest_path,
            root_dir=root,
            out_path=tmp_path / "bad-legibility.zip",
        )


def test_package_verifier_binds_legibility_validation_to_manifest_and_ledger(
    tmp_path, monkeypatch
):
    root = tmp_path / "submission"
    root.mkdir()
    manifest_path = _write_tree(root)
    monkeypatch.setattr(pkg, "validate_manifest", _passing_validation)

    archive = tmp_path / "submission.zip"
    pkg.build_package(
        manifest_path=manifest_path,
        root_dir=root,
        out_path=archive,
    )

    with zipfile.ZipFile(archive) as zf:
        index = json.loads(zf.read(pkg.INDEX_PATH))
        legibility = json.loads(zf.read(pkg.LEGIBILITY_VALIDATION_PATH))
        assert legibility["manifest_sha256"] == index["manifest_sha256"]
        assert legibility["ledger_sha256"] == index["legibility_ledger_sha256"]
        assert index["legibility_ledger_path"] == "legibility.json"
