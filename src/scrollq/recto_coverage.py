"""Audit declared 2027 Grand Prize recto-surface coverage accounting.

This is a fail-closed bookkeeping/evidence audit. It can prove that a declared
reference surface inventory is completely accounted for by submitted meshes or
by the narrow permitted disconnected-outer-patch exclusion. It cannot discover
papyrus that is absent from the reference inventory.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

DIAGNOSTIC = "recto-coverage-audit"
SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENT_KINDS = {
    "main-sheet",
    "attached-patch",
    "detached-patch",
    "disconnected-outer-patch",
}


def _public_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        return None
    return out


def audit_recto_coverage(
    manifest: dict[str, Any],
    *,
    expected_volume_root: str | None = None,
    relative_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Validate declared recto coverage and the <10% outer-patch exception."""

    if relative_tolerance < 0:
        raise ValueError("relative_tolerance must be non-negative")

    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(manifest, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic": DIAGNOSTIC,
            "status": "fail",
            "error_count": 1,
            "warning_count": 0,
            "errors": ["manifest must contain a JSON object"],
            "warnings": [],
        }

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")

    volume_root = manifest.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root:
        errors.append("volume_root must be a non-empty exact CT root")
        volume_root = None
    if expected_volume_root is not None and volume_root != expected_volume_root:
        errors.append("manifest volume_root does not match the requested exact CT root")

    generated_by = manifest.get("generated_by")
    if not isinstance(generated_by, dict):
        generated_by = {}
        errors.append("generated_by must be an object")
    command = generated_by.get("command")
    commit = generated_by.get("code_commit")
    if not isinstance(command, str) or not command.strip():
        errors.append("generated_by.command must document the coverage command")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        errors.append("generated_by.code_commit must be a lowercase 40-hex commit")

    reference = manifest.get("reference")
    if not isinstance(reference, dict):
        reference = {}
        errors.append("reference must be an object")

    reference_area = _positive_number(reference.get("surface_area"))
    if reference_area is None:
        errors.append("reference.surface_area must be a finite positive number")

    area_unit = reference.get("area_unit")
    if not isinstance(area_unit, str) or not area_unit.strip():
        errors.append("reference.area_unit must be a non-empty string")

    method = reference.get("method")
    if not isinstance(method, str) or not method.strip():
        errors.append("reference.method must explain how the recto inventory was measured")

    if not _public_url(reference.get("artifact_url")):
        errors.append("reference.artifact_url must be a public http(s) URL")

    ref_sha = reference.get("sha256")
    if not isinstance(ref_sha, str) or not SHA256_RE.fullmatch(ref_sha):
        errors.append("reference.sha256 must be a lowercase 64-hex digest")

    raw_components = manifest.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        errors.append("components must be a non-empty list")
        raw_components = []

    seen_ids: set[str] = set()
    seen_mesh_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    declared_area = 0.0
    unrolled_area = 0.0
    excluded_area = 0.0

    for i, row in enumerate(raw_components):
        label = f"components[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{label} must be an object")
            continue

        component_id = row.get("id")
        if not isinstance(component_id, str) or not component_id:
            errors.append(f"{label}.id must be a non-empty string")
            continue
        if component_id in seen_ids:
            errors.append(f"duplicate component id: {component_id}")
            continue
        seen_ids.add(component_id)

        kind = row.get("kind")
        if kind not in COMPONENT_KINDS:
            errors.append(
                f"{label}.kind must be one of {', '.join(sorted(COMPONENT_KINDS))}"
            )

        area = _positive_number(row.get("area"))
        if area is None:
            errors.append(f"{label}.area must be a finite positive number")
            continue
        declared_area += area

        if type(row.get("unrolled")) is not bool:
            errors.append(f"{label}.unrolled must be boolean")
            unrolled = False
        else:
            unrolled = bool(row["unrolled"])

        if type(row.get("excluded")) is not bool:
            errors.append(f"{label}.excluded must be boolean")
            excluded = False
        else:
            excluded = bool(row["excluded"])

        mesh_ids_raw = row.get("mesh_ids")
        mesh_ids_valid = isinstance(mesh_ids_raw, list) and all(
            isinstance(v, str) and v for v in mesh_ids_raw
        )
        mesh_ids = mesh_ids_raw if mesh_ids_valid else []
        if mesh_ids_raw is not None and not mesh_ids_valid:
            errors.append(f"{label}.mesh_ids must be a list of non-empty strings")

        for mesh_id in mesh_ids:
            if mesh_id in seen_mesh_ids:
                errors.append(
                    f"mesh id {mesh_id!r} is assigned to more than one recto component"
                )
            seen_mesh_ids.add(mesh_id)

        if excluded:
            if kind != "disconnected-outer-patch":
                errors.append(
                    f"{label} may be excluded only when kind='disconnected-outer-patch'"
                )
            if unrolled:
                errors.append(f"{label} cannot be both unrolled and excluded")
            reason = row.get("exclusion_reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{label}.exclusion_reason is required for excluded area")
            excluded_area += area
        else:
            if not unrolled:
                errors.append(
                    f"{label} is in scope but not unrolled; declared recto coverage is incomplete"
                )
            else:
                if not mesh_ids:
                    errors.append(
                        f"{label}.mesh_ids must name submitted mesh evidence when unrolled"
                    )
                unrolled_area += area

        if kind in {"main-sheet", "attached-patch", "detached-patch"} and not unrolled:
            errors.append(f"{label} kind={kind!r} must be unrolled")

        normalized.append(
            {
                "id": component_id,
                "kind": kind,
                "area": area,
                "unrolled": unrolled,
                "excluded": excluded,
                "mesh_ids": mesh_ids,
                "exclusion_reason": row.get("exclusion_reason"),
            }
        )

    area_error = None
    if reference_area is not None:
        area_error = abs(declared_area - reference_area)
        allowed_error = relative_tolerance * reference_area
        if area_error > allowed_error:
            errors.append(
                "declared component area does not match reference.surface_area "
                f"within tolerance ({declared_area:g} vs {reference_area:g})"
            )

    excluded_fraction = (
        excluded_area / reference_area
        if reference_area is not None and reference_area > 0
        else None
    )
    if excluded_fraction is not None and excluded_fraction >= 0.10:
        errors.append(
            "excluded disconnected outer patches must constitute less than 10% "
            "of the declared total recto surface"
        )

    in_scope_area = (
        reference_area - excluded_area
        if reference_area is not None
        else None
    )
    in_scope_coverage = (
        unrolled_area / in_scope_area
        if in_scope_area is not None and in_scope_area > 0
        else None
    )
    if in_scope_coverage is not None:
        if unrolled_area > in_scope_area * (1 + relative_tolerance):
            errors.append(
                "unrolled area exceeds in-scope reference area; check overlap/double counting"
            )
        elif in_scope_coverage < 1 - relative_tolerance:
            errors.append(
                "declared in-scope recto surface is not 100% unrolled"
            )

    status = "fail" if errors else ("partial" if warnings else "pass")
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "volume_root": volume_root,
        "status": status,
        "reference": {
            "surface_area": reference_area,
            "area_unit": area_unit,
            "method": method,
            "artifact_url": reference.get("artifact_url"),
            "sha256": ref_sha,
        },
        "coverage": {
            "declared_component_area": declared_area,
            "unrolled_area": unrolled_area,
            "excluded_disconnected_outer_patch_area": excluded_area,
            "excluded_disconnected_outer_patch_fraction": excluded_fraction,
            "in_scope_area": in_scope_area,
            "in_scope_unrolled_fraction": in_scope_coverage,
            "area_balance_abs_error": area_error,
            "relative_tolerance": relative_tolerance,
        },
        "components": normalized,
        "mesh_ids": sorted(seen_mesh_ids),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "limitation": (
            "PASS means the declared reference recto inventory is fully accounted for "
            "under the stated area model and Grand Prize outer-patch exception. "
            "This audit does not independently discover omitted papyrus, prove that the "
            "reference inventory is complete, or establish papyrological legibility."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit declared 2027 Grand Prize recto-surface coverage"
    )
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--volume-root", default=None)
    ap.add_argument("--relative-tolerance", type=float, default=1e-6)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = audit_recto_coverage(
        manifest,
        expected_volume_root=args.volume_root,
        relative_tolerance=args.relative_tolerance,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['status'].upper()} {args.manifest}: "
        f"{result.get('error_count', 0)} error(s), "
        f"{result.get('warning_count', 0)} warning(s)"
    )
    if result["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
