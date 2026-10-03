"""Bind external mesh evidence to a ScrolIQ TIFXYZ audit without laundering provenance.

The external-evidence dossier is deliberately conservative. It records the
strongest identity statement supported by both artifacts and only imports an
external measurement as evidence about the local surface when the external
measurement subject is the same published original geometry.

Binding classes are descriptive, not scores:

- semantic-exact: every semantically consumed TIFXYZ file is content-bound.
- coordinate-exact: x/y/z and mask semantics are content-bound, but metadata
  identity is not available from the external source.
- path-grid: path/segment/grid agree but full coordinate hashes are unavailable.
- path-only: only a path/identifier agrees.
- unbound: no adequate identity information.
- mismatch: supplied identity information contradicts the local audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DIAGNOSTIC = "external-mesh-evidence-dossier"
WINDCHECK_SCHEMA = "release_index/v1"
BINDINGS = {
    "semantic-exact",
    "coordinate-exact",
    "path-grid",
    "path-only",
    "unbound",
    "mismatch",
}

_VOLUME_ID_RE = re.compile(r"(?:^|/)volumes/([0-9]+)-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _volume_id(volume_root: str | None) -> str | None:
    if not isinstance(volume_root, str):
        return None
    match = _VOLUME_ID_RE.search(volume_root)
    return match.group(1) if match else None


def _local_coordinate_identity(mesh_audit: dict[str, Any]) -> dict[str, Any]:
    provenance = mesh_audit.get("provenance")
    if not isinstance(provenance, dict):
        return {
            "status": "unbound",
            "reason": "ScrolIQ mesh audit has no provenance map",
        }

    coordinates: dict[str, str] = {}
    missing: list[str] = []
    for name in ("x.tif", "y.tif", "z.tif"):
        row = provenance.get(name)
        value = row.get("sha256") if isinstance(row, dict) else None
        if not isinstance(value, str) or len(value) != 64:
            missing.append(name)
        else:
            coordinates[name[0]] = value

    if missing:
        return {
            "status": "unbound",
            "reason": "ScrolIQ mesh audit lacks full coordinate hashes: " + ", ".join(missing),
        }

    mask_row = provenance.get("mask.tif")
    mask_hash = (
        mask_row.get("sha256")
        if isinstance(mask_row, dict) and isinstance(mask_row.get("sha256"), str)
        else None
    )
    meta_row = provenance.get("meta.json")
    meta_hash = (
        meta_row.get("sha256")
        if isinstance(meta_row, dict) and isinstance(meta_row.get("sha256"), str)
        else None
    )
    return {
        "status": "bound",
        "coordinates": coordinates,
        "mask": mask_hash,
        "meta": meta_hash,
    }


def _compare_hashes(
    local: dict[str, Any],
    external_hashes: dict[str, Any] | None,
    *,
    external_meta_sha256: str | None = None,
) -> dict[str, Any]:
    if local.get("status") != "bound":
        return {
            "level": "unbound",
            "coordinates_match": None,
            "mask_match": None,
            "metadata_match": None,
            "reason": local.get("reason", "local surface is not content-bound"),
        }
    if not isinstance(external_hashes, dict):
        return {
            "level": "unbound",
            "coordinates_match": None,
            "mask_match": None,
            "metadata_match": None,
            "reason": "external evidence supplies no coordinate hash map",
        }

    expected = local["coordinates"]
    observed = {axis: external_hashes.get(axis) for axis in ("x", "y", "z")}
    coordinate_complete = all(
        isinstance(observed[axis], str) and len(observed[axis]) == 64
        for axis in ("x", "y", "z")
    )
    if not coordinate_complete:
        return {
            "level": "unbound",
            "coordinates_match": None,
            "mask_match": None,
            "metadata_match": None,
            "reason": "external coordinate hashes are incomplete",
        }

    coordinates_match = all(observed[axis] == expected[axis] for axis in ("x", "y", "z"))
    local_mask = local.get("mask")
    external_mask = external_hashes.get("mask")
    mask_match = external_mask == local_mask
    if not coordinates_match or not mask_match:
        return {
            "level": "mismatch",
            "coordinates_match": coordinates_match,
            "mask_match": mask_match,
            "metadata_match": None,
            "reason": "external content hashes contradict the local TIFXYZ identity",
        }

    metadata_match: bool | None = None
    if external_meta_sha256 is not None:
        metadata_match = external_meta_sha256 == local.get("meta")
        if not metadata_match:
            return {
                "level": "mismatch",
                "coordinates_match": True,
                "mask_match": True,
                "metadata_match": False,
                "reason": "coordinate bytes match but meta.json SHA-256 differs",
            }
        level = "semantic-exact"
        reason = "coordinate, mask, and metadata identity match"
    else:
        level = "coordinate-exact"
        reason = (
            "x/y/z and mask semantics match by full SHA-256; external source "
            "does not expose meta.json identity"
        )
    return {
        "level": level,
        "coordinates_match": True,
        "mask_match": True,
        "metadata_match": metadata_match,
        "reason": reason,
    }


def bind_windcheck_release(
    mesh_audit: dict[str, Any],
    windcheck_index: dict[str, Any],
    *,
    segment: str,
    scroll: str,
    volume_id: str,
    source_sha256: str | None = None,
    repository: str = "https://github.com/joe-carr-data/windcheck",
    commit: str | None = None,
) -> dict[str, Any]:
    """Compose one Windcheck release record with a ScrolIQ mesh audit.

    Windcheck's release index exposes full x/y/z/mask hashes but not the
    meta.json hash in its per-segment projection. A matching record therefore
    reaches coordinate-exact binding, not semantic-exact binding.
    """
    local = _local_coordinate_identity(mesh_audit)
    audit_volume = _volume_id(mesh_audit.get("volume_root"))
    base = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "surface": {
            "scroll": scroll,
            "segment": segment,
            "volume_id": volume_id,
            "volume_root": mesh_audit.get("volume_root"),
            "tifxyz_path": mesh_audit.get("tifxyz_path"),
            "local_mesh_audit_status": mesh_audit.get("status"),
            "local_mesh_provenance": mesh_audit.get("provenance", {}),
            "local_mesh_findings": list(mesh_audit.get("findings") or []),
        },
        "external_source": {
            "tool": "windcheck",
            "repository": repository,
            "commit": commit,
            "release_schema": windcheck_index.get("schema_version")
            or windcheck_index.get("schema"),
            "source_sha256": source_sha256,
        },
    }

    if mesh_audit.get("diagnostic") != "tifxyz-mesh-audit":
        return {
            **base,
            "status": "excluded",
            "binding": {
                "level": "unbound",
                "reason": "local artifact is not a ScrolIQ tifxyz-mesh-audit",
            },
            "external_measurement": {"status": "excluded"},
            "limitations": ["No external claim was imported."],
        }
    if audit_volume != volume_id:
        return {
            **base,
            "status": "excluded",
            "binding": {
                "level": "mismatch",
                "reason": (
                    f"local mesh audit volume id {audit_volume!r} does not equal "
                    f"declared volume id {volume_id!r}"
                ),
            },
            "external_measurement": {"status": "excluded"},
            "limitations": ["No external claim was imported."],
        }

    release_schema = windcheck_index.get("schema_version") or windcheck_index.get("schema")
    if release_schema != WINDCHECK_SCHEMA:
        return {
            **base,
            "status": "excluded",
            "binding": {
                "level": "unbound",
                "reason": f"unsupported Windcheck release schema: {release_schema!r}",
            },
            "external_measurement": {"status": "excluded"},
            "limitations": ["No external claim was imported."],
        }

    segments = windcheck_index.get("segments")
    record = segments.get(segment) if isinstance(segments, dict) else None
    if not isinstance(record, dict):
        return {
            **base,
            "status": "excluded",
            "binding": {
                "level": "unbound",
                "reason": "segment is absent from the Windcheck release index",
            },
            "external_measurement": {"status": "excluded"},
            "limitations": ["No external claim was imported."],
        }

    identity_mismatch: list[str] = []
    if record.get("scroll") != scroll:
        identity_mismatch.append(
            f"scroll {record.get('scroll')!r} != {scroll!r}"
        )
    if str(record.get("volume")) != str(volume_id):
        identity_mismatch.append(
            f"volume {record.get('volume')!r} != {volume_id!r}"
        )
    if identity_mismatch:
        return {
            **base,
            "status": "excluded",
            "binding": {
                "level": "mismatch",
                "reason": "; ".join(identity_mismatch),
            },
            "external_record": {
                "segment": record.get("segment"),
                "scroll": record.get("scroll"),
                "volume": record.get("volume"),
            },
            "external_measurement": {"status": "excluded"},
            "limitations": ["No external claim was imported."],
        }

    base_kind = record.get("base_kind")
    same_original_subject = base_kind == "original"
    hashes = (
        record.get("input_hashes")
        if same_original_subject
        else record.get("original_hashes")
    )
    binding = _compare_hashes(local, hashes)

    measurement: dict[str, Any]
    if binding["level"] in {"coordinate-exact", "semantic-exact"} and same_original_subject:
        census = record.get("census") if isinstance(record.get("census"), dict) else {}
        measurement = {
            "status": "included",
            "subject": "same-published-original",
            "input_transverse_total": census.get("input_transverse_total"),
            "geometry_status_after_transaction": census.get("geometry_status"),
            "output_transverse_total": census.get("output_transverse_total"),
            "recensus_clean_both_diagonals": census.get("recensus_clean_both_diagonals"),
            "disposition": record.get("disposition"),
            "retention": dict(record.get("retention") or {}),
            "fragmentation": dict(record.get("fragmentation") or {}),
            "certificate": record.get("certificate"),
            "certificate_sha256": record.get("certificate_sha256"),
            "policy_version": record.get("policy_version"),
            "policy_hash": record.get("policy_hash"),
        }
        status = "bound"
    elif binding["level"] in {"coordinate-exact", "semantic-exact"}:
        measurement = {
            "status": "excluded",
            "subject": "derived-base",
            "reason": (
                "Windcheck input census was run on a derived base rather than the "
                "published original; original coordinate identity matches, but that "
                "census is not imported as a measurement of this local original."
            ),
            "base_kind": base_kind,
        }
        status = "partial"
    else:
        measurement = {
            "status": "excluded",
            "subject": "unknown",
            "reason": "external record is not content-bound to the local surface",
        }
        status = "excluded"

    grid_shape = record.get("grid_shape")
    local_shape = ((mesh_audit.get("grid") or {}).get("shape_yx"))
    grid_match = (
        list(grid_shape) == list(local_shape)
        if isinstance(grid_shape, list) and isinstance(local_shape, list)
        else None
    )
    local_valid = (mesh_audit.get("grid") or {}).get("valid_vertices")
    external_valid = record.get("n_valid_vertices")
    valid_vertex_match = (
        int(local_valid) == int(external_valid)
        if isinstance(local_valid, int) and isinstance(external_valid, int)
        else None
    )

    return {
        **base,
        "status": status,
        "binding": {
            **binding,
            "grid_shape_match": grid_match,
            "valid_vertex_count_match": valid_vertex_match,
            "external_hash_subject": (
                "input_hashes" if same_original_subject else "original_hashes"
            ),
            "measurement_subject": (
                "same-published-original" if same_original_subject else "derived-base"
            ),
        },
        "external_record": {
            "segment": record.get("segment"),
            "scroll": record.get("scroll"),
            "volume": record.get("volume"),
            "voxel_um": record.get("voxel_um"),
            "base_kind": base_kind,
            "input_hashes": record.get("input_hashes"),
            "original_hashes": record.get("original_hashes"),
            "grid_shape": grid_shape,
            "n_valid_vertices": external_valid,
            "status": record.get("status"),
        },
        "external_measurement": measurement,
        "claims": {
            "local_mesh_geometry": {
                "status": "measured",
                "source": "ScrolIQ Mesh IQ",
                "findings": list(mesh_audit.get("findings") or []),
            },
            "nonlocal_transverse_self_intersection": (
                {
                    "status": "measured",
                    "source": "Windcheck release index",
                    "input_transverse_total": measurement.get("input_transverse_total"),
                }
                if measurement.get("status") == "included"
                else {
                    "status": "unknown",
                    "reason": measurement.get("reason"),
                }
            ),
        },
        "limitations": [
            (
                "Binding is coordinate-exact rather than semantic-exact because the "
                "Windcheck release-index projection exposes full x/y/z/mask hashes "
                "but not the original meta.json hash."
            ),
            (
                "Windcheck transverse-contact evidence and Mesh IQ local findings "
                "measure different geometry properties; neither proves physical sheet identity."
            ),
            (
                "A Windcheck transformation/reference is not substituted for the local "
                "published surface; transformed-output evidence remains separately identified."
            ),
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bind external mesh evidence to one ScrolIQ TIFXYZ audit"
    )
    ap.add_argument("--mesh-audit", required=True)
    ap.add_argument("--windcheck-index", required=True)
    ap.add_argument("--segment", required=True)
    ap.add_argument("--scroll", required=True)
    ap.add_argument("--volume-id", required=True)
    ap.add_argument("--windcheck-repository", default="https://github.com/joe-carr-data/windcheck")
    ap.add_argument("--windcheck-commit", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    mesh_path = Path(args.mesh_audit)
    index_path = Path(args.windcheck_index)
    mesh_audit = json.loads(mesh_path.read_text(encoding="utf-8"))
    windcheck_index = json.loads(index_path.read_text(encoding="utf-8"))
    dossier = bind_windcheck_release(
        mesh_audit,
        windcheck_index,
        segment=args.segment,
        scroll=args.scroll,
        volume_id=args.volume_id,
        source_sha256=_sha256(index_path),
        repository=args.windcheck_repository,
        commit=args.windcheck_commit,
    )
    dossier["inputs"] = {
        "mesh_audit_path": str(mesh_path),
        "mesh_audit_sha256": _sha256(mesh_path),
        "windcheck_index_path": str(index_path),
        "windcheck_index_sha256": _sha256(index_path),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dossier, indent=2) + "\n", encoding="utf-8")
    print(
        f"{dossier['status'].upper()} {args.segment}: "
        f"binding={dossier['binding']['level']} "
        f"external={dossier['external_measurement']['status']}"
    )
    if dossier["status"] == "excluded":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
