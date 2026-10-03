from pathlib import Path
import subprocess
import sys


def test_sheetness_realdata_preregistration_is_reproducible():
    repo = Path(__file__).resolve().parents[1]
    script = repo / "artifacts/2026-10-03-sheetness-preregistration/derive.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
