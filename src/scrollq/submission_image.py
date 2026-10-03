"""Deterministic Grand Prize column-image and banner generation.

The physical scale relation mirrors current VC3D vc_render_tifxyz semantics:

    um_per_output_pixel = base_voxel_size_um / (2 ** -group_idx) / render_scale

A column image gets a footer containing an exactly computed 1 cm bar and a
small machine-readable JSON proof. Banner generation consumes the decorated
column images and overlays their sequential column numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

TOOL = "scroliq-submission-image"
SCHEMA_VERSION = 1
CM_UM = 10_000.0
COLUMN_RE = re.compile(r"^column_(\d{2,})\.(?:tif|tiff|png)$", re.IGNORECASE)

# Tiny deterministic 5x7 glyphs. Avoids system-font and Pillow-font drift.
_GLYPHS = {
    "0": ("11111","10001","10011","10101","11001","10001","11111"),
    "1": ("00100","01100","00100","00100","00100","00100","01110"),
    "2": ("11110","00001","00001","11110","10000","10000","11111"),
    "3": ("11110","00001","00001","01110","00001","00001","11110"),
    "4": ("10010","10010","10010","11111","00010","00010","00010"),
    "5": ("11111","10000","10000","11110","00001","00001","11110"),
    "6": ("01111","10000","10000","11110","10001","10001","01110"),
    "7": ("11111","00001","00010","00100","01000","01000","01000"),
    "8": ("01110","10001","10001","01110","10001","10001","01110"),
    "9": ("01110","10001","10001","01111","00001","00001","11110"),
    "c": ("00000","00000","01111","10000","10000","10000","01111"),
    "m": ("00000","00000","11011","10101","10101","10101","10101"),
    " ": ("00000","00000","00000","00000","00000","00000","00000"),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def vc_render_um_per_pixel(
    base_voxel_size_um: float,
    group_idx: int,
    render_scale: float,
) -> float:
    if (
        isinstance(base_voxel_size_um, bool)
        or not isinstance(base_voxel_size_um, (int, float))
        or not math.isfinite(float(base_voxel_size_um))
        or float(base_voxel_size_um) <= 0
    ):
        raise ValueError("base voxel size must be a positive finite number")
    if isinstance(group_idx, bool) or not isinstance(group_idx, int) or group_idx < 0:
        raise ValueError("group_idx must be a non-negative integer")
    if (
        isinstance(render_scale, bool)
        or not isinstance(render_scale, (int, float))
        or not math.isfinite(float(render_scale))
        or float(render_scale) <= 0
    ):
        raise ValueError("render scale must be a positive finite number")
    ds_scale = math.ldexp(1.0, -group_idx)
    return float(base_voxel_size_um) / ds_scale / float(render_scale)


def _ink_values(mode: str) -> tuple[Any, Any]:
    if mode == "1":
        return 0, 1
    if mode in {"L", "P"}:
        return 0, 255
    if mode.startswith("I;16"):
        return 0, 65535
    if mode == "I":
        return 0, 2**31 - 1
    if mode == "F":
        return 0.0, 1.0
    if mode == "RGB":
        return (0, 0, 0), (255, 255, 255)
    if mode == "RGBA":
        return (0, 0, 0, 255), (255, 255, 255, 255)
    raise ValueError(f"unsupported image mode {mode!r}")


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill: Any,
    scale: int = 2,
) -> None:
    x0, y0 = xy
    x = x0
    for ch in text:
        glyph = _GLYPHS.get(ch)
        if glyph is None:
            raise ValueError(f"unsupported deterministic glyph {ch!r}")
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    draw.rectangle(
                        (
                            x + col * scale,
                            y0 + row * scale,
                            x + (col + 1) * scale - 1,
                            y0 + (row + 1) * scale - 1,
                        ),
                        fill=fill,
                    )
        x += 6 * scale


def decorate_column(
    input_path: str | Path,
    output_path: str | Path,
    *,
    base_voxel_size_um: float,
    group_idx: int,
    render_scale: float,
    column: int,
    metadata_path: str | Path | None = None,
    footer_height: int = 48,
    margin: int = 16,
    bar_thickness: int = 4,
) -> dict[str, Any]:
    src = Path(input_path)
    dst = Path(output_path)
    if dst.exists():
        raise FileExistsError(f"refusing to overwrite {dst}")
    if metadata_path is not None and Path(metadata_path).exists():
        raise FileExistsError(f"refusing to overwrite {metadata_path}")
    if not src.is_file():
        raise FileNotFoundError(src)
    if isinstance(column, bool) or not isinstance(column, int) or column < 1:
        raise ValueError("column must be a positive integer")

    um_per_pixel = vc_render_um_per_pixel(
        base_voxel_size_um, group_idx, render_scale
    )
    bar_pixels = int(round(CM_UM / um_per_pixel))
    if bar_pixels < 1:
        raise ValueError("1 cm scale bar rounds below one pixel")

    with Image.open(src) as opened:
        image = opened.copy()
    black, white = _ink_values(image.mode)
    available = image.width - 2 * margin
    if bar_pixels > available:
        raise ValueError(
            f"1 cm scale bar needs {bar_pixels} px but image only has "
            f"{available} px between margins"
        )
    if footer_height < 32:
        raise ValueError("footer_height must be at least 32 pixels")

    canvas = Image.new(image.mode, (image.width, image.height + footer_height), black)
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    bar_x = margin
    bar_y = image.height + 12
    draw.rectangle(
        (bar_x, bar_y, bar_x + bar_pixels - 1, bar_y + bar_thickness - 1),
        fill=white,
    )
    _draw_text(
        draw,
        (bar_x, bar_y + bar_thickness + 6),
        "1 cm",
        fill=white,
        scale=2,
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst)

    proof = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "operation": "column",
        "column": column,
        "input": {
            "path": src.name,
            "sha256": _sha256(src),
            "size_xy": [image.width, image.height],
        },
        "output": {
            "path": dst.name,
            "sha256": _sha256(dst),
            "size_xy": [canvas.width, canvas.height],
        },
        "vc_render_tifxyz": {
            "base_voxel_size_um": float(base_voxel_size_um),
            "group_idx": int(group_idx),
            "render_scale": float(render_scale),
            "ds_scale": math.ldexp(1.0, -group_idx),
            "micrometers_per_output_pixel": um_per_pixel,
            "formula": "base_voxel_size_um / (2**-group_idx) / render_scale",
        },
        "scale_bar": {
            "centimeters": 1,
            "micrometers": int(CM_UM),
            "pixels": bar_pixels,
            "x": bar_x,
            "y": bar_y,
            "thickness": bar_thickness,
            "footer_height": footer_height,
        },
    }

    if metadata_path is not None:
        mp = Path(metadata_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof


def _column_number(path: Path) -> int:
    match = COLUMN_RE.fullmatch(path.name)
    if not match:
        raise ValueError(
            f"column image must be named column_NN.tif/.tiff/.png: {path.name}"
        )
    return int(match.group(1))


def build_banner(
    column_paths: list[str | Path],
    output_path: str | Path,
    *,
    metadata_path: str | Path | None = None,
    max_column_height: int = 1200,
    label_height: int = 28,
    gap: int = 8,
) -> dict[str, Any]:
    if not column_paths:
        raise ValueError("at least one column image is required")
    dst = Path(output_path)
    if dst.exists():
        raise FileExistsError(f"refusing to overwrite {dst}")
    if metadata_path is not None and Path(metadata_path).exists():
        raise FileExistsError(f"refusing to overwrite {metadata_path}")
    if max_column_height < 1 or label_height < 16 or gap < 0:
        raise ValueError("invalid banner geometry")

    items: list[tuple[int, Path]] = []
    for value in column_paths:
        path = Path(value)
        if not path.is_file():
            raise FileNotFoundError(path)
        items.append((_column_number(path), path))
    items.sort(key=lambda item: item[0])
    numbers = [n for n, _ in items]
    if len(numbers) != len(set(numbers)):
        raise ValueError("duplicate column number")
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("column numbers must be consecutive")

    rendered: list[tuple[int, Path, Image.Image, float]] = []
    max_h = 0
    for number, path in items:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        scale = min(1.0, max_column_height / image.height)
        if scale < 1.0:
            size = (
                max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))),
            )
            image = image.resize(size, Image.Resampling.LANCZOS)
        rendered.append((number, path, image, scale))
        max_h = max(max_h, image.height)

    width = sum(image.width for _, _, image, _ in rendered)
    width += gap * (len(rendered) - 1)
    canvas = Image.new("RGB", (width, label_height + max_h), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    x = 0
    columns = []
    for number, path, image, scale in rendered:
        label = f"{number:02d}"
        _draw_text(draw, (x + 4, 6), label, fill=(255, 255, 255), scale=2)
        canvas.paste(image, (x, label_height))
        columns.append(
            {
                "column": number,
                "path": path.name,
                "sha256": _sha256(path),
                "banner_x": x,
                "display_size_xy": [image.width, image.height],
                "display_scale": scale,
            }
        )
        x += image.width + gap

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst)
    proof = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "operation": "banner",
        "columns": columns,
        "column_numbers_overlaid": True,
        "output": {
            "path": dst.name,
            "sha256": _sha256(dst),
            "size_xy": [canvas.width, canvas.height],
        },
        "max_column_height": max_column_height,
        "label_height": label_height,
        "gap": gap,
    }
    if metadata_path is not None:
        mp = Path(metadata_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    col = sub.add_parser("column", help="add a physically derived 1 cm scale bar")
    col.add_argument("--input", required=True)
    col.add_argument("--output", required=True)
    col.add_argument("--base-voxel-um", required=True, type=float)
    col.add_argument("--group-idx", required=True, type=int)
    col.add_argument("--render-scale", required=True, type=float)
    col.add_argument("--column", required=True, type=int)
    col.add_argument("--metadata-out", required=True)

    ban = sub.add_parser("banner", help="build numbered full-scroll banner")
    ban.add_argument("--column", action="append", required=True, dest="columns")
    ban.add_argument("--output", required=True)
    ban.add_argument("--metadata-out", required=True)
    ban.add_argument("--max-column-height", type=int, default=1200)

    args = ap.parse_args(argv)
    try:
        if args.command == "column":
            proof = decorate_column(
                args.input,
                args.output,
                base_voxel_size_um=args.base_voxel_um,
                group_idx=args.group_idx,
                render_scale=args.render_scale,
                column=args.column,
                metadata_path=args.metadata_out,
            )
        else:
            proof = build_banner(
                args.columns,
                args.output,
                metadata_path=args.metadata_out,
                max_column_height=args.max_column_height,
            )
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
        return 2

    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
