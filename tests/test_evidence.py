import json
import shutil
from pathlib import Path

import pytest

from scrollq.evidence import ingest, mesh_hashes

FIX = Path(__file__).parent / "fixtures" / "evidence"
MESH = FIX / "elig" / "meshes" / "PHerc0800" / "z14672_w020"
REP = FIX / "reports"


@pytest.fixture(autouse=True)
def _run_from_fixture_root(monkeypatch):
    # The tools recorded mesh paths relative to where they ran.
    monkeypatch.chdir(FIX)


def _one(tool, report, mesh=MESH, check=None):
    recs = ingest(tool, report, subject_id="col", mesh_dir=mesh)
    if check:
        recs = [r for r in recs if r["check"] == check]
    assert len(recs) == 1
    return recs[0]


def test_windcheck_clean_certificate_is_hash_verified():
    r = _one("windcheck", REP / "windcheck.json")
    assert (r["check"], r["status"], r["binding"]) == (
        "mesh.self-intersection", "pass", "hash-verified")
    assert r["metrics"]["crossing_sites"] == 0
    assert r["source"]["pinned_commit"].startswith("2b0fb2f3")
    assert len(r["source"]["report_sha256"]) == 64


def test_report_about_a_different_mesh_version_is_an_error(tmp_path):
    other = tmp_path / "elig" / "meshes" / "PHerc0800" / "z14672_w020"
    shutil.copytree(MESH, other)
    data = bytearray((other / "x.tif").read_bytes())
    data[-1] ^= 0xFF
    (other / "x.tif").write_bytes(bytes(data))
    for tool in ("windcheck", "scroliq-mesh"):
        r = ingest(tool, REP / f"{tool}.json", mesh_dir=other)[0]
        assert r["status"] == "error"
        assert any("differ" in n for n in r["notes"])


def test_flatcheck_real_mesh_fails_the_bar_without_folds():
    r = _one("flatcheck", REP / "flatcheck.json")
    assert (r["status"], r["binding"], r["verdict_source"]) == ("fail", "path-declared", "tool")
    assert r["metrics"]["pct_quads_within_5pct"] == pytest.approx(67.81, abs=0.01)
    assert r["metrics"]["bar_pct"] == 93.1
    assert r["metrics"]["fold_overs"] == 0 and r["metrics"]["collapsed"] is False


def test_tifxyz_doctor_contract_warning_and_review_cues_are_cautions():
    contract = _one("tifxyz-doctor", REP / "tifxyz-doctor.json", check="mesh.tifxyz-contract")
    cues = _one("tifxyz-doctor", REP / "tifxyz-doctor.json", check="mesh.geometry-review-cues")
    assert contract["status"] == "caution"
    assert any("metadata-area-schema-divergence" in n for n in contract["notes"])
    assert cues["status"] == "caution" and cues["metrics"]["review_cues"] == 4


def test_tifxyz_repair_info_is_a_pass():
    r = _one("tifxyz-repair", REP / "tifxyz-repair.json")
    assert (r["status"], r["binding"]) == ("pass", "path-declared")


def test_scroliq_mesh_partial_is_caution_and_hash_verified():
    r = _one("scroliq-mesh", REP / "scroliq-mesh.json")
    assert (r["status"], r["binding"]) == ("caution", "hash-verified")
    assert r["metrics"] == {"errors": 0, "warnings": 1}


def test_spiralcheck_is_measured_never_a_verdict():
    r = ingest("spiralcheck", REP / "spiralcheck-pherc1218.json")[0]
    assert (r["check"], r["status"], r["verdict_source"], r["binding"]) == (
        "spiral.held-out", "measured", "none", "unbound")
    assert r["metrics"]["frac_within_tau"] == pytest.approx(0.7142857)


def test_path_naming_another_mesh_is_unbound(tmp_path):
    elsewhere = tmp_path / "some" / "other_mesh"
    shutil.copytree(MESH, elsewhere)
    r = _one("flatcheck", REP / "flatcheck.json", mesh=elsewhere)
    assert r["binding"] == "unbound"


@pytest.mark.parametrize("tool, content", [
    ("windcheck", {"schema": "windcheck_check/v9"}),
    ("tifxyz-doctor", {"contract": {"schema_version": "other"}}),
    ("flatcheck", {"something": 1}),
    ("tifxyz-repair", [{"path": "a"}, {"path": "b"}]),
])
def test_unrecognized_formats_are_errors_not_guesses(tmp_path, tool, content):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(content))
    r = ingest(tool, p, mesh_dir=MESH)[0]
    assert r["status"] == "error"


def test_unknown_tool_and_missing_report_are_errors(tmp_path):
    assert ingest("nosuchtool", tmp_path / "x.json")[0]["status"] == "error"
    assert ingest("windcheck", tmp_path / "missing.json")[0]["status"] == "error"


def test_mesh_hashes_cover_coordinate_files():
    h = mesh_hashes(MESH)
    assert set(h) == {"x.tif", "y.tif", "z.tif"}
    assert h["x.tif"].startswith("5e83506b1a85b159")
