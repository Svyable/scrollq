from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pherc0139-sheetness-run.yml"


def test_pherc0139_sheetness_execution_is_frozen_and_create_only():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'python-version: "3.12.14"' in text
    assert "artifacts/2026-10-03-pherc0139-sheetness-campaign/campaign-plan.json" in text
    assert "frozen engine byte mismatch" in text
    assert "package drift:" in text
    assert "scroliq-ct-cutout" in text
    assert "scroliq-sheetness-campaign" in text
    assert "scroliq-sheetness-eval" in text
    assert "sheetness-result.json" in text
    assert "failed_group_count" in text
    assert "Run frozen PHerc0139 Phase-A sheetness campaign" in text

    # A negative scientific result must be retained rather than turning the
    # workflow into an optimizer for the preregistered thresholds.
    assert "--require-pass" not in text

    # workflow_dispatch intentionally has no inputs: there is no runtime knob
    # for sigmas, polarity, probes, bboxes, normalization, or thresholds.
    dispatch_tail = text.split("workflow_dispatch:", 1)[1].split("permissions:", 1)[0]
    assert "inputs:" not in dispatch_tail


def test_pherc0139_sheetness_execution_hashes_final_bundle_last():
    text = WORKFLOW.read_text(encoding="utf-8")
    readme = text.index('(root / "README.md").write_text')
    hashes = text.index('find . -type f ! -name hashes.sha256')
    commit = text.index("git add artifacts/2026-10-03-pherc0139-sheetness-run")

    assert readme < hashes < commit
