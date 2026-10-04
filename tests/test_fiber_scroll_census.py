import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_fiber_audit import _write_vc3d  # noqa: E402


def _m():
    sys.path.insert(0, str(ROOT / "scripts"))
    s = importlib.util.spec_from_file_location("fsc", ROOT / "scripts/fiber_scroll_census.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_planted_break_is_detected_by_the_real_auditor(tmp_path):
    from scrollq.fiber_audit import audit_vc3d_json

    m = _m()
    path = _write_vc3d(tmp_path, version=3, line_points=[[i, 0, 0] for i in range(21)])
    obj = json.loads(path.read_text())
    assert not any(f["kind"] == "gap" for f in audit_vc3d_json(path)["findings"])
    planted, j = m.plant_break(obj)
    steps = [planted["line_points"][i + 1][0] - planted["line_points"][i][0] for i in range(20)]
    assert steps[j] == 10.0 and sum(s == 1.0 for s in steps) == 19
    out = tmp_path / "planted.json"
    out.write_text(json.dumps(planted))
    gaps = [f for f in audit_vc3d_json(out)["findings"] if f["kind"] == "gap"]
    assert [g["segment"] for g in gaps] == [j]


def test_plant_break_skips_degenerate_lines():
    m = _m()
    assert m.plant_break({"line_points": [[0, 0, 0], [1, 0, 0]]}) is None
    assert m.plant_break({"line_points": [[0, 0, 0]] * 5}) is None


def test_scroll_volumes_come_from_the_pinned_index():
    m = _m()
    vols = m.scroll_volumes("PHerc0139")
    assert len(vols) == 9 and all(v.startswith("PHerc0139/volumes/") for v in vols)
