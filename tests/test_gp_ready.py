import json
from pathlib import Path

import pytest

from scrollq.gp_ready import DEFAULT_POLICY, compile_dossier, main

FIX = Path(__file__).parent / "fixtures" / "evidence"
MESH = "elig/meshes/PHerc0800/z14672_w020"
ALL_MESH_EVIDENCE = [
    {"tool": t, "report": f"reports/{t}.json"}
    for t in ("windcheck", "flatcheck", "tifxyz-doctor", "tifxyz-repair", "scroliq-mesh")
]


@pytest.fixture(autouse=True)
def _run_from_fixture_root(monkeypatch):
    monkeypatch.chdir(FIX)


def _manifest(evidence=ALL_MESH_EVIDENCE, submission=()):
    return {"schema_version": 1, "submission": "test",
            "columns": [{"id": "column_01", "mesh": MESH, "evidence": list(evidence)}],
            "submission_evidence": list(submission)}


def _check(dossier, name, column=0):
    return next(c for c in dossier["columns"][column]["checks"] if c["check"] == name)


def test_real_mesh_is_not_ready_and_every_blocker_is_named():
    d = compile_dossier(_manifest(), FIX)
    assert d["ready"] is False and d["columns_ready"] == 0
    assert _check(d, "mesh.self-intersection")["status"] == "pass"
    assert _check(d, "mesh.flatten-distortion")["status"] == "fail"
    # doctor says caution, repair says pass: the worse one decides.
    assert _check(d, "mesh.tifxyz-contract")["status"] == "caution"
    assert _check(d, "mesh.scroliq-audit")["status"] == "caution"
    handed = _check(d, "mesh.handedness")
    assert handed["status"] == "missing" and "no adapter yet" in handed["reason"]
    blockers = d["columns"][0]["blockers"]
    assert any(b.startswith("mesh.flatten-distortion: fail") for b in blockers)
    assert not any(b.startswith("mesh.self-intersection") for b in blockers)
    # Review cues are reported but not required by the default policy.
    assert any(r["check"] == "mesh.geometry-review-cues"
               for r in d["columns"][0]["informational"])


def test_measured_needs_a_declared_threshold():
    sub = [{"tool": "spiralcheck", "report": "reports/spiralcheck-pherc1218.json"}]
    d = compile_dossier(_manifest(submission=sub), FIX)
    spiral = next(c for c in d["submission_checks"]["checks"] if c["check"] == "spiral.held-out")
    assert spiral["status"] == "measured"

    for bound, expected in ((0.7, "pass"), (0.9, "fail")):
        policy = {**DEFAULT_POLICY,
                  "thresholds": {"spiral.held-out": {"frac_within_tau": [">=", bound]}}}
        d = compile_dossier(_manifest(submission=sub), FIX, policy)
        spiral = next(c for c in d["submission_checks"]["checks"]
                      if c["check"] == "spiral.held-out")
        assert spiral["records"][0]["status"] == expected
        assert spiral["records"][0]["verdict_source"] == "policy"
        # The example report names its fit by a placeholder path, so nothing
        # ties it to this submission: a passing number still cannot count.
        assert spiral["records"][0]["binding"] == "unbound"
        assert spiral["status"] == ("binding-too-weak" if expected == "pass" else "fail")


def test_stricter_binding_policy_rejects_path_only_evidence():
    policy = {**DEFAULT_POLICY, "min_binding": "coordinate-exact",
              "column_checks": ["mesh.self-intersection", "mesh.tifxyz-contract"],
              "submission_checks": []}
    ev = [{"tool": "windcheck", "report": "reports/windcheck.json"},
          {"tool": "tifxyz-repair", "report": "reports/tifxyz-repair.json"}]
    d = compile_dossier(_manifest(ev), FIX, policy)
    assert _check(d, "mesh.self-intersection")["status"] == "pass"
    assert _check(d, "mesh.tifxyz-contract")["status"] == "binding-too-weak"


def test_a_column_is_ready_only_when_every_required_check_passes():
    policy = {**DEFAULT_POLICY, "column_checks": ["mesh.self-intersection"],
              "submission_checks": []}
    ev = [{"tool": "windcheck", "report": "reports/windcheck.json"}]
    d = compile_dossier(_manifest(ev), FIX, policy)
    assert d["ready"] is True and d["columns_ready"] == 1
    # No columns is never ready.
    empty = {"schema_version": 1, "submission": "x", "columns": []}
    assert compile_dossier(empty, FIX, policy)["ready"] is False


def test_policy_is_hashed_into_the_dossier():
    a = compile_dossier(_manifest(), FIX)
    b = compile_dossier(_manifest(), FIX, {**DEFAULT_POLICY, "policy_id": "other"})
    assert len(a["policy_sha256"]) == 64 and a["policy_sha256"] != b["policy_sha256"]


def test_cli_writes_dossier_and_markdown(tmp_path):
    m = tmp_path / "manifest.json"
    manifest = _manifest()
    for e in manifest["columns"][0]["evidence"]:
        e["report"] = str(FIX / e["report"])
    manifest["columns"][0]["mesh"] = str(FIX / MESH)
    m.write_text(json.dumps(manifest))
    out, md = tmp_path / "d.json", tmp_path / "d.md"
    main(["--manifest", str(m), "--out", str(out), "--markdown", str(md)])
    assert json.loads(out.read_text())["columns_total"] == 1
    assert "| column_01 |" in md.read_text()
    with pytest.raises(SystemExit) as exc:
        main(["--manifest", str(m), "--out", str(out), "--fail-unless-ready"])
    assert exc.value.code == 1
