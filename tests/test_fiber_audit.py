import hashlib
import json

import pytest

from scrollq.fiber_audit import audit_csv, audit_rows, main


def _trace(tid, pts):
    return [{"trace_id": tid, "x": x, "y": y, "z": z} for x, y, z in pts]


STRAIGHT = [(i, 0, 0) for i in range(6)]


def test_straight_evenly_spaced_trace_passes():
    out = audit_rows(_trace("a", STRAIGHT))
    assert out["status"] == "pass"
    assert out["findings"] == []
    assert out["counts"]["valid_traces"] == 1
    assert out["total_trace_length"] == pytest.approx(5.0)


def test_gap_is_relative_to_the_trace_median_step():
    pts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (8, 0, 0)]
    out = audit_rows(_trace("a", pts))
    gaps = [f for f in out["findings"] if f["kind"] == "gap"]
    assert out["status"] == "caution"
    assert gaps == [{"trace_id": "a", "kind": "gap", "segment": 3, "ratio": 5.0}]
    # Exactly at the factor is not a gap.
    pts[-1] = (7, 0, 0)
    assert audit_rows(_trace("a", pts))["counts"]["gaps"] == 0


def test_sharp_turn_is_flagged_at_its_vertex():
    pts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0), (2, 2, 0)]
    out = audit_rows(_trace("a", pts))
    turns = [f for f in out["findings"] if f["kind"] == "sharp_turn"]
    assert len(turns) == 1
    assert turns[0]["vertex"] == 2
    assert turns[0]["degrees"] == pytest.approx(90.0)
    # A gentle bend under the threshold is not flagged.
    gentle = [(0, 0, 0), (1, 0, 0), (2, 0.5, 0)]
    assert audit_rows(_trace("b", gentle))["counts"]["sharp_turns"] == 0


def test_repeated_points_do_not_create_spurious_turns():
    pts = [(0, 0, 0), (1, 0, 0), (1, 0, 0), (2, 0, 0)]
    out = audit_rows(_trace("a", pts))
    assert out["counts"]["sharp_turns"] == 0


def test_single_point_trace_is_short_not_silently_dropped():
    out = audit_rows(_trace("lonely", [(0, 0, 0)]) + _trace("a", STRAIGHT))
    assert out["status"] == "caution"
    assert {"trace_id": "lonely", "kind": "short_trace", "points": 1} in out["findings"]


def test_parse_errors_fail_with_csv_row_numbers():
    rows = _trace("a", STRAIGHT)
    rows.append({"trace_id": "a", "x": "nan", "y": 0, "z": 0})
    rows.append({"trace_id": "a", "x": 1, "y": 0})
    out = audit_rows(rows)
    assert out["status"] == "fail"
    assert [e["row"] for e in out["errors"]] == [8, 9]
    assert out["counts"]["parse_errors"] == 2


def test_traces_are_independent():
    out = audit_rows(_trace("a", STRAIGHT) + _trace("b", [(0, 5, 0), (0, 6, 0)]))
    assert out["status"] == "pass"
    assert out["counts"]["valid_traces"] == 2


def test_csv_input_is_hashed_and_cli_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.csv"
    good.write_text("trace_id,x,y,z\n" + "".join(f"a,{i},0,0\n" for i in range(4)))
    out = audit_csv(good)
    assert out["input"]["sha256"] == hashlib.sha256(good.read_bytes()).hexdigest()

    with pytest.raises(SystemExit) as ok:
        main([str(good), "--out", str(tmp_path / "r.json")])
    assert ok.value.code == 0
    assert json.loads((tmp_path / "r.json").read_text())["status"] == "pass"

    bad = tmp_path / "bad.csv"
    bad.write_text("trace_id,x,y,z\na,zero,0,0\n")
    with pytest.raises(SystemExit) as fail:
        main([str(bad)])
    assert fail.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "fail"
