"""Leaderboard rank bands (stability v2 consequence) and drift guards."""

import json
import sys
from pathlib import Path

from scrollq import leaderboard

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "artifacts" / "2026-10-stability-v2"


def _vol(root, score):
    return {"root": root, "ok": True, "score": score, "score_std": 5.0, "score_min": 1, "score_max": 2,
            "components": {"signal_40": 30, "texture_30": 20, "dynamic_20": 15, "pen_sat": 0, "pen_dead": 0},
            "metrics": {"nonzero_frac": 0.9, "grad_energy": 8.0, "dyn_range": 150, "dead_slices": 0, "chunks_decoded": 24},
            "sampling": {"requested": 24, "decoded": 24}}


def _render(tmp_path, bands=None, monkeypatch=None):
    roots = [f"community-uploads/x/volcomp/PHerc000{i}/volumes/2025-9.0um-1m-100keV-masked.zarr" for i in range(3)]
    vols = tmp_path / "v.json"
    vols.write_text(json.dumps([_vol(r, 70 - i) for i, r in enumerate(roots)]))
    cmd = ["scrollq-leaderboard", "--in", str(vols), "--out", str(tmp_path / "i.html")]
    if bands is not None:
        data = {"decision": {"verdict": "FAIL", "rho": 0.75, "gate_rho": 0.85},
                "rank_bands": {roots[0]: {"best": 1, "worst": 2}, roots[1]: {"best": 2, "worst": 2}},
                "pooled_scores": {roots[0]: 68.0, roots[1]: 69.0}}
        (tmp_path / "b.json").write_text(json.dumps(data))
        cmd += ["--rank-bands", str(tmp_path / "b.json")]
    old = sys.argv
    sys.argv = cmd
    try:
        leaderboard.main()
    finally:
        sys.argv = old
    return (tmp_path / "i.html").read_text(encoding="utf-8"), roots


def test_without_bands_the_rank_column_is_a_view_counter(tmp_path):
    page, _ = _render(tmp_path)
    assert '<th data-k="rank">#</th>' in page
    assert "const BANDS = false;" in page
    assert "Ranks are bands" not in page


def test_with_bands_each_volume_shows_its_band_or_a_dash(tmp_path):
    page, _ = _render(tmp_path, bands=True)
    assert ">rank band</th>" in page and "const BANDS = true;" in page
    assert 'data-band="1–2"' in page and 'data-band="2"' in page
    assert "not ranked\">—</td>" in page
    assert "Ranks are bands." in page and "FAIL" in page
    assert "by 1.0 points on average" in page  # mean of |68-70| and |69-69|


def test_committed_page_reflects_the_committed_verdict():
    summary = json.loads((V2 / "summary.json").read_text())
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert f"returned <b>{summary['decision']['verdict']}</b>" in page
    assert f"ρ = {summary['decision']['rho']:.3f}" in page
    bands = json.loads((V2 / "stability-v2.json").read_text())["rank_bands"]
    assert page.count('title="best–worst rank of') == len(bands)
