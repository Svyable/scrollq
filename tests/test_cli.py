import json
import sys

import pytest

import scrollq.cli as cli


@pytest.mark.parametrize("extra, expected_rotate", [([], 0), (["--rotate", "9"], 9)])
def test_scrollq_score_forwards_rotate_and_spread(monkeypatch, tmp_path, extra, expected_rotate):
    calls = []

    def fake_score(base, root, samples=4, rotate=0, spread=3):
        calls.append((root, samples, rotate, spread))
        return {"root": root, "ok": True, "score": 50.0}

    volumes = tmp_path / "volumes.txt"
    volumes.write_text("root/a\nroot/b\n")
    monkeypatch.setattr(cli, "score_volume", fake_score)
    monkeypatch.setattr(
        sys, "argv",
        ["scrollq-score", "--volumes", str(volumes), "--samples", "2",
         "--spread", "5", "--workers", "1", "--out-dir", str(tmp_path / "out"),
         *extra],
    )

    cli.main()

    assert calls == [("root/a", 2, expected_rotate, 5),
                     ("root/b", 2, expected_rotate, 5)]
    assert len(json.loads((tmp_path / "out" / "volumes.json").read_text())) == 2
