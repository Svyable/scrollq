import copy
import hashlib
import json

from scrollq.evidence_adapters import WINDCHECK_ADAPTER, normalize_native_report
from scrollq.evidence_ledger import validate_evidence_ledger
from scrollq.package_hash import sha256_path


def _entry(ident, claim, *, status="pass", mesh_ids=None, adapter=None):
    entry = {
        "id": ident,
        "claim": claim,
        "status": status,
        "tool": "independent-tool",
        "artifact_url": "https://example.org/evidence/report.json",
        "sha256": "a" * 64,
        "scope": {
            "mesh_ids": list(mesh_ids or []),
            "mesh_sha256": {
                mesh_id: "c" * 64 for mesh_id in (mesh_ids or [])
            },
        },
        "producer": {
            "repository": "https://github.com/example/independent-tool",
            "commit": "b" * 40,
            "command": "independent-tool --json report.json",
        },
    }
    if adapter is not None:
        entry["normalization"] = {"adapter": adapter, "assessment": {}}
    return entry


def _ledger():
    return {
        "schema_version": 1,
        "diagnostic": "grand-prize-evidence-ledger",
        "volume_id": "eligible-volume",
        "entries": [
            _entry(
                "flat",
                "flattening-isometry",
                mesh_ids=["mesh:01", "mesh:02"],
                adapter="flatcheck-grid/v1",
            ),
            _entry(
                "cross",
                "mesh-self-intersection",
                mesh_ids=["mesh:01", "mesh:02"],
                adapter="windcheck-check/v1",
            ),
            _entry("hand", "render-handedness", mesh_ids=["mesh:01", "mesh:02"]),
            _entry("spiral", "spiral-held-out"),
        ],
    }


def test_policy_does_not_invent_passes_for_unresolved_claims():
    report = validate_evidence_ledger(
        _ledger(),
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "partial"
    assert report["ready"] is False
    assert report["error_count"] == 0
    by_claim = {item["claim"]: item["status"] for item in report["required_claims"]}
    assert by_claim["flattening-isometry"] == "partial"
    assert by_claim["mesh-self-intersection"] == "partial"
    assert by_claim["render-handedness"] == "partial"
    assert by_claim["spiral-held-out"] == "partial"
    assert sum(
        item["code"] == "EVIDENCE_PASS_NOT_AUTHORIZED"
        for item in report["warnings"]
    ) == 3
    assert any(
        item["code"] == "EVIDENCE_NATIVE_BINDING_UNVERIFIED"
        for item in report["warnings"]
    )


def test_missing_mesh_coverage_stays_partial_not_clean():
    ledger = _ledger()
    ledger["entries"][0]["scope"]["mesh_ids"] = ["mesh:01"]

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "partial"
    assert report["ready"] is False
    claim = next(
        item for item in report["required_claims"]
        if item["claim"] == "flattening-isometry"
    )
    assert claim["missing_mesh_ids"] == ["mesh:02"]


def test_explicit_failure_blocks_even_when_other_evidence_passes():
    ledger = _ledger()
    ledger["entries"][2]["status"] = "fail"

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    claim = next(
        item for item in report["required_claims"]
        if item["claim"] == "render-handedness"
    )
    assert claim["failed_evidence_ids"] == ["hand"]


def test_wrong_exact_volume_fails_closed():
    report = validate_evidence_ledger(
        _ledger(),
        expected_volume_id="different-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_VOLUME_MISMATCH" in {
        item["code"] for item in report["errors"]
    }


def test_unknown_mesh_reference_is_a_structural_error():
    ledger = _ledger()
    ledger["entries"][0]["scope"]["mesh_ids"].append("mesh:not-submitted")

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_SCOPE_UNKNOWN_MESH" in {
        item["code"] for item in report["errors"]
    }


def test_duplicate_evidence_ids_fail():
    ledger = _ledger()
    duplicate = copy.deepcopy(ledger["entries"][0])
    ledger["entries"].append(duplicate)

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_DUPLICATE_ID" in {
        item["code"] for item in report["errors"]
    }


def test_mesh_digest_must_match_provenance_manifest():
    report = validate_evidence_ledger(
        _ledger(),
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:01", "mesh:02"],
        expected_mesh_sha256={
            "mesh:01": "d" * 64,
            "mesh:02": "c" * 64,
        },
    )

    assert report["status"] == "fail"
    assert "EVIDENCE_SCOPE_MESH_HASH_MISMATCH" in {
        item["code"] for item in report["errors"]
    }



def _windcheck_report_for(mesh):
    names = ("x.tif", "y.tif", "z.tif", "mask.tif", "mask.png", "meta.json")
    rows = []
    for name in names:
        path = mesh / name
        if path.is_file():
            payload = path.read_bytes()
            rows.append({
                "path": name,
                "present": True,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
        else:
            rows.append({
                "path": name,
                "present": False,
                "size": None,
                "sha256": None,
            })
    lines = []
    for row in sorted(rows, key=lambda item: item["path"]):
        if row["present"]:
            lines.append(f"{row['path']}\0{row['size']}\0{row['sha256']}")
        else:
            lines.append(f"{row['path']}\0absent\0absent")
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    return {
        "tool": "windcheck check",
        "schema": "windcheck_check/v1",
        "report_only": True,
        "mesh": {
            "path": str(mesh),
            "hashes": {
                "schema": "windcheck_mesh_manifest/v1",
                "files": rows,
                "digest": digest,
            },
        },
        "measurements": {
            "transverse_d0": 0,
            "transverse_d1": 0,
            "crossing_events": 0,
        },
        "clean": True,
        "clean_definition": "zero transverse contacts under both triangulations",
    }


def test_windcheck_pass_requires_and_accepts_exact_native_mesh_binding(tmp_path):
    mesh = tmp_path / "column_01.tifxyz"
    mesh.mkdir()
    (mesh / "x.tif").write_bytes(b"x")
    (mesh / "y.tif").write_bytes(b"y")
    (mesh / "z.tif").write_bytes(b"z")
    (mesh / "meta.json").write_bytes(b'{"format":"tifxyz"}')

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    native = _windcheck_report_for(mesh)
    native_path = evidence_dir / "windcheck.json"
    raw = json.dumps(native, sort_keys=True).encode()
    native_path.write_bytes(raw)

    mesh_digest = sha256_path(mesh)
    entry = normalize_native_report(
        adapter=WINDCHECK_ADAPTER,
        report=native,
        entry_id="wind:column-01",
        mesh_id="mesh:column-01",
        artifact_url="https://example.org/evidence/windcheck.json",
        sha256=hashlib.sha256(raw).hexdigest(),
        path="evidence/windcheck.json",
        mesh_sha256=mesh_digest,
        producer_commit="b" * 40,
        command="windcheck check column_01.tifxyz --out evidence",
    )
    ledger = {
        "schema_version": 1,
        "diagnostic": "grand-prize-evidence-ledger",
        "volume_id": "eligible-volume",
        "entries": [entry],
    }

    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:column-01"],
        expected_mesh_sha256={"mesh:column-01": mesh_digest},
        expected_mesh_paths={"mesh:column-01": "column_01.tifxyz"},
        root_dir=tmp_path,
        require_local_artifacts=True,
    )
    claim = next(
        item for item in report["required_claims"]
        if item["claim"] == "mesh-self-intersection"
    )
    assert claim["status"] == "pass"
    assert report["error_count"] == 0

    (mesh / "x.tif").write_bytes(b"tampered")
    report = validate_evidence_ledger(
        ledger,
        expected_volume_id="eligible-volume",
        expected_mesh_ids=["mesh:column-01"],
        expected_mesh_sha256={"mesh:column-01": mesh_digest},
        expected_mesh_paths={"mesh:column-01": "column_01.tifxyz"},
        root_dir=tmp_path,
        require_local_artifacts=True,
    )
    assert "EVIDENCE_NATIVE_MESH_BINDING" in {
        item["code"] for item in report["errors"]
    }
