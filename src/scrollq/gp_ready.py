"""Compile a Grand Prize evidence dossier from normalized tool reports.

Input is a dossier manifest naming the numbered column meshes and, for each,
the reports produced by internal and community tools; plus submission-level
reports. Output says, per column and per required check, whether passing
evidence exists that is bound to that exact mesh, and lists every blocker.
There is no score and no partial credit. See docs/gp-ready.md.

Manifest::

    {"schema_version": 1,
     "submission": "PHerc0800 First Letters candidate",
     "columns": [{"id": "column_01", "mesh": "meshes/column_01",
                  "evidence": [{"tool": "windcheck", "report": "…json"}]}],
     "submission_evidence": [{"tool": "spiralcheck", "report": "…json",
                              "subject": "fit/meshes"}]}

Relative paths resolve against the manifest's directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .evidence import BINDINGS, ingest

DOSSIER_SCHEMA = "scroliq-gp-dossier/1"

# Checks a column must pass. "planned" checks have no adapter yet; they are
# required anyway, so a dossier cannot look ready while they are unmeasured.
DEFAULT_POLICY: dict[str, Any] = {
    "policy_id": "scroliq-default-2026-10-02",
    "min_binding": "path-declared",
    "column_checks": [
        "mesh.tifxyz-contract",
        "mesh.scroliq-audit",
        "mesh.self-intersection",
        "mesh.flatten-distortion",
        "mesh.handedness",
        "ct.surface-support",
    ],
    "submission_checks": [
        "submission.provenance",
        "spiral.held-out",
    ],
    "planned_checks": {
        "mesh.handedness": "handcheck adapter (needs the volume's catalogue properties)",
        "ct.surface-support": "per-mesh CT support (scroliq-support is per-volume today)",
        "submission.provenance": "scroliq-provenance report adapter",
    },
    # Thresholds turn a "measured" record into pass/fail. None are declared by
    # default: choosing them is a published judgment call, like score weights.
    "thresholds": {},
}

_RANK = {"error": 4, "fail": 3, "caution": 2, "measured": 1, "pass": 0}
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b, "<": lambda a, b: a < b}


def _apply_thresholds(rec: dict, thresholds: dict) -> dict:
    rules = thresholds.get(rec["check"])
    if rec["status"] != "measured" or not rules:
        return rec
    failed = []
    for metric, (op, bound) in rules.items():
        value = rec["metrics"].get(metric)
        if not isinstance(value, (int, float)) or not _OPS[op](value, bound):
            failed.append(f"{metric} {value!r} not {op} {bound}")
    rec = {**rec, "status": "fail" if failed else "pass",
           "verdict_source": "policy", "notes": rec["notes"] + failed}
    return rec


def _judge(check: str, records: list[dict], policy: dict) -> dict:
    """One required check: pass only if every record for it passes at or
    above the policy's minimum binding."""
    if not records:
        planned = policy.get("planned_checks", {}).get(check)
        return {"check": check, "status": "missing",
                "reason": f"no adapter yet: {planned}" if planned else "no evidence supplied",
                "records": []}
    floor = BINDINGS.index(policy["min_binding"])
    worst = max(records, key=lambda r: _RANK[r["status"]])
    if worst["status"] != "pass":
        return {"check": check, "status": worst["status"],
                "reason": f"{worst['source']['tool']}: {worst['status']}",
                "records": records}
    weak = [r for r in records if BINDINGS.index(r["binding"]) > floor]
    if weak:
        return {"check": check, "status": "binding-too-weak",
                "reason": ", ".join(f"{r['source']['tool']}: {r['binding']}" for r in weak),
                "records": records}
    bindings = sorted({r["binding"] for r in records}, key=BINDINGS.index)
    return {"check": check, "status": "pass", "reason": "; ".join(bindings),
            "records": records}


def _collect(entries: list[dict], base: Path, *, subject_id, mesh_dir, thresholds):
    recs = []
    for e in entries:
        report = (base / e["report"]) if not Path(e["report"]).is_absolute() else Path(e["report"])
        subject = mesh_dir
        if subject is None and e.get("subject"):
            # Submission-level evidence may name the artifact it is about
            # (e.g. a spiral-fit output directory) so path binding can apply.
            subject = base / e["subject"] if not Path(e["subject"]).is_absolute() else Path(e["subject"])
        for r in ingest(e["tool"], report, subject_id=subject_id, mesh_dir=subject):
            recs.append(_apply_thresholds(r, thresholds))
    return recs


def _section(required: list[str], recs: list[dict], policy: dict) -> dict:
    by_check: dict[str, list[dict]] = {}
    for r in recs:
        by_check.setdefault(r["check"], []).append(r)
    checks = [_judge(c, by_check.get(c, []), policy) for c in required]
    extra = sorted(set(by_check) - set(required))
    return {
        "ready": all(c["status"] == "pass" for c in checks),
        "blockers": [f"{c['check']}: {c['status']} ({c['reason']})"
                     for c in checks if c["status"] != "pass"],
        "checks": checks,
        "informational": [r for c in extra for r in by_check[c]],
    }


def compile_dossier(manifest: dict, base: Path, policy: dict | None = None) -> dict:
    policy = policy or DEFAULT_POLICY
    thresholds = policy.get("thresholds", {})
    columns = []
    for col in manifest.get("columns", []):
        mesh = col["mesh"]
        mesh_dir = (base / mesh) if not Path(mesh).is_absolute() else Path(mesh)
        recs = _collect(col.get("evidence", []), base, subject_id=col["id"],
                        mesh_dir=mesh_dir, thresholds=thresholds)
        columns.append({"id": col["id"], "mesh": mesh,
                        **_section(policy["column_checks"], recs, policy)})
    sub_recs = _collect(manifest.get("submission_evidence", []), base,
                        subject_id=manifest.get("submission"), mesh_dir=None,
                        thresholds=thresholds)
    submission = _section(policy["submission_checks"], sub_recs, policy)
    policy_sha = hashlib.sha256(
        json.dumps(policy, sort_keys=True).encode()).hexdigest()
    return {
        "schema": DOSSIER_SCHEMA,
        "submission": manifest.get("submission"),
        "policy": policy,
        "policy_sha256": policy_sha,
        "ready": bool(columns) and submission["ready"] and all(c["ready"] for c in columns),
        "columns_ready": sum(c["ready"] for c in columns),
        "columns_total": len(columns),
        "submission_checks": submission,
        "columns": columns,
        "claim_boundary": (
            "A ready dossier means every required check has bound, passing "
            "evidence. It does not establish legibility, sheet identity or "
            "prize eligibility; reviewers decide those."
        ),
    }


def summary_markdown(d: dict) -> str:
    lines = [f"# GP dossier: {d['submission']}", "",
             f"Ready: **{d['ready']}** — columns ready {d['columns_ready']} / "
             f"{d['columns_total']} (policy `{d['policy']['policy_id']}`, "
             f"sha256 `{d['policy_sha256'][:12]}`)", ""]
    checks = d["policy"]["column_checks"]
    lines.append("| column | " + " | ".join(checks) + " |")
    lines.append("|---|" + "---|" * len(checks))
    for c in d["columns"]:
        cells = [next(x["status"] for x in c["checks"] if x["check"] == k) for k in checks]
        lines.append(f"| {c['id']} | " + " | ".join(cells) + " |")
    lines += ["", "Submission-level blockers:"]
    lines += [f"- {b}" for b in d["submission_checks"]["blockers"]] or ["- none"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Compile a Grand Prize evidence dossier.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--policy", help="policy JSON (default: built-in DEFAULT_POLICY)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown", help="optional human-readable summary")
    ap.add_argument("--fail-unless-ready", action="store_true")
    a = ap.parse_args(argv)
    mpath = Path(a.manifest)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    policy = json.loads(Path(a.policy).read_text(encoding="utf-8")) if a.policy else None
    dossier = compile_dossier(manifest, mpath.parent, policy)
    Path(a.out).write_text(json.dumps(dossier, indent=1) + "\n", encoding="utf-8")
    if a.markdown:
        Path(a.markdown).write_text(summary_markdown(dossier), encoding="utf-8")
    print(f"ready={dossier['ready']} columns {dossier['columns_ready']}/"
          f"{dossier['columns_total']}")
    if a.fail_unless_ready and not dossier["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
