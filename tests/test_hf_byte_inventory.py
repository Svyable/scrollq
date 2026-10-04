import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hf_byte_inventory.py"
spec = importlib.util.spec_from_file_location("hf_byte_inventory", SCRIPT)
inv = importlib.util.module_from_spec(spec)
sys.modules["hf_byte_inventory"] = inv
spec.loader.exec_module(inv)

REV = "a" * 40


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_pin(files, *, repo_type="dataset", repo_id="owner/name", **extra):
    pin = {
        "schema_version": 1,
        "repo_type": repo_type,
        "repo_id": repo_id,
        "resolved_revision": REV,
        "immutable_repo_url": f"https://huggingface.co/{repo_id}/tree/{REV}",
        "private": False,
        "gated": False,
        "files": files,
    }
    pin.update(extra)
    return pin


def row(path, data, *, hub=True, size="auto"):
    return {
        "path": path,
        "size": len(data) if size == "auto" else size,
        "git_blob_id": None,
        "content_sha256": sha(data) if hub else None,
    }


class Store:
    """Injected fetcher serving bytes in several chunks and recording URLs."""

    def __init__(self, blobs):
        self.blobs = blobs
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        data = self.blobs[url]
        step = max(1, len(data) // 3)
        for i in range(0, len(data), step):
            yield data[i : i + step]


def test_hashes_streamed_bytes_and_verifies_hub_sha():
    a, b = b"alpha-bytes" * 5, b"beta" * 7
    pin = make_pin([row("b/two.bin", b), row("a.txt", a, hub=False)])
    store = Store(
        {
            inv.resolve_url(pin, "a.txt"): a,
            inv.resolve_url(pin, "b/two.bin"): b,
        }
    )

    repo = inv.inventory_repo(pin, fetch=store)

    assert repo["status"] == "hashed"
    assert [f["path"] for f in repo["files"]] == ["a.txt", "b/two.bin"]
    by_path = {f["path"]: f for f in repo["files"]}
    assert by_path["a.txt"]["sha256"] == sha(a)
    assert by_path["a.txt"]["hub_sha256_verified"] is False
    assert by_path["b/two.bin"]["sha256"] == sha(b)
    assert by_path["b/two.bin"]["hub_sha256_verified"] is True
    assert repo["total_bytes"] == len(a) + len(b)
    assert repo["inventory_sha256"] == inv._inventory_digest(repo["files"])


def test_inventory_digest_is_deterministic_and_content_sensitive():
    a = b"payload-one"
    pin = make_pin([row("a.bin", a)])
    url = inv.resolve_url(pin, "a.bin")
    first = inv.inventory_repo(pin, fetch=Store({url: a}))
    again = inv.inventory_repo(pin, fetch=Store({url: a}))
    assert first == again

    other = make_pin([row("a.bin", a, hub=False)])
    changed = inv.inventory_repo(other, fetch=Store({url: b"payload-two"}).__call__)
    assert changed["inventory_sha256"] != first["inventory_sha256"]


def test_resolve_url_uses_resolved_sha_and_repo_kind_and_encodes_path():
    ds = make_pin([row("x", b"x")], repo_type="dataset", repo_id="o/d")
    md = make_pin([row("x", b"x")], repo_type="model", repo_id="o/m")
    assert inv.resolve_url(ds, "w 1/p#.png") == (
        f"https://huggingface.co/datasets/o/d/resolve/{REV}/w%201/p%23.png"
    )
    assert inv.resolve_url(md, "ckpt.pt") == (
        f"https://huggingface.co/o/m/resolve/{REV}/ckpt.pt"
    )


def test_hub_sha_mismatch_fails_closed():
    good = b"expected-bytes"
    pin = make_pin([row("m.pt", good)])
    store = Store({inv.resolve_url(pin, "m.pt"): b"tampered-bytes"})
    store.blobs[inv.resolve_url(pin, "m.pt")] = b"x" * len(good)  # same size

    with pytest.raises(inv.InventoryError, match="differs from Hub-exposed"):
        inv.inventory_repo(pin, fetch=store)


def test_size_mismatch_from_truncated_download_fails_closed():
    data = b"0123456789"
    pin = make_pin([row("a.bin", data, hub=False)])
    store = Store({inv.resolve_url(pin, "a.bin"): data[:6]})

    with pytest.raises(inv.InventoryError, match="read 6 bytes, pin recorded 10"):
        inv.inventory_repo(pin, fetch=store)


def test_unknown_size_cannot_be_guarded_and_fails_closed():
    pin = make_pin([row("a.bin", b"abc", hub=False, size=None)])
    with pytest.raises(inv.InventoryError, match="no known size"):
        inv.inventory_repo(pin, fetch=Store({}))


def test_guard_blocks_without_downloading_anything():
    pin = make_pin([row("big.bin", b"z" * 50, hub=False)])

    def must_not_fetch(url):
        raise AssertionError("guarded repo must not be downloaded")

    repo = inv.inventory_repo(pin, fetch=must_not_fetch, max_repo_bytes=10)

    assert repo["status"] == "blocked_exceeds_guard"
    assert repo["total_bytes"] == 50
    assert repo["inventory_sha256"] is None
    assert repo["files"][0]["sha256"] is None


def test_policy_skip_records_pinned_metadata_only():
    data = b"corpus-shard"
    pin = make_pin([row("shard.tar", data)])

    def must_not_fetch(url):
        raise AssertionError("skipped repo must not be downloaded")

    repo = inv.inventory_repo(pin, fetch=must_not_fetch, skip_download=True)

    assert repo["status"] == "skipped_by_policy"
    assert repo["files"][0]["hub_content_sha256"] == sha(data)
    assert repo["files"][0]["sha256"] is None
    assert repo["files"][0]["hub_sha256_verified"] is False


def test_transient_network_error_is_retried_then_succeeds():
    data = b"flaky-file"
    pin = make_pin([row("f.bin", data)])
    url = inv.resolve_url(pin, "f.bin")
    calls = {"n": 0}
    sleeps = []

    def flaky(u):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("reset")
        yield data

    repo = inv.inventory_repo(pin, fetch=flaky, sleep=sleeps.append)

    assert repo["files"][0]["sha256"] == sha(data)
    assert calls["n"] == 2 and sleeps == [2.0]
    assert url.endswith("/f.bin")


def test_persistent_network_error_surfaces_after_retries():
    pin = make_pin([row("f.bin", b"abc")])

    def down(u):
        raise requests.ConnectionError("down")
        yield b""  # pragma: no cover

    with pytest.raises(inv.InventoryError, match="cannot read"):
        inv.inventory_repo(pin, fetch=down, retries=2, sleep=lambda s: None)


def test_load_pin_rejects_private_gated_unresolved_and_empty(tmp_path):
    def write(pin):
        path = tmp_path / "pin.json"
        path.write_text(json.dumps(pin))
        return path

    ok = make_pin([row("a", b"a")])
    pin, digest = inv.load_pin(write(ok))
    assert pin["repo_id"] == "owner/name" and len(digest) == 64

    for mutate, message in (
        ({"private": True}, "not marked public"),
        ({"gated": "auto"}, "gated"),
        ({"resolved_revision": "main"}, "40-hex"),
        ({"files": []}, "no file inventory"),
        ({"repo_type": "space"}, "repo_type"),
    ):
        with pytest.raises(inv.InventoryError, match=message):
            inv.load_pin(write({**ok, **mutate}))

    bad = make_pin([{"path": "a", "size": 1, "content_sha256": "nothex"}])
    with pytest.raises(inv.InventoryError, match="malformed"):
        inv.load_pin(write(bad))
    dup = make_pin([row("a", b"a"), row("a", b"a")])
    with pytest.raises(inv.InventoryError, match="duplicate"):
        inv.load_pin(write(dup))


def test_build_inventory_orders_repos_binds_pin_files_and_summarizes():
    a, m = b"label-bytes", b"model-bytes"
    surf = make_pin([row("l.png", a)], repo_id="o/surfaces")
    model = make_pin([row("m.pt", m)], repo_type="model", repo_id="o/model")
    corpus = make_pin([row("s.tar", b"big")], repo_id="o/corpus")
    store = Store(
        {
            inv.resolve_url(surf, "l.png"): a,
            inv.resolve_url(model, "m.pt"): m,
        }
    )

    report = inv.build_inventory(
        [
            ("pins/surfaces.json", surf, "1" * 64),
            ("pins/model.json", model, "2" * 64),
            ("pins/corpus.json", corpus, "3" * 64),
        ],
        fetch=store,
        skip_download=["o/corpus"],
    )

    assert [r["repo_id"] for r in report["repos"]] == [
        "o/corpus",
        "o/model",
        "o/surfaces",
    ]
    assert report["repos"][1]["pin_file"] == "model.json"
    assert report["repos"][1]["pin_file_sha256"] == "2" * 64
    assert report["summary"] == {
        "repos": 3,
        "hashed": 2,
        "skipped_by_policy": 1,
        "blocked_exceeds_guard": 0,
        "files_hashed": 2,
        "bytes_hashed": len(a) + len(m),
    }
    assert json.dumps(report, sort_keys=True, allow_nan=False)


def test_build_inventory_rejects_duplicates_and_unknown_skips():
    pin = make_pin([row("a", b"a")])
    with pytest.raises(inv.InventoryError, match="more than once"):
        inv.build_inventory([("p1", pin, "0" * 64), ("p2", pin, "0" * 64)], fetch=Store({}))
    with pytest.raises(inv.InventoryError, match="unpinned"):
        inv.build_inventory(
            [("p1", pin, "0" * 64)], fetch=Store({}), skip_download=["x/y"]
        )


def test_cli_is_create_only_and_reports_invalid_pins(tmp_path, capsys):
    out = tmp_path / "inventory.json"
    out.write_text("{}")
    with pytest.raises(SystemExit) as refusal:
        inv.main(["--pin", str(tmp_path / "p.json"), "--out", str(out)])
    assert refusal.value.code == 2
    assert out.read_text() == "{}"

    missing = tmp_path / "new.json"
    rc = inv.main(["--pin", str(tmp_path / "absent.json"), "--out", str(missing)])
    assert rc == 2
    assert not missing.exists()
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "invalid"
