"""End-to-end, fail-closed dry run of the Grand Prize reviewer package.

This command deliberately reuses the production package builder twice, then
runs the production verifier on both archives. It is an orchestration check:
it does not create scientific evidence or relax any underlying gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .submission_package import PackageError, build_package, verify_package

SCHEMA_VERSION = 1
TOOL = "scroliq-submission-dry-run"


def _build_kwargs(
    *,
    manifest_path: str | Path,
    root_dir: str | Path,
    methodology_path: str,
    system_requirements_path: str,
    human_input_log_path: str,
    vc3d_workflow_path: str,
    false_positive_mitigation_path: str,
    legibility_ledger_path: str,
    docker_run_command: str,
) -> dict[str, Any]:
    return {
        "manifest_path": manifest_path,
        "root_dir": root_dir,
        "methodology_path": methodology_path,
        "system_requirements_path": system_requirements_path,
        "human_input_log_path": human_input_log_path,
        "vc3d_workflow_path": vc3d_workflow_path,
        "false_positive_mitigation_path": false_positive_mitigation_path,
        "legibility_ledger_path": legibility_ledger_path,
        "docker_run_command": docker_run_command,
    }


def _failed_report(
    report: dict[str, Any],
    *,
    stage: str,
    message: str,
) -> dict[str, Any]:
    report["passed"] = False
    report["failure_stage"] = stage
    report["errors"].append(message)
    return report


def run_dry_run(
    *,
    manifest_path: str | Path,
    root_dir: str | Path,
    methodology_path: str = "METHODOLOGY.md",
    system_requirements_path: str = "SYSTEM_REQUIREMENTS.md",
    human_input_log_path: str = "human-input.json",
    vc3d_workflow_path: str = "VC3D_WORKFLOW.md",
    false_positive_mitigation_path: str = "FALSE_POSITIVES.md",
    legibility_ledger_path: str = "legibility.json",
    docker_run_command: str,
) -> dict[str, Any]:
    """Build twice in isolation and independently verify both packages."""

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "passed": False,
        "failure_stage": None,
        "inputs": {
            "manifest": str(manifest_path),
            "root_dir": str(root_dir),
            "methodology": methodology_path,
            "system_requirements": system_requirements_path,
            "human_input_log": human_input_log_path,
            "vc3d_workflow": vc3d_workflow_path,
            "false_positive_mitigation": false_positive_mitigation_path,
            "legibility_ledger": legibility_ledger_path,
        },
        "builds": [],
        "deterministic_rebuild": None,
        "errors": [],
        "scope_note": (
            "PASS means the current staging tree survives the production Grand Prize "
            "package builder twice, produces byte-identical deterministic archives, "
            "and both archives pass the production self-contained verifier. It does "
            "not prove surface correctness, biological ink identity, papyrological "
            "legibility, whole-scroll completeness beyond the supplied evidence, or "
            "Grand Prize eligibility outside the encoded provenance contract."
        ),
    }

    kwargs = _build_kwargs(
        manifest_path=manifest_path,
        root_dir=root_dir,
        methodology_path=methodology_path,
        system_requirements_path=system_requirements_path,
        human_input_log_path=human_input_log_path,
        vc3d_workflow_path=vc3d_workflow_path,
        false_positive_mitigation_path=false_positive_mitigation_path,
        legibility_ledger_path=legibility_ledger_path,
        docker_run_command=docker_run_command,
    )

    with tempfile.TemporaryDirectory(prefix="scroliq-submission-dry-run-") as raw_tmp:
        tmp = Path(raw_tmp)
        build_results: list[dict[str, Any]] = []

        for ordinal in (1, 2):
            archive = tmp / f"build-{ordinal}.zip"
            try:
                built = build_package(
                    **kwargs,
                    out_path=archive,
                )
            except (OSError, PackageError, ValueError) as exc:
                return _failed_report(
                    report,
                    stage=f"build-{ordinal}",
                    message=str(exc),
                )

            try:
                verified = verify_package(archive)
            except (OSError, PackageError, ValueError) as exc:
                return _failed_report(
                    report,
                    stage=f"verify-{ordinal}",
                    message=str(exc),
                )

            row = {
                "ordinal": ordinal,
                "archive_sha256": built.get("archive_sha256"),
                "manifest_sha256": built.get("manifest_sha256"),
                "graph_sha256": built.get("graph_sha256"),
                "file_count": built.get("file_count"),
                "verified": verified.get("valid") is True,
                "verification_errors": list(verified.get("errors") or []),
            }
            report["builds"].append(row)
            build_results.append(built)

            if verified.get("valid") is not True:
                return _failed_report(
                    report,
                    stage=f"verify-{ordinal}",
                    message=(
                        "; ".join(str(x) for x in verified.get("errors", [])[:8])
                        or "package verifier returned invalid without an error message"
                    ),
                )

        first_sha = build_results[0].get("archive_sha256")
        second_sha = build_results[1].get("archive_sha256")
        deterministic = (
            isinstance(first_sha, str)
            and bool(first_sha)
            and first_sha == second_sha
        )
        report["deterministic_rebuild"] = {
            "passed": deterministic,
            "first_archive_sha256": first_sha,
            "second_archive_sha256": second_sha,
        }
        if not deterministic:
            return _failed_report(
                report,
                stage="deterministic-rebuild",
                message="two isolated package builds produced different archive SHA-256 digests",
            )

        first = build_results[0]
        second = build_results[1]
        for key in ("manifest_sha256", "graph_sha256", "file_count"):
            if first.get(key) != second.get(key):
                return _failed_report(
                    report,
                    stage="deterministic-rebuild",
                    message=f"two isolated package builds disagree on {key}",
                )

    report["passed"] = True
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root-dir", required=True)
    parser.add_argument("--methodology", required=True)
    parser.add_argument("--system-requirements", required=True)
    parser.add_argument("--human-input-log", required=True)
    parser.add_argument("--vc3d-workflow", required=True)
    parser.add_argument("--false-positive-mitigation", required=True)
    parser.add_argument("--legibility-ledger", required=True)
    parser.add_argument(
        "--docker-run-command",
        required=True,
        help="copy-paste reproduction command using the manifest's digest-pinned image",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="create-only JSON receipt for the dry run",
    )
    args = parser.parse_args(argv)

    if args.out.exists():
        print(
            f"{TOOL}: refusing to overwrite existing report: {args.out}",
            file=sys.stderr,
        )
        return 2

    report = run_dry_run(
        manifest_path=args.manifest,
        root_dir=args.root_dir,
        methodology_path=args.methodology,
        system_requirements_path=args.system_requirements,
        human_input_log_path=args.human_input_log,
        vc3d_workflow_path=args.vc3d_workflow,
        false_positive_mitigation_path=args.false_positive_mitigation,
        legibility_ledger_path=args.legibility_ledger,
        docker_run_command=args.docker_run_command,
    )
    try:
        _write_report(args.out, report)
    except OSError as exc:
        print(f"{TOOL}: cannot write report: {exc}", file=sys.stderr)
        return 2

    verdict = "PASS" if report["passed"] else "FAIL"
    print(f"{TOOL}: {verdict}")
    if report.get("failure_stage"):
        print(f"failure stage: {report['failure_stage']}")
    for error in report.get("errors", []):
        print(f"- {error}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
