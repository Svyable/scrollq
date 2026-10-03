"""Canonical OBJ round-trip negative control for flattening experiments.

This is deliberately not a parameterizer. It parses an already-parameterized
triangle OBJ and rewrites the same vertices, UVs, and vertex/UV face
associations in a deterministic canonical text form.

Expected result under scroliq-flatten-compare: HOLD, with identical 3-D geometry
and zero material distortion improvement. A PROMOTE result from this control
would indicate a bug in the comparison/evidence path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scrollq.obj_audit import parse_obj


def _fmt(value: float) -> str:
    # 17 significant digits are sufficient for exact IEEE-754 double round-trip.
    return format(float(value), ".17g")


def roundtrip_obj(source: str | Path, destination: str | Path) -> dict[str, int]:
    src = Path(source)
    dst = Path(destination)
    mesh = parse_obj(src)

    vertices = mesh["vertices"]
    uvs = mesh["uvs"]
    faces = mesh["faces"]
    face_uvs = mesh["face_uvs"]

    if mesh["polygons"] != len(faces):
        raise ValueError(
            "round-trip control only accepts triangle-only OBJ inputs; "
            "fan-triangulating polygons would change the textual face contract"
        )
    if len(uvs) == 0 or any(item is None for item in face_uvs):
        raise ValueError("round-trip control requires UV coordinates on every face")

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# ScrolIQ canonical OBJ round-trip negative control\n")
        fh.write(f"# source={src}\n")
        for x, y, z in vertices:
            fh.write(f"v {_fmt(x)} {_fmt(y)} {_fmt(z)}\n")
        for u, v in uvs:
            fh.write(f"vt {_fmt(u)} {_fmt(v)}\n")
        for face, uv_face in zip(faces, face_uvs, strict=True):
            assert uv_face is not None
            refs = [
                f"{int(vi) + 1}/{int(ti) + 1}"
                for vi, ti in zip(face, uv_face, strict=True)
            ]
            fh.write("f " + " ".join(refs) + "\n")

    return {
        "vertices": int(len(vertices)),
        "uvs": int(len(uvs)),
        "triangles": int(len(faces)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    summary = roundtrip_obj(args.source, args.out)
    print(
        "PASS canonical round-trip: "
        f"{summary['vertices']} vertices, "
        f"{summary['uvs']} UVs, "
        f"{summary['triangles']} triangles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
