import copy
import json

import numpy as np
import pytest

from scrollq.shortcut_audit import audit, main


def fixture(leak=True):
    rng = np.random.default_rng(10)
    rows, features = [], []
    for split in ("train", "test"):
        for domain in range(2):
            for ink in range(2):
                for index in range(30):
                    identity = f"{split}-{domain}-{ink}-{index}"
                    rows.append({"sample_id": identity, "group_id": identity,
                        "probe_split": split, "fragment_id": str(domain),
                        "scroll_id": str(domain), "acquisition_id": str(domain),
                        "ink_label": ink, "ink_probability": .9 if ink else .1})
                    features.append([domain * 10 if leak else ink * 10, *rng.normal(size=3)])
    return np.array(features), {"samples": rows, "embedding_layer": "penultimate",
        "label_evidence": "synthetic-control-only", "training_domains": {
            "fragment_id": [], "scroll_id": [], "acquisition_id": []}}


def test_leak_positive_control_and_null():
    x, manifest = fixture()
    result = audit(x, manifest)
    assert result == audit(x, manifest)
    assert result["probes"]["fragment_id"]["balanced_accuracy"] == 1
    assert result["causal_shortcut_demonstrated"] is False
    assert result["promotional"] is False
    assert result["probes"]["fragment_id"]["held_out_error_association"]["scroll_id"]["status"] == "unverified"
    x, manifest = fixture(leak=False)
    assert audit(x, manifest)["probes"]["fragment_id"]["balanced_accuracy"] < .65


@pytest.mark.parametrize("mutation", ["group", "duplicate", "nan", "label", "probability", "inventory", "id"])
def test_fail_closed(mutation):
    x, manifest = fixture()
    if mutation == "group":
        manifest["samples"][-1]["group_id"] = manifest["samples"][0]["group_id"]
    elif mutation == "duplicate":
        x[-1] = x[0]
    elif mutation == "nan":
        x[0, 0] = np.nan
    elif mutation == "label":
        manifest["samples"][0]["ink_label"] = True
    elif mutation == "probability":
        manifest["samples"][0]["ink_probability"] = float("inf")
    elif mutation == "inventory":
        del manifest["training_domains"]["scroll_id"]
    else:
        manifest["samples"][-1]["sample_id"] = manifest["samples"][0]["sample_id"]
    with pytest.raises(ValueError):
        audit(x, manifest)


def test_missing_and_unbalanced_are_unverified():
    x, manifest = fixture()
    assert audit(x, manifest)["probes"]["segment_id"]["status"] == "unverified"
    for row in manifest["samples"]:
        if row["fragment_id"] == "0":
            row["ink_label"] = 0
    assert audit(x, manifest)["probes"]["fragment_id"]["status"] == "unverified"


def test_training_domain_not_claimed_heldout():
    x, manifest = fixture()
    manifest["training_domains"]["scroll_id"] = ["0", "1"]
    result = audit(x, manifest)
    assert result["held_out_ink"]["scroll_id"]["status"] == "unverified"
    assert result["probes"]["scroll_id"]["held_out_error_association"]["scroll_id"]["n"] == 0


def test_operational_error_association_is_descriptive():
    x, manifest = fixture()
    # Vary the acquisition fingerprint and induce errors on its strongest patches.
    for i, row in enumerate(manifest["samples"]):
        x[i, 0] = (-1 if row["fragment_id"] == "0" else 1) * (1 + i % 30)
        if i % 30 > 15:
            row["ink_probability"] = 1 - row["ink_probability"]
    association = audit(x, manifest)["probes"]["fragment_id"]["held_out_error_association"]["fragment_id"]
    assert association["status"] == "measured_descriptive_only"
    assert association["pearson_r"] > .8


def test_cli_hashes_and_create_only(tmp_path):
    x, manifest = fixture()
    np.save(tmp_path / "x.npy", x)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "checkpoint").write_bytes(b"synthetic-not-model")
    argv = ["--embeddings", str(tmp_path / "x.npy"), "--manifest", str(tmp_path / "manifest.json"),
            "--checkpoint", str(tmp_path / "checkpoint"), "--out", str(tmp_path / "result.json")]
    main(argv)
    report = json.loads((tmp_path / "result.json").read_text())
    assert all(len(value) == 64 for value in report["sha256"].values())
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2


def test_seed_and_ridge_validation():
    x, manifest = fixture()
    for kwargs in ({"seed": -1}, {"seed": True}, {"ridge": 0}, {"ridge": np.nan}):
        with pytest.raises(ValueError):
            audit(x, copy.deepcopy(manifest), **kwargs)
