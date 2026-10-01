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



def _vc3d_config():
    return {
        "step_voxels": 1.0,
        "cone_angle_degrees": 30.0,
        "cone_angle_step_degrees": 5.0,
        "cone_grid_size": 3,
        "beam_width": 4,
        "beam_prune_distance_voxels": 2.0,
        "beam_lookahead_steps": 2,
        "smoothness_weight": 1.0,
        "smoothness_normal_weight": 1.0,
        "smoothness_tangent_weight": 1.0,
        "smoothness_free_angle_degrees": 10.0,
        "cumulative_smoothness_steps": 2,
        "cumulative_smoothness_tangent_weight": 1.0,
        "initial_free_angle_degrees": 10.0,
        "max_step_factor": 2.0,
        "meeting_accept_max_error_ratio": 0.5,
        "endpoint_accept_threshold_base_voxels": 2.0,
    }


def _vc3d_span(*, mode="trace", tags=None):
    trace = mode == "trace"
    out = {
        "optimizer": "native_fiber_trace3d",
        "metadata_version": 3,
        "tracer_version": 2,
        "interp_goal": "global",
        "interp_mode": mode,
        "metric": None if mode == "cspline" else 3.2,
        "msg": mode,
        "normal_manifest": "normal.lasagna.json",
        "fiber_manifest": "fiber.lasagna.json",
        "trace_to_base_scale": 1.0,
        "meeting_error_base_voxels": 0.4 if trace else None,
        "meeting_error_ratio": 0.2 if trace else None,
        "meeting_source": "bidirectional" if trace else "",
        "failure_code": "",
        "failure_detail": "",
        "lasagna_failure_code": "" if trace else "trace_not_selected",
        "lasagna_failure_detail": "",
        "config": _vc3d_config(),
    }
    if tags is not None:
        out["tags"] = tags
    return out


def _write_vc3d(tmp_path, *, version=4, mode="trace", line_points=None):
    if line_points is None:
        line_points = [[i, 0, 0] for i in range(6)]
    if version == 1:
        obj = {
            "type": "vc3d_fiber",
            "version": 1,
            "line_points": line_points,
            "control_points": [[0, 0, 0], [5, 0, 0]],
        }
    else:
        obj = {
            "type": "vc3d_fiber",
            "version": version,
            "optimization_mode": "native_fiber_trace3d",
            "generation": 2,
            "line_points": line_points,
            "control_points": [
                {
                    "position": [0, 0, 0],
                    "segment_to_next": _vc3d_span(
                        mode=mode, tags=["gap"] if version == 4 else None
                    ),
                },
                {"position": [5, 0, 0]},
            ],
        }
    path = tmp_path / "fiber.json"
    path.write_text(json.dumps(obj))
    return path


def test_native_vc3d_v4_is_audited_and_metadata_summarized(tmp_path):
    from scrollq.fiber_audit import audit_vc3d_json

    path = _write_vc3d(tmp_path, version=4)
    out = audit_vc3d_json(path, volume_root="volume-A")
    assert out["status"] == "pass"
    assert out["volume_root"] == "volume-A"
    assert out["input_format"] == "vc3d_fiber_json"
    assert out["vc3d_fiber"]["version"] == 4
    assert out["format_reference"]["commit"] == "56d7c3aeea4bbccf5f56b195ce2a44ea2cf601dd"
    assert out["vc3d_fiber"]["native_trace_segments"] == 1
    assert out["vc3d_fiber"]["fallback_segments"] == 0
    assert out["vc3d_fiber"]["tagged_segments"] == [
        {"segment": 0, "tags": ["gap"]}
    ]
    assert out["input"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_native_vc3d_fallback_is_observed_not_called_a_geometry_defect(tmp_path):
    from scrollq.fiber_audit import audit_vc3d_json

    out = audit_vc3d_json(_write_vc3d(tmp_path, version=3, mode="lasagna"))
    assert out["status"] == "pass"
    assert out["findings"] == []
    assert out["vc3d_fiber"]["fallback_segments"] == 1
    assert out["vc3d_fiber"]["fallback_fraction"] == pytest.approx(1.0)
    assert out["vc3d_fiber"]["failure_codes"][0]["lasagna_failure_code"] == "trace_not_selected"


def test_native_vc3d_geometry_findings_and_cli_gate(tmp_path):
    from scrollq.fiber_audit import audit_vc3d_json

    pts = [[0, 0, 0], [1, 0, 0], [2, 0, 0], [8, 0, 0], [8, 1, 0]]
    path = _write_vc3d(tmp_path, version=4, line_points=pts)
    out = audit_vc3d_json(path)
    assert out["status"] == "caution"
    assert {f["kind"] for f in out["findings"]} == {"gap", "sharp_turn"}

    with pytest.raises(SystemExit) as advisory:
        main([str(path)])
    assert advisory.value.code == 0
    with pytest.raises(SystemExit) as gated:
        main([str(path), "--fail-on-findings"])
    assert gated.value.code == 2


def test_native_vc3d_schema_mismatch_fails_closed(tmp_path):
    from scrollq.fiber_audit import audit_vc3d_json

    path = _write_vc3d(tmp_path, version=4)
    obj = json.loads(path.read_text())
    del obj["control_points"][0]["segment_to_next"]["config"]["beam_width"]
    path.write_text(json.dumps(obj))
    out = audit_vc3d_json(path)
    assert out["status"] == "fail"
    assert out["counts"]["parse_errors"] == 1
    assert "config" in out["errors"][0]["error"]


def test_native_vc3d_v1_remains_supported(tmp_path):
    from scrollq.fiber_audit import audit_vc3d_json

    out = audit_vc3d_json(_write_vc3d(tmp_path, version=1))
    assert out["status"] == "pass"
    assert out["vc3d_fiber"]["version"] == 1
    assert out["vc3d_fiber"]["optimization_mode"] == "lasagna"
