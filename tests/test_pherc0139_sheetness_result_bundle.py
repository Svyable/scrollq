from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = ROOT / "artifacts" / "2026-10-03-pherc0139-sheetness-run"
PLAN = ROOT / "artifacts" / "2026-10-03-pherc0139-sheetness-campaign" / "campaign-plan.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_pherc0139_phase_a_bundle_hash_census_is_exact():
    manifest = RESULT_ROOT / "hashes.sha256"
    assert manifest.is_file()

    declared: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, sep, rel = line.partition("  ")
        assert sep == "  "
        assert len(digest) == 64
        int(digest, 16)
        path = Path(rel)
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert rel not in declared
        declared[rel] = digest

    actual_paths = {
        path.relative_to(RESULT_ROOT).as_posix()
        for path in RESULT_ROOT.rglob("*")
        if path.is_file() and path.name != "hashes.sha256"
    }
    assert set(declared) == actual_paths

    for rel, expected in declared.items():
        assert _sha256(RESULT_ROOT / rel) == expected, rel


def test_pherc0139_phase_a_result_is_complete_and_bound_to_frozen_plan():
    result = json.loads((RESULT_ROOT / "sheetness-result.json").read_text(encoding="utf-8"))

    assert result["schema"] == "scroliq-sheetness-campaign-result/1"
    assert result["status"] in {"pass", "fail"}
    assert result["metrics"]["group_count"] == 32
    assert result["metrics"]["score_complete_count"] == 32
    assert result["metrics"]["normal_complete_count"] == 32
    assert result["metrics"]["failed_group_count"] == 0
    assert result["failures"] == []

    assert result["campaign_plan"]["file_sha256"] == _sha256(PLAN)
    checks = result["decision_checks"]
    assert result["status"] == ("pass" if all(checks.values()) else "fail")

    groups = result["groups"]
    assert len(groups) == 32
    assert len({row["id"] for row in groups}) == 32
    assert all(row["status"] == "measured" for row in groups)


def test_pherc0139_phase_a_negative_result_is_preserved_not_retuned():
    result = json.loads((RESULT_ROOT / "sheetness-result.json").read_text(encoding="utf-8"))

    # This is a frozen observation, not a desired CI outcome. CI must preserve
    # and validate a scientific FAIL rather than redefine thresholds until PASS.
    assert result["status"] == "fail"
    assert result["decision_checks"]["normal_offset_win_fraction"] is False
    assert result["decision_checks"]["median_normal_offset_margin"] is False
