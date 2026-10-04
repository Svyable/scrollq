import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ["fiber_gap_rule_eval.py", "paris4_fiber_ct_support.py", "paris4_fiber_ct_direction.py"]


def _load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    s = importlib.util.spec_from_file_location(name[:-3], ROOT / "scripts" / name)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


@pytest.mark.parametrize("runner", RUNNERS)
def test_every_registered_spec_matches_its_frozen_hash(runner):
    m = _load(runner)
    assert len(m.FROZEN_SPECS) >= 2
    for rel, sha in m.FROZEN_SPECS.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha, rel


@pytest.mark.parametrize("runner", RUNNERS)
def test_unregistered_spec_is_refused_before_any_read(runner, tmp_path):
    m = _load(runner)
    rogue = ROOT / "artifacts" / "_rogue_spec_for_test.json"
    rogue.write_text("{}")
    try:
        args = (tmp_path, rogue) if runner == "fiber_gap_rule_eval.py" else (tmp_path, 1, rogue)
        assert m.run(*args) == 3
    finally:
        rogue.unlink()
