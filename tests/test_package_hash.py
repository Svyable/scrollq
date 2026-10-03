import hashlib

import pytest

from scrollq.package_hash import sha256_path


def test_file_hash_matches_standard_sha256(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"scroll")
    assert sha256_path(path) == hashlib.sha256(b"scroll").hexdigest()


def test_directory_hash_is_order_independent_and_content_sensitive(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    (first / "meta.json").write_bytes(b"{}")
    (first / "x.tif").write_bytes(b"x")
    (second / "x.tif").write_bytes(b"x")
    (second / "meta.json").write_bytes(b"{}")

    assert sha256_path(first) == sha256_path(second)

    (second / "x.tif").write_bytes(b"changed")
    assert sha256_path(first) != sha256_path(second)


def test_directory_hash_rejects_symlinks(tmp_path):
    root = tmp_path / "mesh.tifxyz"
    root.mkdir()
    target = tmp_path / "real.tif"
    target.write_bytes(b"x")
    link = root / "x.tif"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(ValueError, match="symlinks"):
        sha256_path(root)
