#!/usr/bin/env python3
"""Execute the frozen PHerc0139 Phase-A sheetness campaign exactly once.

This is execution plumbing for issue #105, not a parameter-selection surface.
All scientific choices are read from the already-frozen campaign plan.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
from pathlib import Path

PLAN = Path("artifacts/2026-10-03-pherc0139-sheetness-campaign/campaign-plan.json")
ZPA = Path("artifacts/2026-10-03-pherc0139-sheetness-prereg/zpa.json")
FROZEN_ENV = Path("artifacts/2026-10-03-pherc0139-sheetness-campaign/environment.txt")
OUTDIR = Path("artifacts/2026-10-03-pherc0139-sheetness-run")
EXPECTED_SCHEMA = "scroliq-sheetness-campaign/1"
RESULT_SCHEMA = "scroliq-sheetness-campaign-result/1"
EXPECTED_GROUPS = 32
EXPECTED_PYTHON = "3.12.14"
PUBLIC_CT_BASE = "https://vesuvius-challenge-open-data.s3.amazonaws.com"


class ExecutionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExecutionError(f"{path} must contain a JSON object")
    return value


def verify_frozen_execution_fence(repo_root: Path) -> dict:
    plan = _load_json(repo_root / PLAN)
    if plan.get("schema") != EXPECTED_SCHEMA:
        raise ExecutionError("unexpected campaign schema")
    if plan.get("status") != "frozen-before-sheetness":
        raise ExecutionError("campaign is not frozen-before-sheetness")
    summary = plan.get("summary", {})
    if summary.get("group_count") != EXPECTED_GROUPS:
        raise ExecutionError("campaign group count changed")
    if summary.get("ready_group_count") != EXPECTED_GROUPS:
        raise ExecutionError("not all frozen groups are ready")

    engine = plan.get("engine")
    if not isinstance(engine, dict):
        raise ExecutionError("campaign engine is missing")
    expected = {
        "src/scrollq/sheetness.py": engine["sheetness_py_sha256"],
        "src/scrollq/sheetness_benchmark.py": engine["sheetness_benchmark_py_sha256"],
        "src/scrollq/sheetness_campaign.py": engine["sheetness_campaign_py_sha256"],
    }
    for rel, want in expected.items():
        got = _sha256(repo_root / rel)
        if got != want:
            raise ExecutionError(
                f"frozen engine byte mismatch: {rel}: {got} != {want}"
            )

    if platform.python_version() != EXPECTED_PYTHON:
        raise ExecutionError(
            f"Python drift: {platform.python_version()} != {EXPECTED_PYTHON}"
        )

    frozen: dict[str, str] = {}
    for raw in (repo_root / FROZEN_ENV).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", raw.strip())
        if match:
            frozen[match.group(1).lower().replace("_", "-")] = match.group(2)
    if not frozen:
        raise ExecutionError("frozen environment contains no exact package pins")

    for name, want in sorted(frozen.items()):
        try:
            got = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ExecutionError(f"frozen package missing: {name}=={want}") from exc
        if got != want:
            raise ExecutionError(f"package drift: {name} {got} != {want}")

    return plan


def _run(cmd: list[str | Path], *, cwd: Path, log_path: Path) -> None:
    rendered = [str(value) for value in cmd]
    with log_path.open("a", encoding="utf-8") as log:
        log.write("$ " + " ".join(rendered) + "\n")
        proc = subprocess.run(
            rendered,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            log.write("\n")
        log.flush()
    if proc.returncode != 0:
        raise ExecutionError(
            f"command failed ({proc.returncode}): {' '.join(rendered)}"
        )


def execute(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    plan = verify_frozen_execution_fence(repo_root)
    outdir = repo_root / OUTDIR
    result_path = outdir / "sheetness-result.json"
    if result_path.exists():
        raise ExecutionError(f"refusing to overwrite frozen result: {result_path}")

    groups_dir = outdir / "groups"
    specs_dir = outdir / "specs"
    results_dir = outdir / "results"
    for path in (groups_dir, specs_dir, results_dir):
        path.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "run.log"

    volume_root = plan["volume_root"]
    ct_url = f"{PUBLIC_CT_BASE}/{volume_root}"
    engine = plan["engine"]
    params = engine["parameters"]
    normalization = engine["normalization"]

    for index, group in enumerate(plan["groups"], start=1):
        if group.get("status") != "ready":
            raise ExecutionError(f"group {group.get('id')} is no longer ready")
        gid = group["id"]
        bbox = group["bbox_zyx_half_open"]
        start = ",".join(str(v) for v in bbox["start"])
        stop = ",".join(str(v) for v in bbox["stop"])
        gdir = groups_dir / gid
        gdir.mkdir(parents=True, exist_ok=True)
        cutout = gdir / "cutout.npy"
        manifest = gdir / "cutout.json"
        prefix = gdir / "sheetness"

        print(f"[{index:02d}/{EXPECTED_GROUPS}] {gid}: extract", flush=True)
        _run(
            [
                "scroliq-ct-cutout",
                "--ct-url", ct_url,
                "--volume-root", volume_root,
                "--zpa-report", repo_root / ZPA,
                "--start", start,
                "--stop", stop,
                "--out", cutout,
                "--manifest", manifest,
            ],
            cwd=repo_root,
            log_path=log_path,
        )

        print(f"[{index:02d}/{EXPECTED_GROUPS}] {gid}: sheetness", flush=True)
        sheetness_cmd: list[str | Path] = [
            "scroliq-sheetness",
            cutout,
            "--out-prefix", prefix,
            "--sigmas", ",".join(str(v) for v in params["sigmas"]),
            "--beta", str(params["beta"]),
            "--gamma", str(params["gamma"]),
            "--bright-object" if params["bright_object"] else "--dark-object",
            "--normalize-low", str(normalization["lower_percentile"]),
            "--normalize-high", str(normalization["upper_percentile"]),
            "--write-normal",
            "--max-voxels", str(engine["max_voxels"]),
        ]
        if params["scale_objectness"]:
            sheetness_cmd.append("--scale-objectness")
        if not normalization["enabled"]:
            sheetness_cmd.append("--no-normalize")
        _run(sheetness_cmd, cwd=repo_root, log_path=log_path)

        report = Path(str(prefix) + ".sheetness.json")
        response = Path(str(prefix) + ".sheetness.npy")
        normal = Path(str(prefix) + ".normal-zyx.npy")
        spec = specs_dir / f"{gid}.json"
        result = results_dir / f"{gid}.json"

        print(f"[{index:02d}/{EXPECTED_GROUPS}] {gid}: seal + evaluate", flush=True)
        _run(
            [
                "scroliq-sheetness-campaign", "seal-group",
                "--plan", repo_root / PLAN,
                "--group-id", gid,
                "--cutout-manifest", manifest,
                "--sheetness-report", report,
                "--out", spec,
            ],
            cwd=repo_root,
            log_path=log_path,
        )
        _run(
            [
                "scroliq-sheetness-eval",
                "--spec", spec,
                "--cutout-manifest", manifest,
                "--report", report,
                "--response", response,
                "--normal", normal,
                "--out", result,
            ],
            cwd=repo_root,
            log_path=log_path,
        )

    _run(
        [
            "scroliq-sheetness-campaign", "aggregate",
            "--plan", repo_root / PLAN,
            "--specs-dir", specs_dir,
            "--results-dir", results_dir,
            "--out", result_path,
        ],
        cwd=repo_root,
        log_path=log_path,
    )

    result = _load_json(result_path)
    metrics = result.get("metrics", {})
    if result.get("schema") != RESULT_SCHEMA:
        raise ExecutionError("aggregate schema mismatch")
    if metrics.get("group_count") != EXPECTED_GROUPS:
        raise ExecutionError("aggregate lost frozen groups")
    if metrics.get("failed_group_count") != 0:
        raise ExecutionError(
            "execution produced invalid/missing groups; this is not a scientific negative"
        )
    if result.get("status") not in {"pass", "fail"}:
        raise ExecutionError("aggregate status is neither pass nor fail")

    print("Phase-A scientific result:", result["status"].upper(), flush=True)
    print(json.dumps(metrics, indent=2, sort_keys=True), flush=True)
    return result


def write_bundle_metadata(repo_root: Path, result: dict) -> None:
    repo_root = repo_root.resolve()
    root = repo_root / OUTDIR
    metrics = result["metrics"]
    status = result["status"].upper()
    readme = f"""# PHerc0139 Phase-A sheetness result — 2026-10-03

**Frozen scientific result: {status}.**

This directory is the create-only execution of the preregistered campaign in
`artifacts/2026-10-03-pherc0139-sheetness-campaign/campaign-plan.json`.
No probe, bbox, engine parameter, normalization setting, or decision threshold
was changed after the campaign freeze.

Measured groups: **{metrics['group_count']} / {EXPECTED_GROUPS}**.
Normal-offset wins: **{metrics['normal_offset_win_count']} / {EXPECTED_GROUPS}**
({metrics['normal_offset_win_fraction']:.3f}).
Median surface-minus-best-offset margin:
**{metrics['median_surface_minus_best_normal_offset']}**.
Normal completeness: **{metrics['normal_completeness']:.3f}**.
Median absolute normal cosine: **{metrics['median_abs_cosine']}**.
Wrong-wrap wins (descriptive only):
**{metrics['wrong_wrap_win_count_descriptive']} / {EXPECTED_GROUPS}**.

A FAIL here is a valid negative scientific result and must not be retuned into
PASS under this campaign identity. Invalid or missing groups are execution
failures and are not published as a scientific negative.

The result tests local physical sheet localization only. Even PASS would not
establish winding identity, topology, recto coverage, ink, readable text, or
Grand Prize readiness.
"""
    (root / "README.md").write_text(readme, encoding="utf-8")

    freeze = subprocess.run(
        ["python", "-m", "pip", "freeze"],
        cwd=repo_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    (root / "environment.txt").write_text(
        f"{head}\nPython {platform.python_version()}\n{freeze}",
        encoding="utf-8",
    )

    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "hashes.sha256":
            rel = path.relative_to(root).as_posix()
            entries.append(f"{_sha256(path)}  {rel}")
    (root / "hashes.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        default=".",
        help="repository root; no scientific configuration is accepted at runtime",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        root = Path(args.repo_root)
        result = execute(root)
        write_bundle_metadata(root, result)
    except (ExecutionError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PHerc0139 Phase-A execution failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
