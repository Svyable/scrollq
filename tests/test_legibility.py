import copy
import hashlib
import json

from scrollq import legibility as lg


def _manifest(columns=1):
    meshes = []
    renders = []
    for column in range(1, columns + 1):
        meshes.append(
            {
                "id": f"mesh:column-{column:02d}",
                "column": column,
                "path": f"column_{column:02d}.tifxyz",
                "sha256": f"{column:x}" * 64,
            }
        )
        renders.append(
            {
                "id": f"render:column-{column:02d}",
                "column": column,
                "mesh_id": f"mesh:column-{column:02d}",
                "path": f"column_{column:02d}.tif",
                "sha256": f"{column + 8:x}" * 64,
            }
        )
    return {
        "schema_version": 6,
        "submission": {"scroll_id": "PHerc0813"},
        "meshes": meshes,
        "renders": renders,
    }


def _character(index, *, status="legible", reading="α"):
    row = {
        "id": f"c{index:03d}",
        "status": status,
    }
    if status in {"legible", "illegible"}:
        x = index * 10
        row["bbox_xyxy"] = [x, 10, x + 8, 24]
    if status == "legible":
        row["reading"] = reading
        row["interpolated"] = False
    elif status == "lost":
        row["loss_evidence"] = "Papyrus missing at this character position"
    return row


def _column_ledger(manifest, column=1, *, legible=7, illegible=3):
    render = next(r for r in manifest["renders"] if r["column"] == column)
    mesh = next(m for m in manifest["meshes"] if m["column"] == column)
    chars = [
        _character(i + 1, status="legible")
        for i in range(legible)
    ]
    chars += [
        _character(legible + i + 1, status="illegible", reading=None)
        for i in range(illegible)
    ]
    chars.append(_character(legible + illegible + 1, status="lost"))
    return {
        "column": column,
        "render_id": render["id"],
        "mesh_id": mesh["id"],
        "render_sha256": render["sha256"],
        "mesh_sha256": mesh["sha256"],
        "counted": True,
        "lines": [{"line": 1, "characters": chars}],
    }


def _ledger(manifest, *, legible=7, illegible=3):
    return {
        "schema_version": 1,
        "scroll_id": manifest["submission"]["scroll_id"],
        "columns": [
            _column_ledger(
                manifest,
                column=column,
                legible=legible,
                illegible=illegible,
            )
            for column in range(1, len(manifest["renders"]) + 1)
        ],
    }


def _codes(report):
    return {item["code"] for item in report["errors"]}


def test_exact_seventy_percent_passes_and_lost_characters_stay_out_of_denominator():
    manifest = _manifest()
    ledger = _ledger(manifest, legible=7, illegible=3)

    report = lg.audit_legibility(
        manifest,
        ledger,
        manifest_sha256="a" * 64,
        ledger_sha256="b" * 64,
    )

    assert report["passes_recorded_thresholds"] is True
    assert report["threshold"] == 0.70
    assert report["summary"]["preserved_characters"] == 10
    assert report["summary"]["legible_characters"] == 7
    assert report["summary"]["weighted_recorded_legibility_rate"] == 0.7
    assert report["columns"][0]["lost_characters"] == 1
    assert report["columns"][0]["passes_70_percent"] is True
    assert report["manifest_sha256"] == "a" * 64
    assert report["ledger_sha256"] == "b" * 64


def test_below_seventy_percent_fails_per_column():
    manifest = _manifest()
    report = lg.audit_legibility(
        manifest,
        _ledger(manifest, legible=6, illegible=4),
    )

    assert report["passes_recorded_thresholds"] is False
    assert "LEGIBILITY_BELOW_70_PERCENT" in _codes(report)
    assert report["columns"][0]["recorded_legibility_rate"] == 0.6


def test_interpolation_and_multi_character_readings_never_count_cleanly():
    manifest = _manifest()
    ledger = _ledger(manifest)
    first = ledger["columns"][0]["lines"][0]["characters"][0]
    first["interpolated"] = True
    second = ledger["columns"][0]["lines"][0]["characters"][1]
    second["reading"] = "αβ"

    report = lg.audit_legibility(manifest, ledger)

    assert "LEGIBILITY_INTERPOLATED" in _codes(report)
    assert "LEGIBILITY_NOT_LETTER_BY_LETTER" in _codes(report)
    assert report["passes_recorded_thresholds"] is False


def test_combining_mark_reading_is_one_character():
    manifest = _manifest()
    ledger = _ledger(manifest)
    ledger["columns"][0]["lines"][0]["characters"][0]["reading"] = "α\u0301"

    report = lg.audit_legibility(manifest, ledger)

    assert "LEGIBILITY_NOT_LETTER_BY_LETTER" not in _codes(report)


def test_ledger_is_bound_to_exact_render_and_mesh_hashes():
    manifest = _manifest()
    ledger = _ledger(manifest)
    ledger["columns"][0]["render_sha256"] = "f" * 64
    ledger["columns"][0]["mesh_sha256"] = "e" * 64

    report = lg.audit_legibility(manifest, ledger)

    assert "LEGIBILITY_RENDER_BINDING" in _codes(report)
    assert "LEGIBILITY_MESH_BINDING" in _codes(report)


def test_every_submitted_render_column_must_have_a_ledger_row():
    manifest = _manifest(columns=2)
    ledger = _ledger(manifest)
    ledger["columns"].pop()

    report = lg.audit_legibility(manifest, ledger)

    assert "LEGIBILITY_COLUMN_COVERAGE" in _codes(report)
    assert "missing=[2]" in next(
        item["message"]
        for item in report["errors"]
        if item["code"] == "LEGIBILITY_COLUMN_COVERAGE"
    )


def test_uncounted_column_requires_challenge_acknowledgement():
    manifest = _manifest()
    ledger = _ledger(manifest)
    row = ledger["columns"][0]
    row["counted"] = False
    row["exclusion"] = {
        "reason": "No ink is preserved in this column",
        "challenge_acknowledged": False,
        "reference": "email-2027-05-01",
    }

    report = lg.audit_legibility(manifest, ledger)
    assert "LEGIBILITY_EXCLUSION_ACK" in _codes(report)

    row["exclusion"]["challenge_acknowledged"] = True
    report = lg.audit_legibility(manifest, ledger)
    assert "LEGIBILITY_EXCLUSION_ACK" not in _codes(report)
    assert report["passes_recorded_thresholds"] is True
    assert report["summary"]["excluded_columns"] == 1
    assert report["summary"]["preserved_characters"] == 0
    assert report["summary"]["legible_characters"] == 0
    assert report["summary"]["weighted_recorded_legibility_rate"] is None


def test_duplicate_character_ids_fail_closed():
    manifest = _manifest()
    ledger = _ledger(manifest)
    chars = ledger["columns"][0]["lines"][0]["characters"]
    chars[1]["id"] = chars[0]["id"]

    report = lg.audit_legibility(manifest, ledger)

    assert "LEGIBILITY_CHARACTER_ID" in _codes(report)


def test_cli_writes_hash_bound_report(tmp_path):
    manifest = _manifest()
    ledger = _ledger(manifest)
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    ledger_raw = (json.dumps(ledger, sort_keys=True) + "\n").encode()
    manifest_path = tmp_path / "provenance.json"
    ledger_path = tmp_path / "legibility.json"
    out = tmp_path / "legibility-report.json"
    manifest_path.write_bytes(manifest_raw)
    ledger_path.write_bytes(ledger_raw)

    code = lg.main(
        [
            "--manifest",
            str(manifest_path),
            "--ledger",
            str(ledger_path),
            "--out",
            str(out),
            "--format",
            "json",
        ]
    )

    assert code == 0
    report = json.loads(out.read_text())
    assert report["passes_recorded_thresholds"] is True
    assert report["manifest_sha256"] == hashlib.sha256(manifest_raw).hexdigest()
    assert report["ledger_sha256"] == hashlib.sha256(ledger_raw).hexdigest()


def test_ledger_input_is_not_mutated():
    manifest = _manifest()
    ledger = _ledger(manifest)
    before = copy.deepcopy(ledger)

    lg.audit_legibility(manifest, ledger)

    assert ledger == before
