import json

import pytest

from scrollq.hf_pin import HubPinError, main, pin_repo


class FakeResponse:
    def __init__(self, payload, *, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


def _payload():
    return {
        "sha": "a" * 40,
        "lastModified": "2026-10-03T00:00:00.000Z",
        "private": False,
        "gated": False,
        "siblings": [
            {
                "rfilename": "README.md",
                "size": 123,
                "blobId": "b" * 40,
            },
            {
                "rfilename": "model.pt",
                "size": 456,
                "blobId": "c" * 40,
                "lfs": {"sha256": "d" * 64, "size": 456},
            },
        ],
    }


def _get(payload=None):
    def fake_get(url, **kwargs):
        fake_get.url = url
        fake_get.kwargs = kwargs
        return FakeResponse(payload if payload is not None else _payload())

    return fake_get


def test_pin_resolves_revision_and_lfs_sha256():
    get = _get()
    report = pin_repo(
        repo_id="YoussefMoNader/ink-8um-v8in",
        repo_type="model",
        revision="main",
        require_files=["README.md", "model.pt"],
        require_sha256=["model.pt"],
        request_get=get,
    )

    assert report["resolved_revision"] == "a" * 40
    assert report["immutable_repo_url"].endswith("/tree/" + "a" * 40)
    assert report["summary"] == {
        "files": 2,
        "files_with_content_sha256": 1,
    }
    assert report["files"][1]["content_sha256"] == "d" * 64
    assert "/api/models/YoussefMoNader/ink-8um-v8in/revision/main" in get.url
    assert get.kwargs["params"] == {"blobs": "true"}


def test_dataset_url_and_revision_are_encoded():
    get = _get()
    report = pin_repo(
        repo_id="YoussefMoNader/ink-8um-pherc1447-surfaces",
        repo_type="dataset",
        revision="refs/pr/1",
        request_get=get,
    )

    assert "/api/datasets/" in get.url
    assert get.url.endswith("/revision/refs%2Fpr%2F1")
    assert "/datasets/YoussefMoNader/" in report["immutable_repo_url"]


def test_required_file_missing_fails_closed():
    with pytest.raises(HubPinError, match="required Hub files are missing"):
        pin_repo(
            repo_id="owner/repo",
            repo_type="model",
            require_files=["missing.ckpt"],
            request_get=_get(),
        )


def test_required_sha256_missing_fails_closed():
    with pytest.raises(HubPinError, match="lack Hub-exposed content SHA-256"):
        pin_repo(
            repo_id="owner/repo",
            repo_type="model",
            require_sha256=["README.md"],
            request_get=_get(),
        )


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"sha": "main", "siblings": []}, "40-hex"),
        ({"sha": "a" * 40}, "file inventory"),
        ({"sha": "a" * 40, "siblings": ["README.md"]}, "non-object"),
    ],
)
def test_malformed_hub_response_fails_closed(payload, match):
    with pytest.raises(HubPinError, match=match):
        pin_repo(
            repo_id="owner/repo",
            repo_type="model",
            request_get=_get(payload),
        )


def test_cli_writes_new_snapshot_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scrollq.hf_pin.requests.get",
        _get(),
    )
    out = tmp_path / "pin.json"
    args = [
        "--repo",
        "owner/repo",
        "--repo-type",
        "model",
        "--require-file",
        "model.pt",
        "--require-sha256",
        "model.pt",
        "--out",
        str(out),
    ]
    assert main(args) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["resolved_revision"] == "a" * 40

    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
