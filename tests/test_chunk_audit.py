import json
import urllib.parse

import pytest

from scrollq import chunk_audit as ca

BUCKET = "https://bucket.test"
NS = "http://s3.amazonaws.com/doc/2006-03-01/"


class FakeS3:
    """ListObjectsV2 + GET with the response shape the real bucket returns."""

    def __init__(self, objects, unavailable=()):
        self.objects = dict(objects)  # key -> bytes (metadata) or int (size)
        self.list_calls = 0
        self.unavailable = tuple(unavailable)  # URL substrings that error

    def fetch(self, url):
        if any(sub in url for sub in self.unavailable):
            raise OSError(f"{url}: simulated outage")
        if "/?" in url:
            return self._list(dict(urllib.parse.parse_qsl(url.split("/?")[1])))
        key = url[len(BUCKET) + 1:]
        v = self.objects.get(key)
        return v if isinstance(v, bytes) else (b"" if v is not None else None)

    def _list(self, q):
        self.list_calls += 1
        keys = sorted(k for k in self.objects if k.startswith(q["prefix"]))
        after = q.get("start-after")
        if q.get("continuation-token"):
            after = q["continuation-token"][4:]
        if after:
            keys = [k for k in keys if k > after]
        page, rest = keys[:int(q["max-keys"])], keys[int(q["max-keys"]):]
        body = "".join(
            f"<Contents><Key>{k}</Key><LastModified>2026-03-04T12:36:07.000Z"
            f"</LastModified><ETag>&quot;abc&quot;</ETag>"
            f"<ChecksumAlgorithm>CRC32C</ChecksumAlgorithm>"
            f"<ChecksumType>FULL_OBJECT</ChecksumType>"
            f"<Size>{self._size(k)}</Size>"
            f"<StorageClass>INTELLIGENT_TIERING</StorageClass></Contents>"
            for k in page)
        tok = (f"<NextContinuationToken>tok:{page[-1]}</NextContinuationToken>"
               if rest and page else "")
        return (f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult '
                f'xmlns="{NS}"><Name>b</Name><KeyCount>{len(page)}</KeyCount>'
                f"<IsTruncated>{'true' if rest else 'false'}</IsTruncated>"
                f"{body}{tok}</ListBucketResult>").encode()

    def _size(self, k):
        v = self.objects[k]
        return len(v) if isinstance(v, bytes) else v


def volume(path="S/volumes/V.zarr/", grid=(4, 4, 4), chunk=8, levels=1,
           corrupt=None, compressor=None):
    """A fake uncompressed volume; ``corrupt`` maps chunk index -> size."""
    objs = {f"{path}.zattrs": json.dumps({"multiscales": [{"datasets": [
        {"path": str(i)} for i in range(levels)]}]}).encode()}
    for lv in range(levels):
        objs[f"{path}{lv}/.zarray"] = json.dumps({
            "shape": [g * chunk for g in grid], "chunks": [chunk] * 3,
            "dtype": "|u1", "compressor": compressor, "filters": None,
            "zarr_format": 2}).encode()
        for z in range(grid[0]):
            for y in range(grid[1]):
                for x in range(grid[2]):
                    objs[f"{path}{lv}/{z}/{y}/{x}"] = chunk**3
    for (lv, z, y, x), size in (corrupt or {}).items():
        objs[f"{path}{lv}/{z}/{y}/{x}"] = size
    return objs


def audit(objs, **kw):
    s3 = FakeS3(objs)
    return ca.audit_volume(s3.fetch, BUCKET, "S/volumes/V.zarr/", **kw), s3


def test_parse_listing_handles_real_response_shape_and_token():
    s3 = FakeS3(volume())
    entries, token = ca.parse_listing(
        s3._list({"prefix": "S/volumes/V.zarr/0/", "max-keys": "3"}))
    assert [k for k, _ in entries][0].endswith("/0/.zarray")
    assert entries[1][1] == 512 and token == f"tok:{entries[-1][0]}"
    _, none = ca.parse_listing(s3._list(
        {"prefix": "S/volumes/V.zarr/0/", "max-keys": "5000"}))
    assert none is None


def test_classify_level_statuses():
    ok = [("p/0/0/0/0", 512), ("p/0/0/0/1", 512), ("p/0/.zarray", 238)]
    assert ca.classify_level([8] * 3, "|u1", None, None, ok)["status"] == "ok"
    bad = ok + [("p/0/9/9/9", 4096)]
    r = ca.classify_level([8] * 3, "|u1", None, None, bad)
    assert r["status"] == "mismatch" and r["n_mismatch"] == 1
    assert r["examples"][0]["ratio_to_expected"] == 8.0
    # zero checked objects can never be "ok"
    r = ca.classify_level([8] * 3, "|u1", None, None, [("p/0/.zarray", 238)])
    assert r["status"] == "unverified"
    assert ca.classify_level([8] * 3, "|u1", {"id": "blosc"}, None,
                             ok)["status"] == "not_applicable"
    assert ca.classify_level([8] * 3, "|zz", None, None,
                             ok)["status"] == "not_applicable"


def test_clean_volume_passes_and_corruption_is_counted_exactly_in_full_mode():
    clean, _ = audit(volume(), full=True)
    assert clean["levels"][0]["status"] == "ok"
    assert clean["levels"][0]["n_checked"] == 64
    bad, _ = audit(volume(corrupt={(0, 1, 2, 3): 4096, (0, 3, 3, 3): 32768}),
                   full=True)
    lv = bad["levels"][0]
    assert lv["status"] == "mismatch" and lv["n_mismatch"] == 2
    assert lv["size_histogram"] == {"512": 62, "4096": 1, "32768": 1}


def test_observed_size_mix_signature_is_flagged():
    # PHerc0343P 8.64um L0: declared 128^3 (2 MiB); stored mostly 2 MiB with
    # 256^3 and 512^3 objects mixed in
    objs = volume(chunk=128, grid=(2, 2, 2), corrupt={
        (0, 0, 0, 1): 256**3, (0, 1, 1, 1): 512**3})
    rep, _ = audit(objs, full=True)
    lv = rep["levels"][0]
    assert lv["expected_bytes"] == 2097152 and lv["status"] == "mismatch"
    assert lv["size_histogram"] == {"2097152": 6, "16777216": 1,
                                    "134217728": 1}


def test_level_with_no_chunks_is_unverified_never_ok():
    objs = volume()
    for k in [k for k in objs if "/0/" in k and not k.endswith(".zarray")
              and not k.endswith(".zattrs")]:
        del objs[k]
    rep, _ = audit(objs, full=True)
    assert rep["levels"][0]["status"] == "unverified"


def test_missing_metadata_and_compressed_levels_are_reported():
    rep, _ = audit({})
    assert rep["error"] == ".zattrs not found"
    rep, _ = audit(volume(compressor={"id": "blosc"}), full=True)
    assert rep["levels"][0]["status"] == "not_applicable"


def test_sampling_reaches_beyond_the_first_page_where_head_only_misses():
    # mismatch confined to the last z-slab; a head-only listing cannot see it
    objs = volume(grid=(8, 4, 4),
                  corrupt={(0, 7, y, x): 4096 for y in range(4)
                           for x in range(4)})
    s3 = FakeS3(objs)
    prefix = "S/volumes/V.zarr/0/"
    head, _ = ca.collect_entries(s3.fetch, BUCKET, prefix, 8, head_pages=1,
                                 random_pages=0, page_keys=20)
    assert not any(s == 4096 for _, s in head)
    sampled, pages = ca.collect_entries(s3.fetch, BUCKET, prefix, 8,
                                        head_pages=1, random_pages=8,
                                        page_keys=40, seed=1)
    assert any(s == 4096 for _, s in sampled) and pages > 1


def test_full_mode_follows_pagination_to_the_end():
    s3 = FakeS3(volume())
    entries, pages = ca.collect_entries(s3.fetch, BUCKET, "S/volumes/V.zarr/0/",
                                        4, full=True, page_keys=10)
    assert len([e for e in entries if not e[0].endswith(".zarray")]) == 64
    assert pages >= 7


def test_summarize_and_cli_exit_codes(tmp_path, monkeypatch):
    index = {"samples": {"S": {"volumes": {"V": {
        "properties": {"pixel_size_um": 8.64},
        "data": [{"type": "ome-zarr", "origins": [{
            "path": "S/volumes/V.zarr/",
            "access_roots": [{"url": ca.BUCKET_S3}]}]}]}}}}}
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps(index))

    def run(objs):
        s3 = FakeS3(objs)
        monkeypatch.setattr(ca, "default_fetch", lambda: s3.fetch)
        out = tmp_path / "o.json"
        rc = ca.main(["--index", str(idx), "--bucket-url", BUCKET, "--full",
                      "--workers", "1", "--out", str(out)])
        return rc, json.loads(out.read_text())

    rc, rep = run(volume())
    assert rc == 0 and rep["summary"]["levels_by_status"] == {"ok": 1}
    rc, rep = run(volume(corrupt={(0, 0, 0, 0): 4096}))
    assert rc == 1
    assert rep["summary"]["volumes_with_mismatch"] == ["S:V"]
    rc, _ = run({})  # nothing readable must not look like success
    assert rc == 1


# -- absent is not unavailable --------------------------------------------------
def audit_with(objs, unavailable=(), **kw):
    s3 = FakeS3(objs, unavailable)
    return ca.audit_volume(s3.fetch, BUCKET, "S/volumes/V.zarr/", **kw)


def test_unavailable_zattrs_is_unknown_not_missing():
    rep = audit_with(volume(), unavailable=[".zattrs"], full=True)
    assert rep["error"].startswith(".zattrs unavailable:")
    assert "not found" not in rep["error"] and rep["levels"] == []
    assert ca.audit_volume(FakeS3({}).fetch, BUCKET, "S/volumes/V.zarr/"
                           )["error"] == ".zattrs not found"


def test_unavailable_zarray_leaves_level_unverified():
    rep = audit_with(volume(levels=2), unavailable=["/1/.zarray"], full=True)
    lv0, lv1 = rep["levels"]
    assert lv0["status"] == "ok"
    assert lv1["status"] == "unverified" and "unavailable" in lv1["detail"]


def test_listing_outage_is_unverified_not_ok_and_not_a_mismatch():
    rep = audit_with(volume(), unavailable=["list-type"], full=True)
    lv = rep["levels"][0]
    assert lv["status"] == "unverified" and "unavailable" in lv["detail"]
    assert "n_mismatch" not in lv


def test_malformed_zarray_is_recorded_not_fatal():
    objs = volume(levels=2)
    objs["S/volumes/V.zarr/1/.zarray"] = b"{not json"
    rep = audit_with(objs, full=True)
    assert rep["levels"][0]["status"] == "ok"
    assert rep["levels"][1]["status"] == "unverified"
    assert "unusable .zarray" in rep["levels"][1]["detail"]
    objs["S/volumes/V.zarr/1/.zarray"] = json.dumps({"shape": [8]}).encode()
    assert audit_with(objs, full=True)["levels"][1]["status"] == "unverified"


def test_default_fetch_distinguishes_404_from_failure(monkeypatch):
    import requests

    class R:
        def __init__(self, code, content=b""):
            self.status_code, self.content = code, content

    script = {"ok": [R(200, b"x")], "gone": [R(404)],
              "flaky": [R(503), R(503), R(503)], "boom": [RuntimeError("x")] * 3,
              "forbidden": [R(403)] * 3}

    class S:
        def get(self, url, timeout):
            item = script[url.rsplit("/", 1)[-1]].pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(requests, "Session", S)
    fetch = ca.default_fetch()
    assert fetch("https://h/ok") == b"x"
    assert fetch("https://h/gone") is None
    for name in ("flaky", "boom", "forbidden"):
        with pytest.raises(OSError):
            fetch(f"https://h/{name}")


def test_cli_contains_a_failing_volume_and_exits_nonzero(tmp_path, monkeypatch):
    index = {"samples": {"S": {"volumes": {"V": {
        "properties": {"pixel_size_um": 8.64},
        "data": [{"type": "ome-zarr", "origins": [{
            "path": "S/volumes/V.zarr/",
            "access_roots": [{"url": ca.BUCKET_S3}]}]}]}}}}}
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps(index))
    s3 = FakeS3(volume(), unavailable=["list-type"])
    monkeypatch.setattr(ca, "default_fetch", lambda: s3.fetch)
    out = tmp_path / "o.json"
    rc = ca.main(["--index", str(idx), "--bucket-url", BUCKET, "--full",
                  "--workers", "1", "--out", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 1
    assert rep["summary"]["levels_by_status"] == {"unverified": 1}
    assert rep["summary"]["volumes_unavailable"] == ["S:V"]
    assert rep["summary"]["volumes_with_mismatch"] == []
