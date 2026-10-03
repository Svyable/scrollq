import pytest

from scrollq.artifact_hash import ArtifactHashError, artifact_sha256


def _mesh(root, *, z=b"z"):
    mesh = root / "column_01.tifxyz"
    mesh.mkdir()
    (mesh / "meta.json").write_bytes(b'{"format":"tifxyz"}')
    (mesh / "x.tif").write_bytes(b"x")
    (mesh / "y.tif").write_bytes(b"y")
    (mesh / "z.tif").write_bytes(z)
    return mesh


def test_directory_hash_is_stable_and_content_sensitive(tmp_path):
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    a_root.mkdir()
    b_root.mkdir()
    a = _mesh(a_root)
    b = _mesh(b_root)

    assert artifact_sha256(a) == artifact_sha256(b)

    (b / "z.tif").write_bytes(b"changed")
    assert artifact_sha256(a) != artifact_sha256(b)


def test_file_hash_remains_ordinary_sha256(tmp_path):
    import hashlib

    p = tmp_path / "render.tif"
    p.write_bytes(b"render")
    assert artifact_sha256(p) == hashlib.sha256(b"render").hexdigest()


def test_directory_hash_refuses_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    mesh = _mesh(root)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (mesh / "link.bin").symlink_to(outside)

    with pytest.raises(ArtifactHashError):
        artifact_sha256(mesh)
