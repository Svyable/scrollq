import json
import shutil
import zipfile

import pytest

import scrollq.submission_package as pkg


def _package_manifest():
    return {
        "schema_version": 6,
        "ct_volume": {
            "zarr_audit": {
                "path": "evidence/zpa-report.json",
            }
        },
        "surfaces": [],
        "meshes": [{"path": "column_01.tifxyz"}],
        "renders": [{"path": "column_01.tif", "scale_proof": {"path": "evidence/column_01.scale.json"}}],
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
        assert pkg.INDEX_PATH in names


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
