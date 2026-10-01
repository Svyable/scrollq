import json
import subprocess
import sys

import numpy as np

from scrollq.obj_audit import audit_obj, parse_obj


def _grid(n=6, *, uv_stretch=(1.0, 1.0), drop=(), z=None):
    """n x n vertex grid, unit spacing, as quads split into triangles."""
    verts, uvs, faces = [], [], []
    for j in range(n):
        for i in range(n):
            zz = 0.0 if z is None else z(i, j)
            verts.append((i, j, zz))
            uvs.append((i * uv_stretch[0], j * uv_stretch[1]))
    for j in range(n - 1):
        for i in range(n - 1):
            if (i, j) in drop:
                continue
            a, b, c, d = j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i
            faces += [(a, b, c), (a, c, d)]
    return verts, uvs, faces


def _write(tmp_path, verts, faces, uvs=None, name="m.obj"):
    lines = [f"v {x} {y} {z}" for x, y, z in verts]
    if uvs is not None:
        lines += [f"vt {u} {w}" for u, w in uvs]
        lines += ["f " + " ".join(f"{i + 1}/{i + 1}" for i in f) for f in faces]
    else:
        lines += ["f " + " ".join(str(i + 1) for i in f) for f in faces]
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def _kinds(r):
    return {f["kind"] for f in r["findings"]}


def test_clean_grid_passes(tmp_path):
    v, uv, f = _grid()
    r = audit_obj(_write(tmp_path, v, f, uv))
    assert r["status"] == "pass", r["warnings"]
    assert r["topology"]["components"] == 1
    assert r["topology"]["holes"] == 0
    assert r["topology"]["boundary_loops"] == 1
    assert r["isometry"]["status"] == "measured"
    assert abs(r["isometry"]["symmetric_stretch_distortion"]["max"] - 1.0) < 1e-9


def test_hole_is_detected(tmp_path):
    v, uv, f = _grid(drop={(2, 2)})
    r = audit_obj(_write(tmp_path, v, f, uv))
    assert _kinds(r) == {"hole"}
    assert r["topology"]["holes"] == 1


def test_disconnected_components(tmp_path):
    v, uv, f = _grid(drop={(2, j) for j in range(5)})
    r = audit_obj(_write(tmp_path, v, f, uv))
    assert "connectivity" in _kinds(r)
    assert r["topology"]["components"] == 2
    assert r["topology"]["holes"] == 0


def test_fold_is_a_normal_reversal(tmp_path):
    # A sheet folded back on itself along x = 3 (a crease of ~180 degrees).
    v, uv, f = _grid(n=7)
    v = [(x if x <= 3 else 6 - x, y, 0.0 if x <= 3 else 0.01 * (x - 3)) for x, y, _ in v]
    r = audit_obj(_write(tmp_path, v, f))
    assert "normal-reversal" in _kinds(r)
    assert r["normals"]["reversal_pairs"] > 0


def test_inconsistent_winding_is_not_counted_as_a_fold(tmp_path):
    v, uv, f = _grid()
    f[7] = (f[7][0], f[7][2], f[7][1])
    r = audit_obj(_write(tmp_path, v, f))
    assert _kinds(r) == {"orientation"}
    assert r["topology"]["inconsistent_winding_edges"] == 3
    assert r["normals"]["reversal_pairs"] == 0


def test_non_manifold_fin(tmp_path):
    v, uv, f = _grid()
    v.append((1.5, 1.5, 3.0))
    f.append((7, 14, len(v) - 1))  # a third face on the interior diagonal 7-14
    r = audit_obj(_write(tmp_path, v, f))
    assert "non-manifold" in _kinds(r)
    assert r["topology"]["nonmanifold_edges"] == 1


def test_area_preserving_uv_stretch_is_caught(tmp_path):
    v, uv, f = _grid(uv_stretch=(2.5, 0.4))
    r = audit_obj(_write(tmp_path, v, f, uv))
    assert "isometry-distortion" in _kinds(r)
    assert abs(r["isometry"]["symmetric_stretch_distortion"]["p95"] - 2.5) < 1e-9


def test_flipped_uv_triangle(tmp_path):
    v, uv, f = _grid()
    uv[14] = (1.0, 3.0)  # drag one UV across its neighbours
    r = audit_obj(_write(tmp_path, v, f, uv))
    assert "uv-flip" in _kinds(r)
    assert r["isometry"]["flipped_uv_triangles"] > 0


def test_edge_jump(tmp_path):
    v, uv, f = _grid()
    x, y, _ = v[14]
    v[14] = (x, y, 20.0)
    r = audit_obj(_write(tmp_path, v, f))
    assert "edge-jump" in _kinds(r)


def test_polygon_syntax_and_negative_indices(tmp_path):
    p = tmp_path / "quad.obj"
    p.write_text(
        "# comment\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n"
        "f -4/-4/1 -3/-3/1 -2/-2/1 -1/-1/1\n"
    )
    mesh = parse_obj(p)
    assert mesh["polygons"] == 1 and len(mesh["faces"]) == 2
    r = audit_obj(p)
    assert r["status"] == "pass"
    assert r["isometry"]["textured_triangles"] == 2


def test_empty_and_malformed_fail_closed(tmp_path):
    empty = tmp_path / "empty.obj"
    empty.write_text("v 0 0 0\n")
    assert audit_obj(empty)["status"] == "fail"
    bad = tmp_path / "bad.obj"
    bad.write_text("v 0 0 0\nv 1 0 0\nf 1 2 9\n")
    assert audit_obj(bad)["status"] == "fail"
    garbage = tmp_path / "garbage.obj"
    garbage.write_text("v 0 zero 0\n")
    assert audit_obj(garbage)["status"] == "fail"


def test_no_uvs_leaves_isometry_unknown(tmp_path):
    v, _, f = _grid()
    r = audit_obj(_write(tmp_path, v, f))
    assert r["status"] == "pass"
    assert r["isometry"]["status"] == "unknown"


def test_cli_writes_report_and_exits_nonzero_on_fail(tmp_path):
    v, uv, f = _grid()
    src = _write(tmp_path, v, f, uv)
    out = tmp_path / "r.json"
    ok = subprocess.run([sys.executable, "-m", "scrollq.obj_audit", "--obj", str(src),
                         "--out", str(out)], capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(out.read_text())["status"] == "pass"
    empty = tmp_path / "e.obj"
    empty.write_text("")
    bad = subprocess.run([sys.executable, "-m", "scrollq.obj_audit", "--obj", str(empty),
                          "--out", str(out)], capture_output=True, text=True)
    assert bad.returncode == 2
