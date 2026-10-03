import pytest

from scrollq.evidence_adapters import (
    FLATCHECK_ADAPTER,
    WINDCHECK_ADAPTER,
    NativeEvidenceError,
    assess_flatcheck,
    assess_windcheck,
    normalize_native_report,
    verify_normalized_entry,
)


def _flatcheck(*, passes=True, collapsed=False, folds=0, window=False):
    return {
        "mesh": "column_01.tifxyz",
        "window": {
            "rows": "0:10" if window else None,
            "cols": None,
        },
        "results": {
            "grid": {
                "pct_quads_within_5pct": 95.0 if passes else 80.0,
                "passes_bar": passes,
                "bar_pct": 93.1,
                "fold_overs": folds,
                "collapse": {"collapsed": collapsed},
            }
        },
    }


def _windcheck(*, clean=True):
    d0 = d1 = 0 if clean else 2
    return {
        "tool": "windcheck check",
        "schema": "windcheck_check/v1",
        "report_only": True,
        "measurements": {
            "transverse_d0": d0,
            "transverse_d1": d1,
            "crossing_events": 0 if clean else 1,
        },
        "clean": clean,
        "clean_definition": (
            "CLEAN means zero transverse contacts under BOTH quad triangulations"
        ),
    }


def test_flatcheck_whole_grid_can_authorize_pass():
    result = assess_flatcheck(_flatcheck())
    assert result["claim"] == "flattening-isometry"
    assert result["status"] == "pass"
    assert result["summary"]["fold_overs"] == 0


def test_flatcheck_window_is_not_whole_mesh_evidence():
    with pytest.raises(NativeEvidenceError):
        assess_flatcheck(_flatcheck(window=True))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"passes": False},
        {"collapsed": True},
        {"folds": 1},
    ],
)
def test_flatcheck_explicit_geometry_failure_fails(kwargs):
    assert assess_flatcheck(_flatcheck(**kwargs))["status"] == "fail"


def test_windcheck_clean_requires_zero_contacts_on_both_diagonals():
    result = assess_windcheck(_windcheck(clean=True))
    assert result["claim"] == "mesh-self-intersection"
    assert result["status"] == "pass"

    result = assess_windcheck(_windcheck(clean=False))
    assert result["status"] == "fail"


def test_windcheck_inconsistent_clean_flag_is_refused():
    report = _windcheck(clean=True)
    report["measurements"]["transverse_d1"] = 1
    with pytest.raises(NativeEvidenceError):
        assess_windcheck(report)


def test_normalized_entry_is_recomputable_from_native_report():
    report = _flatcheck()
    entry = normalize_native_report(
        adapter=FLATCHECK_ADAPTER,
        report=report,
        entry_id="flat:01",
        mesh_id="mesh:column-01",
        artifact_url="https://example.org/column-01-flatcheck.json",
        sha256="a" * 64,
        path="evidence/column-01-flatcheck.json",
        producer_commit="b" * 40,
        command="flatcheck report column_01.tifxyz --json report.json",
    )
    assert verify_normalized_entry(entry, report) == []

    entry["status"] = "fail"
    assert verify_normalized_entry(entry, report)


def test_windcheck_adapter_name_is_distinct_and_supported():
    assert WINDCHECK_ADAPTER != FLATCHECK_ADAPTER
