"""One volume raising must not discard the rest of a scoring campaign."""

import json
import sys

import scrollq.cli as cli


def _run(monkeypatch, tmp_path, roots, fake_score):
    vols = tmp_path / "volumes.txt"
    vols.write_text("\n".join(roots) + "\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(cli, "score_volume", fake_score)
    monkeypatch.setattr(sys, "argv", [
        "scrollq-score", "--volumes", str(vols), "--out-dir", str(out_dir),
        "--workers", "2",
    ])
    cli.main()
    return json.loads((out_dir / "volumes.json").read_text(encoding="utf-8"))


def test_unhandled_exception_becomes_a_failed_record(monkeypatch, tmp_path):
    def fake_score(base, root, samples=4, rotate=0, spread=3):
        if root == "bad":
            raise RuntimeError("boom")
        return {"root": root, "ok": True, "score": 50.0}

    results = _run(monkeypatch, tmp_path, ["a", "bad", "c"], fake_score)

    by_root = {r["root"]: r for r in results}
    assert set(by_root) == {"a", "bad", "c"}
    assert by_root["a"]["ok"] and by_root["c"]["ok"]
    assert by_root["bad"]["ok"] is False
    assert "RuntimeError" in by_root["bad"]["error"]
    assert "boom" in by_root["bad"]["error"]


def test_failed_record_sorts_after_scored_volumes(monkeypatch, tmp_path):
    def fake_score(base, root, samples=4, rotate=0, spread=3):
        if root == "bad":
            raise ValueError("x")
        return {"root": root, "ok": True, "score": 10.0}

    results = _run(monkeypatch, tmp_path, ["bad", "a"], fake_score)
    assert [r["root"] for r in results] == ["a", "bad"]
