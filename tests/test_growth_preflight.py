from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrollq.growth_preflight import (
    _exit_for,
    _parse_patch_number,
    analyze_growth,
    read_relationships,
)


def _write_rel(path: Path, edges: list[tuple[int, int]]) -> None:
    rows = [f"{a},{b},0,0,0,0,0,0,1,0,0,0,1,0" for a, b in edges]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _patches(path: Path, ids: list[int]) -> None:
    path.mkdir()
    for patch_id in ids:
        (path / f"patch_{patch_id}.bin").write_bytes(b"x")


def test_clean_growth_counts_augmented_walks(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    patch_dir = tmp_path / "patches"
    _write_rel(rel, [(1, 2), (2, 3)])
    _patches(patch_dir, [1, 2, 3])

    report = analyze_growth(rel, patch_dir=patch_dir)

    assert report["integrity"] == "pass"
    assert report["relationship_rows"] == 2
    assert report["augmented_relationship_rows"] == 4
    assert report["missing_geometry_count"] == 0
    assert report["chain_walk_states"] == {
        "2": 4,
        "3": 6,
        "4": 8,
        "5": 12,
    }
    assert report["degree"] == {"mean": pytest.approx(4 / 3), "p95": 2, "max": 2}
    assert _exit_for(report, "high") == 0


def test_missing_geometry_is_fail_closed(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    patch_dir = tmp_path / "patches"
    _write_rel(rel, [(1, 2), (2, 3)])
    _patches(patch_dir, [1, 2])

    report = analyze_growth(rel, patch_dir=patch_dir)

    assert report["integrity"] == "blocked"
    assert report["missing_geometry_ids"] == [3]
    assert report["missing_geometry_count"] == 1
    assert "BLOCK" in report["recommendation"]
    assert _exit_for(report, "none") == 2


def test_isolated_patch_is_reported_but_not_an_integrity_failure(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    patch_dir = tmp_path / "patches"
    _write_rel(rel, [(1, 2)])
    _patches(patch_dir, [1, 2, 9])

    report = analyze_growth(rel, patch_dir=patch_dir)

    assert report["integrity"] == "pass"
    assert report["isolated_patch_ids"] == [9]


def test_without_patch_dir_geometry_is_unknown(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    _write_rel(rel, [(1, 2)])

    report = analyze_growth(rel)

    assert report["geometry_check"] == "not_run"
    assert report["integrity"] == "unknown"
    assert report["patch_files"] is None


def test_float_ids_match_cpp_truncation(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    rel.write_text("1.9,2.1,0\n", encoding="utf-8")

    assert read_relationships(rel) == [(1, 2)]


def test_bad_rel_row_fails_with_line_number(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    rel.write_text("1\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r":1: expected at least two columns"):
        read_relationships(rel)


def test_patch_filename_parser_matches_upstream_digit_collection() -> None:
    assert _parse_patch_number("patch_104.bin") == 104
    assert _parse_patch_number("foo1bar2.bin") == 12
    assert _parse_patch_number("README") is None


def test_report_is_json_serializable(tmp_path: Path) -> None:
    rel = tmp_path / "rel.csv"
    _write_rel(rel, [(1, 2)])
    json.dumps(analyze_growth(rel))
