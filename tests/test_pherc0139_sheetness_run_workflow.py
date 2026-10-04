from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pherc0139-sheetness-run.yml"
RUNNER = ROOT / "bin" / "run_pherc0139_sheetness_phase_a.py"


def test_pherc0139_sheetness_execution_is_frozen_and_create_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")

    assert 'python-version: "3.12.14"' in workflow
    assert "pherc0139-frozen-constraints.txt" in workflow
    assert "run_pherc0139_sheetness_phase_a.py --repo-root ." in workflow
    assert "sheetness-result.json" in workflow
    assert "Run frozen PHerc0139 Phase-A sheetness campaign" in workflow

    assert "artifacts/2026-10-03-pherc0139-sheetness-campaign/campaign-plan.json" in runner
    assert "frozen engine byte mismatch" in runner
    assert "package drift:" in runner
    assert "scroliq-ct-cutout" in runner
    assert "scroliq-sheetness-campaign" in runner
    assert "scroliq-sheetness-eval" in runner
    assert "failed_group_count" in runner
    assert "EXPECTED_GROUPS = 32" in runner

    # A negative scientific result must be retained rather than turning the
    # execution path into an optimizer for preregistered thresholds.
    assert "--require-pass" not in workflow
    assert "--require-pass" not in runner

    # There are no runtime scientific knobs: the runner accepts only repo-root.
    assert "--sigmas" not in RUNNER.read_text().split("def build_parser", 1)[1]
    assert "--beta" not in RUNNER.read_text().split("def build_parser", 1)[1]
    assert "--gamma" not in RUNNER.read_text().split("def build_parser", 1)[1]

    # workflow_dispatch intentionally has no inputs.
    dispatch_tail = workflow.split("workflow_dispatch:", 1)[1].split("permissions:", 1)[0]
    assert "inputs:" not in dispatch_tail


def test_pherc0139_sheetness_execution_hashes_final_bundle_after_metadata():
    runner = RUNNER.read_text(encoding="utf-8")
    readme = runner.index('(root / "README.md").write_text')
    environment = runner.index('(root / "environment.txt").write_text')
    hashes = runner.index('(root / "hashes.sha256").write_text')

    assert readme < environment < hashes


def test_pherc0139_sheetness_workflow_uses_narrow_campaign_push_trigger():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '"campaign/pherc0139-sheetness-phase-a-*"' in workflow
    assert '"artifacts/2026-10-03-pherc0139-sheetness-run/**"' in workflow
    assert "pull_request:" not in workflow
