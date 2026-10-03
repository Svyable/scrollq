import json
import shutil
import zipfile

import pytest

import scrollq.submission_package as pkg


def _package_manifest():
    return {
        "schema_version": 6,
        "submission": {
            "human_input_hours": 1.5,
        },
        "code": {
            "docker_image": "ghcr.io/example/pipeline@sha256:" + "b" * 64,
        },
        "ct_volume": {
            "zarr_audit": {
                "path": "evidence/zpa-report.json",
            }
        },
        "surfaces": [],
        "meshes": [{"path": "column_01.tifxyz", "column": 1}],
        "renders": [{"path": "column_01.tif", "column": 1, "scale_proof": {"path": "evidence/column_01.scale.json"}}],
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
    (root / "evidence" / "column_01.scale.json").write_bytes(b"scale-proof")
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
        "validator_schema_version": 6,
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
        assert pkg.INDEX_PATH in names
        assert "METHODOLOGY.md" in names
        assert "SYSTEM_REQUIREMENTS.md" in names
        assert "human-input.json" in names
        assert "VC3D_WORKFLOW.md" in names
        assert "FALSE_POSITIVES.md" in names
        reviewer = json.loads(zf.read(pkg.REVIEWER_CONTRACT_PATH))
        assert reviewer["columns"]["meshes"] == [1]
        assert reviewer["columns"]["renders"] == [1]
        assert reviewer["human_input"]["ledger_hours"] == 1.5
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
