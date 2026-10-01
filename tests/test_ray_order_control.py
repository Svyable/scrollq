"""bin/ray_order_control.py: injected mis-numberings must be caught, and
untestable injections must be reported, not folded into recall."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_winding_geometry import _absolute_doc, _spiral_point, _umbilicus  # noqa: E402

BIN = Path(__file__).resolve().parents[1] / "bin" / "ray_order_control.py"


def _load():
    spec = importlib.util.spec_from_file_location("ray_order_control", BIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_injections_on_ideal_spiral_are_detected_and_lead_the_queue():
    control = _load().run_control(
        {"absolute": _absolute_doc()}, _umbilicus(), injections=20, shifts=(3,), seed=1
    )

    summary = control["by_shift"]["3"]["summary"]
    assert control["baseline"]["inversion_candidates"] == 0
    assert summary["injections"] == 20
    assert summary["testable"] > 0
    assert summary["recall_of_testable"] >= 0.9
    assert summary["rank1_of_detected"] >= 0.9


def test_data_is_restored_after_each_injection():
    doc = {"absolute": _absolute_doc()}
    before = repr(doc)
    _load().run_control(doc, _umbilicus(), injections=5, shifts=(2, 5), seed=0)
    assert repr(doc) == before


def test_isolated_point_is_untestable_not_a_miss():
    doc = {
        "vc_pointcollections_json_version": "1",
        "collections": {
            "1": {
                "name": "lonely",
                "points": {
                    "0": {"p": _spiral_point(3, 0.2, 100.0), "wind_a": 3},
                    "1": {"p": _spiral_point(9, 3.0, 900.0), "wind_a": 9},
                },
            }
        },
    }
    control = _load().run_control({"absolute": doc}, _umbilicus(), injections=2, shifts=(5,))
    summary = control["by_shift"]["5"]["summary"]
    assert summary["testable"] == 0
    assert summary["untestable"] == 2
    assert summary["recall_of_testable"] is None


def test_two_winding_errors_are_invisible_by_construction():
    # With min_winding_gap=2 a shift s can only invert against a neighbour
    # whose true winding lies strictly between old and new label, which
    # needs s >= 3. On a dense consecutive line a +/-2 error is never caught.
    line = {
        str(i): {"p": _spiral_point(3 + i, 1.0 + 0.01 * i, 100.0 + i), "wind_a": i}
        for i in range(9)
    }
    doc = {
        "vc_pointcollections_json_version": "1",
        "collections": {"1": {"name": "line", "points": line}},
    }
    control = _load().run_control({"relative": doc}, _umbilicus(), injections=9, shifts=(2, 3))
    assert control["by_shift"]["2"]["summary"]["detected"] == 0
    assert control["by_shift"]["3"]["summary"]["detected"] > 0
