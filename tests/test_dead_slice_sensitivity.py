import json
from pathlib import Path

from scrollq.dead_slice_sensitivity import build_report, main
from scrollq.score import SCORE_POLICY_VERSION


def test_fixed_prevalence_exposes_budget_sensitivity_without_policy_change():
    report = build_report()
    rows = report["controlled_cases"][
        "fixed_prevalence_one_slice_per_six_chunks"
    ]

    assert report["score_policy_version"] == SCORE_POLICY_VERSION
    assert report["finding"]["policy_change"] == "none"
    assert [row["decoded_chunks"] for row in rows] == [6, 12, 24, 48]
    assert [row["dead_slices"] for row in rows] == [1, 2, 4, 8]
    assert [row["dead_slice_penalty"] for row in rows] == [15, 30, 30, 30]
    assert [row["score"] for row in rows] == [75, 60, 60, 60]


def test_one_observed_slice_is_not_diluted_by_more_clean_chunks():
    rows = build_report()["controlled_cases"]["fixed_one_observed_slice"]

    assert {row["dead_slices"] for row in rows} == {1}
    assert {row["dead_slice_penalty"] for row in rows} == {15}
    assert {row["score"] for row in rows} == {75}
    assert rows[-1]["dead_slice_prevalence_per_chunk"] < rows[0][
        "dead_slice_prevalence_per_chunk"
    ]


def test_cli_writes_the_same_deterministic_report(tmp_path, monkeypatch):
    out = tmp_path / "analysis.json"
    monkeypatch.setattr("sys.argv", ["dead-slice-sensitivity", "--out", str(out)])

    main()

    assert json.loads(out.read_text(encoding="utf-8")) == build_report()


def test_committed_analysis_matches_the_executable_policy():
    artifact = (
        Path(__file__).parents[1]
        / "artifacts/2026-10-01-dead-slice-sensitivity/analysis.json"
    )

    assert json.loads(artifact.read_text(encoding="utf-8")) == build_report()
