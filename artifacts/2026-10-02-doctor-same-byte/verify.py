#!/usr/bin/env python3
"""Verify stable evidence from the same-byte TIFXYZ cross-validation campaign."""

from __future__ import annotations

import json
import sys
from pathlib import Path

VOLATILE = {"generated_utc", "scrollq_git_sha"}


def stable(value: dict) -> dict:
    return {key: item for key, item in value.items() if key not in VOLATILE}


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify.py ACTUAL.json EXPECTED.json")
    actual = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    expected = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    if stable(actual) != stable(expected):
        print("same-byte evidence drifted", file=sys.stderr)
        return 1

    for name, report in (("actual", actual), ("expected", expected)):
        summary = report["shared_topology_summary"]
        if summary["hole_presence_matches"] != summary["hole_presence_cases"]:
            raise SystemExit(f"{name}: hole-presence concordance is incomplete")
        if (
            summary["single_component_presence_matches"]
            != summary["single_component_presence_cases"]
        ):
            raise SystemExit(f"{name}: component-presence concordance is incomplete")
        if summary["mesh_iq_isometry_false_positive_candidates"]:
            raise SystemExit(f"{name}: calibrated isometry false-positive candidate remains")
        if not report["input_contract"]["every_file_verified_against_doctor_manifest_sha256"]:
            raise SystemExit(f"{name}: input SHA-256 verification was not complete")
        if not report.get("scrollq_git_sha"):
            raise SystemExit(f"{name}: missing ScrolIQ run commit")

    print("same-byte stable evidence matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
