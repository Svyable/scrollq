"""Coverage join must fail closed on an empty inventory.

Regression for the 2026-09-30 n24-dense campaign: its coverage.json was
built from an inventory with no ink or segment roots, so every volume read
0 labels and PHercParis4 (70 ink labels) was flagged label-next.
"""

import json
import subprocess
import sys
from collections import Counter

import pytest

from scrollq.coverage import build_coverage, counts_from_coverage

ROOT = "community-uploads/forrest/volcomp/{}/volumes/v.zarr"


def _vols(*pairs):
    return [{"root": ROOT.format(s), "ok": True, "score": sc} for s, sc in pairs]


def test_empty_inventory_is_rejected():
    with pytest.raises(ValueError, match="no ink-detection or surface-volume"):
        build_coverage(_vols(("PHerc0001", 50.0)), Counter(), Counter())


def test_labelled_scroll_is_not_label_next():
    vols = _vols(("PHercParis4", 90.0), ("PHerc0002", 80.0),
                 ("PHerc0003", 10.0), ("PHerc0004", 5.0))
    cov = build_coverage(vols, Counter({"PHercParis4": 70}),
                         Counter({"PHercParis4": 169, "PHerc0002": 3}))
    assert cov[ROOT.format("PHercParis4")]["label_next"] is False
    assert cov[ROOT.format("PHercParis4")]["ink_labels"] == 70
    assert cov[ROOT.format("PHerc0002")]["segments"] == 3


def test_inventory_from_prior_coverage(tmp_path):
    prior = {ROOT.format("PHercParis4"): {"scroll": "PHercParis4",
                                         "ink_labels": 70, "segments": 169,
                                         "label_next": False}}
    p = tmp_path / "prior.json"
    p.write_text(json.dumps(prior))
    ink, surf = counts_from_coverage(str(p))
    assert ink["PHercParis4"] == 70 and surf["PHercParis4"] == 169


def test_inconsistent_prior_coverage_is_rejected(tmp_path):
    prior = {"a": {"scroll": "PHerc0001", "ink_labels": 1, "segments": 0},
             "b": {"scroll": "PHerc0001", "ink_labels": 2, "segments": 0}}
    p = tmp_path / "prior.json"
    p.write_text(json.dumps(prior))
    with pytest.raises(ValueError, match="inconsistent counts"):
        counts_from_coverage(str(p))


def test_cli_exits_nonzero_on_empty_inventory(tmp_path):
    roots = tmp_path / "roots.jsonl"
    roots.write_text(json.dumps({"root": "PHerc0001/volumes/x.zarr"}) + "\n")
    vols = tmp_path / "volumes.json"
    vols.write_text(json.dumps(_vols(("PHerc0001", 50.0))))
    out = tmp_path / "cov.json"
    r = subprocess.run([sys.executable, "-m", "scrollq.coverage",
                        "--s3-roots", str(roots), "--volumes", str(vols),
                        "--out", str(out)], capture_output=True, text=True)
    assert r.returncode != 0
    assert "refusing" in r.stderr
    assert not out.exists()
