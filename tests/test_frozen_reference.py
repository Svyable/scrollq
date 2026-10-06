"""The official recto 3D U-Net is registered as a frozen baseline, unpinned.

Nothing that requires the checkpoint bytes may be filled in without them, and
the checkpoint license must never stand in for the training-data terms.
"""

import json
from pathlib import Path

REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "artifacts" / "2026-10-06-recto-3dunet-reference" / "reference.json"
)

ANCESTRY = {"PHerc0139", "PHerc1667", "PHerc0343P", "PHerc0500P2", "PHercMANBp"}


def load():
    return json.loads(REFERENCE.read_text())


def test_unpinned_fields_stay_empty():
    ref = load()
    assert ref["pin_status"] == "unpinned"
    src = ref["source"]
    for key in ("revision", "checkpoint_sha256", "checkpoint_bytes"):
        assert src[key] is None, key


def test_licenses_are_separate_and_unverified():
    lic = load()["licenses"]
    assert set(lic) == {"checkpoint", "training_data"}
    for entry in lic.values():
        assert entry["verified"] is False
        assert entry["evidence_url"] is None
    assert "MIT" in lic["checkpoint"]["statement"]
    assert "CC BY-NC" in lic["training_data"]["statement"]


def test_training_ancestry_is_scroll_level():
    ancestry = load()["training_ancestry"]
    assert {a["scroll"] for a in ancestry} == ANCESTRY
    assert all(a["volume_id"] is None for a in ancestry)


def test_prize_targets_disjoint_or_flagged():
    from scrollq.grand_prize import DEFAULT_MANIFEST

    ref = load()
    gp = {t["scroll"] for t in DEFAULT_MANIFEST["targets"]}
    assert len(gp) == 13
    assert not gp & ANCESTRY
    conflicts = " ".join(ref["ancestry_conflicts_to_resolve"])
    assert "PHerc0343" in conflicts and "PHerc0139" in conflicts
