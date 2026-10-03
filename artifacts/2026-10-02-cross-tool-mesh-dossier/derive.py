#!/usr/bin/env python3
"""Build the frozen PHerc0139 ScrolIQ × Windcheck mesh evidence dossier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scrollq.external_mesh_evidence import bind_windcheck_release

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEGMENT = "20260306000001-w051_2026030600"
SCROLL = "PHerc0139"
VOLUME_ID = "20250728140407"
MESH_AUDIT = (
    ROOT
    / "artifacts/2026-10-01-corpus-mesh-audit/reports/"
    / "PHerc0139.20260306000001-w051_2026030600."
      "20260306000001-on-20250728140407-9.362um.json"
)
WINDCHECK = HERE / "windcheck-record.json"
OUT = HERE / "summary.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    mesh = json.loads(MESH_AUDIT.read_text(encoding="utf-8"))
    windcheck = json.loads(WINDCHECK.read_text(encoding="utf-8"))
    source = windcheck["source_projection"]

    dossier = bind_windcheck_release(
        mesh,
        windcheck,
        segment=SEGMENT,
        scroll=SCROLL,
        volume_id=VOLUME_ID,
        source_sha256=sha256(WINDCHECK),
        repository=source["repository"],
        commit=source["commit"],
    )
    dossier["inputs"] = {
        "mesh_audit_path": str(MESH_AUDIT.relative_to(ROOT)),
        "mesh_audit_sha256": sha256(MESH_AUDIT),
        "windcheck_projection_path": str(WINDCHECK.relative_to(ROOT)),
        "windcheck_projection_sha256": sha256(WINDCHECK),
        "windcheck_release_index_git_blob": source["git_blob_sha"],
    }
    dossier["source_projection"] = source

    OUT.write_text(json.dumps(dossier, indent=2) + "\n", encoding="utf-8")
    print(
        f"{dossier['status'].upper()} {SEGMENT}: "
        f"binding={dossier['binding']['level']} "
        f"external={dossier['external_measurement']['status']} "
        f"contacts={dossier['external_measurement'].get('input_transverse_total')}"
    )
    if dossier["status"] != "bound":
        return 2
    if dossier["binding"]["level"] != "coordinate-exact":
        return 2
    if dossier["external_measurement"]["status"] != "included":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
