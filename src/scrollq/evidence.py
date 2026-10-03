"""Normalize internal and community tool reports into ScrolIQ evidence records.

Each adapter is written against real output of a pinned tool commit (see
``tests/fixtures/evidence/``) and turns one report into evidence records:

    {"check", "subject", "source", "binding", "status", "verdict_source",
     "metrics", "notes"}

Statuses: pass, fail, caution, measured, error. ``measured`` means the tool
reports numbers but no verdict; it is never promoted to ``pass`` here. A
policy threshold can do that later in ``scrollq.gp_ready``.

Bindings use the same classes as ``scrollq.external_mesh_evidence``, compared
against the mesh files on disk: ``semantic-exact`` (coordinate, mask and
meta.json hashes match), ``coordinate-exact`` (x/y/z and mask hashes match),
``path-grid`` (path and grid shape agree, no hashes), ``path-only``,
``unbound``. Hashes that contradict the files give ``mismatch`` and make the
record ``error``: the report is about another version of the mesh.

See docs/gp-ready.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import tifffile

from .external_mesh_evidence import _compare_hashes

SCHEMA = "scroliq-evidence/1"
STATUSES = ("pass", "fail", "caution", "measured", "error")
# Strongest first; "mismatch" is not a binding a check can pass at.
BINDINGS = ("semantic-exact", "coordinate-exact", "path-grid", "path-only",
            "unbound", "mismatch")
MESH_FILES = ("x.tif", "y.tif", "z.tif")

# Tool commits each adapter was written and tested against.
PINNED = {
    "windcheck": "2b0fb2f3d305d3727dcb24a8eaa73c3c8ce5c3ce",
    "flatcheck": "948a19d102ed5d623de8958bf53707c0bf7cdfc6",
    "tifxyz-doctor": "5ca0444fb31863c8e02466316bf9e560cf567876",
    "tifxyz-repair": "4d6c98d95b71aa94dfed9398fbfe592419e62763",
    "spiralcheck": "d1b50e2957",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def mesh_hashes(mesh_dir: Path) -> dict[str, str]:
    """SHA-256 of the tifxyz coordinate files, plus mask/meta when present."""
    out = {name: sha256_file(mesh_dir / name) for name in MESH_FILES}
    for extra in ("mask.tif", "meta.json"):
        if (mesh_dir / extra).is_file():
            out[extra] = sha256_file(mesh_dir / extra)
    return out


def _local_identity(mesh_dir: Path) -> dict[str, Any]:
    """The audited files, in the shape external_mesh_evidence compares."""
    h = mesh_hashes(mesh_dir)
    return {"status": "bound",
            "coordinates": {name[0]: h[name] for name in MESH_FILES},
            "mask": h.get("mask.tif"), "meta": h.get("meta.json")}


def _grid_shape(mesh_dir: Path) -> list[int] | None:
    try:
        with tifffile.TiffFile(mesh_dir / "x.tif") as tif:
            return list(tif.pages[0].shape)
    except Exception:  # unreadable grid: no grid evidence, not a crash
        return None


def _same_dir(declared: Any, mesh_dir: Path, report_dir: Path) -> bool:
    """Does a path recorded in a report resolve to the audited mesh directory?"""
    if not isinstance(declared, str) or not declared:
        return False
    p = Path(declared)
    candidates = [p] if p.is_absolute() else [Path.cwd() / p, report_dir / p]
    target = mesh_dir.resolve()
    if any(c.resolve() == target for c in candidates if c.exists()):
        return True
    # Reports written elsewhere keep relative paths; accept a matching tail.
    tail = Path(*target.parts[-len(p.parts):]) if len(p.parts) <= len(target.parts) else None
    return tail is not None and tail == p


def _binding(recorded: dict | None, declared_path: Any, declared_grid: Any,
             mesh_dir: Path | None, report_dir: Path) -> tuple[str, str | None]:
    """(binding, error) for a report about ``mesh_dir``.

    ``recorded`` uses external_mesh_evidence's hash map: x, y, z, mask and an
    optional "meta" (meta.json SHA-256).
    """
    if mesh_dir is None:
        return "unbound", None
    if recorded and mesh_dir.is_dir():
        cmp = _compare_hashes(_local_identity(mesh_dir), recorded,
                              external_meta_sha256=recorded.get("meta"))
        if cmp["level"] == "mismatch":
            return "mismatch", f"recorded hashes differ from audited files: {cmp['reason']}"
        if cmp["level"] != "unbound":
            return cmp["level"], None
    if _same_dir(declared_path, mesh_dir, report_dir):
        if declared_grid is not None and list(declared_grid) == _grid_shape(mesh_dir):
            return "path-grid", None
        return "path-only", None
    return "unbound", None


def _record(check, status, verdict_source, metrics, notes=()):
    assert status in STATUSES, status
    return {"check": check, "status": status, "verdict_source": verdict_source,
            "metrics": metrics, "notes": list(notes)}


# --- adapters: report -> (records, recorded_hashes, declared_path, grid_yx, version)

def _windcheck(rep: dict) -> tuple:
    if rep.get("schema") != "windcheck_check/v1":
        raise ValueError(f"unsupported windcheck schema {rep.get('schema')!r}")
    hashes = rep["mesh"]["hashes"]
    recorded = {k: hashes.get(k) for k in ("x", "y", "z", "mask")}
    sites = rep.get("crossing_sites") or []
    status = "pass" if rep.get("clean") is True else "fail"
    rec = _record("mesh.self-intersection", status, "tool",
                  {"crossing_sites": len(sites),
                   "n_valid_vertices": rep["mesh"].get("n_valid_vertices")},
                  [rep.get("verdict", "")])
    return [rec], recorded, rep["mesh"].get("path"), rep["mesh"].get("grid_shape"), \
        rep.get("provenance", {}).get("code_version")


def _flatcheck(rep: dict) -> tuple:
    results = rep.get("results")
    if not isinstance(results, dict) or "mesh" not in rep:
        raise ValueError("not a flatcheck report")
    # "grid" is the parametrization stored in the tifxyz itself; prefer
    # "given_uv" when the caller audited an explicit UV map.
    method = "given_uv" if "given_uv" in results else "grid"
    r = results[method]
    collapsed = bool((r.get("collapse") or {}).get("collapsed"))
    ok = r.get("passes_bar") is True and r.get("fold_overs") == 0 and not collapsed
    rec = _record("mesh.flatten-distortion", "pass" if ok else "fail", "tool",
                  {"method": method,
                   "pct_quads_within_5pct": r.get("pct_quads_within_5pct"),
                   "bar_pct": r.get("bar_pct"),
                   "fold_overs": r.get("fold_overs"),
                   "collapsed": collapsed})
    return [rec], None, rep.get("mesh"), rep.get("grid_shape"), None


_SEVERITY = {"ok": "pass", "info": "pass", "warning": "caution", "error": "fail"}


def _tifxyz_doctor(rep: dict) -> tuple:
    contract = rep.get("contract") or {}
    if contract.get("schema_version") != "tifxyz-integrity-v1":
        raise ValueError("unsupported tifxyz-doctor contract schema")
    status = _SEVERITY.get(contract.get("status"), "error")
    recs = [_record("mesh.tifxyz-contract", status, "tool",
                    dict(contract.get("summary") or {}),
                    [f"{f['severity']}: {f['code']}" for f in contract.get("findings", [])])]
    cues = [f for f in rep.get("findings", []) if f.get("level") == "review"]
    recs.append(_record("mesh.geometry-review-cues",
                        "caution" if cues else "pass", "tool",
                        {"review_cues": len(cues)},
                        [f"{f['code']}: {f.get('message', '')}" for f in cues]))
    shape = (contract.get("coordinates") or {}).get("shape")
    return recs, None, (rep.get("source") or {}).get("path"), \
        shape[:2] if isinstance(shape, list) else None, \
        (rep.get("tool") or {}).get("version")


def _tifxyz_repair(rep) -> tuple:
    rows = rep if isinstance(rep, list) else [rep]
    if len(rows) != 1 or "status" not in rows[0] or "findings" not in rows[0]:
        raise ValueError("expected one tifxyz-repair validate result")
    row = rows[0]
    status = _SEVERITY.get(row["status"], "error")
    rec = _record("mesh.tifxyz-contract", status, "tool",
                  {"findings": len(row["findings"])},
                  [f"{f['severity']}: {f['check']}: {f['message']}" for f in row["findings"]])
    return [rec], None, row.get("path"), None, None


def _scroliq_mesh(rep: dict) -> tuple:
    if rep.get("diagnostic") != "tifxyz-mesh-audit":
        raise ValueError("not a scroliq-mesh report")
    status = {"pass": "pass", "partial": "caution", "fail": "fail"}.get(
        rep.get("status"), "error")
    prov = rep.get("provenance") or {}
    recorded = {k[0]: (prov.get(k) or {}).get("sha256") for k in MESH_FILES}
    recorded["mask"] = (prov.get("mask.tif") or {}).get("sha256")
    recorded["meta"] = (prov.get("meta.json") or {}).get("sha256")
    rec = _record("mesh.scroliq-audit", status, "tool",
                  {"errors": rep.get("error_count"), "warnings": rep.get("warning_count")},
                  list(rep.get("errors", [])) + list(rep.get("warnings", [])))
    return [rec], recorded, rep.get("tifxyz_path"), \
        (rep.get("grid") or {}).get("shape_yx"), None


def _spiralcheck(rep: dict) -> tuple:
    meta = rep.get("meta") or {}
    if "spiralcheck" not in meta or "heldout_aggregate" not in rep:
        raise ValueError("not a spiralcheck report")
    agg = rep["heldout_aggregate"]
    leak = agg.get("evidence_leakage") or {}
    unseen = agg.get("unseen") or {}
    rec = _record("spiral.held-out", "measured", "none",
                  {"n_patches": agg.get("n_patches"),
                   "frac_within_tau": agg.get("frac_within_tau"),
                   "tau": agg.get("tau"),
                   "dist_p90": agg.get("dist_p90"),
                   "leakage_frac_within_2_vox": leak.get("frac_within_2_vox"),
                   "unseen_frac_within_tau": unseen.get("frac_within_tau")},
                  ["spiralcheck reports held-out distances, not a verdict"])
    return [rec], None, meta.get("meshes"), None, meta.get("spiralcheck")


ADAPTERS: dict[str, Callable[[Any], tuple]] = {
    "windcheck": _windcheck,
    "flatcheck": _flatcheck,
    "tifxyz-doctor": _tifxyz_doctor,
    "tifxyz-repair": _tifxyz_repair,
    "scroliq-mesh": _scroliq_mesh,
    "spiralcheck": _spiralcheck,
}


def ingest(tool: str, report_path: str | Path, *, subject_id: str | None = None,
           mesh_dir: str | Path | None = None) -> list[dict]:
    """Evidence records for one report. Never raises on bad input: a report
    that cannot be read or bound becomes an ``error`` record."""
    report_path = Path(report_path)
    mesh = Path(mesh_dir) if mesh_dir is not None else None
    source = {"tool": tool, "pinned_commit": PINNED.get(tool),
              "report_path": str(report_path), "report_sha256": None,
              "tool_version": None}
    subject = {"kind": "mesh" if mesh else "submission", "id": subject_id,
               "path": str(mesh) if mesh else None}

    def wrap(recs, binding):
        return [{"schema": SCHEMA, "subject": subject, "source": source,
                 "binding": binding, **r} for r in recs]

    if tool not in ADAPTERS:
        return wrap([_record(f"unknown.{tool}", "error", "none", {},
                             [f"no adapter for {tool!r}"])], "unbound")
    try:
        raw = report_path.read_bytes()
        source["report_sha256"] = hashlib.sha256(raw).hexdigest()
        recs, recorded, declared, grid, version = ADAPTERS[tool](json.loads(raw))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return wrap([_record(f"report.{tool}", "error", "none", {},
                             [f"{type(exc).__name__}: {exc}"])], "unbound")
    source["tool_version"] = version
    binding, problem = _binding(recorded, declared, grid, mesh, report_path.parent)
    if problem:
        for r in recs:
            r["status"], r["verdict_source"] = "error", "none"
            r["notes"].append(problem)
    return wrap(recs, binding)
