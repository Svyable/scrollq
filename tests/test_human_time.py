import hashlib
import json

import pytest

from scrollq.human_time import HumanTimeError, add_entry, init_ledger, summarize


def test_measured_session_appends_packager_compatible_entry(tmp_path):
    ledger = tmp_path / "human-input.json"
    init_ledger(ledger)
    result = add_entry(
        ledger,
        description="Review a winding transition in VC3D",
        started_utc="2026-10-03T15:00:00Z",
        ended_utc="2026-10-03T15:30:00Z",
        operator="reviewer-1",
        stage="vc3d-review",
    )
    assert result["entry"]["hours"] == 0.5
    document = json.loads(ledger.read_text())
    assert document["schema_version"] == 1
    assert document["entries"][0]["description"]
    assert document["entries"][0]["hours"] == 0.5
    assert summarize(document)["remaining_hours"] == 7.5


def test_hours_and_measured_duration_must_agree(tmp_path):
    ledger = tmp_path / "human-input.json"
    init_ledger(ledger)
    with pytest.raises(HumanTimeError, match="does not match"):
        add_entry(
            ledger,
            description="review",
            hours=1.0,
            started_utc="2026-10-03T15:00:00Z",
            ended_utc="2026-10-03T15:30:00Z",
        )


def test_cap_is_fail_closed(tmp_path):
    ledger = tmp_path / "human-input.json"
    init_ledger(ledger)
    add_entry(ledger, description="first", hours=7.75)
    with pytest.raises(HumanTimeError, match="exceed 8-hour"):
        add_entry(ledger, description="too much", hours=0.26)
    assert summarize(json.loads(ledger.read_text()))["total_hours"] == 7.75


def test_artifact_hash_is_recorded(tmp_path):
    ledger = tmp_path / "human-input.json"
    artifact = tmp_path / "column_01.tif"
    artifact.write_bytes(b"render")
    init_ledger(ledger)
    result = add_entry(
        ledger,
        description="inspect final column",
        hours=0.25,
        artifact=artifact,
        root=tmp_path,
    )
    assert result["entry"]["artifact"] == {
        "path": "column_01.tif",
        "sha256": hashlib.sha256(b"render").hexdigest(),
    }


def test_tampered_measured_entry_is_rejected():
    document = {
        "schema_version": 1,
        "entries": [
            {
                "description": "review",
                "hours": 0.25,
                "started_utc": "2026-10-03T15:00:00Z",
                "ended_utc": "2026-10-03T15:30:00Z",
            }
        ],
    }
    with pytest.raises(HumanTimeError, match="does not match"):
        summarize(document)
