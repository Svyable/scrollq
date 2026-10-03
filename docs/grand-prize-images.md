# Grand Prize submission images

`scroliq-submission-image` makes two reviewer-facing artifacts that the 2027
Grand Prize rules require: per-column static images with a visible **1 cm**
scale bar, and one numbered full-scroll banner.

The important part is that the scale bar is not an arbitrary pixel length.
For images rendered by current VC3D `vc_render_tifxyz`, ScrolIQ mirrors the
renderer’s physical-spacing relation:

```text
micrometers_per_output_pixel =
    base_voxel_size_um / (2 ** -group_idx) / render_scale
```

Here `render_scale` is the value passed to `vc_render_tifxyz --scale`, and
`group_idx` is the source pyramid level. The eligible volume’s level-0 voxel
size is the `base_voxel_size_um`. A 1 cm bar is therefore
`round(10000 / micrometers_per_output_pixel)` pixels long.

## Decorate a column

Render the scientific image first, then add the reviewer footer:

```bash
scroliq-submission-image column \
  --input work/column_01.raw.tif \
  --output submission/column_01.tif \
  --base-voxel-um 9.362 \
  --group-idx 0 \
  --render-scale 1 \
  --column 1 \
  --metadata-out submission/evidence/column_01.scale.json
```

The command refuses to overwrite an existing output. It appends a footer
instead of drawing over papyrus pixels, writes an exactly computed white
1 cm bar plus a deterministic `1 cm` label, and emits a JSON proof containing:

- the source and final image SHA-256 digests and dimensions;
- the exact VC3D physical-scale inputs and formula;
- micrometres per output pixel;
- the integer bar length and its exact pixel coordinates.

If the true 1 cm bar cannot fit between the image margins, generation fails
instead of silently shortening the bar.

## Build the full-scroll banner

After every final column image is frozen:

```bash
scroliq-submission-image banner \
  --column submission/column_01.tif \
  --column submission/column_02.tif \
  --column submission/column_03.tif \
  --output submission/banner.tif \
  --metadata-out submission/evidence/banner.json
```

Input names must be `column_NN.tif`, `.tiff`, or `.png`. The builder sorts
them numerically, rejects duplicate or skipped column numbers, scales only for
the overview canvas, and overlays each column number in a deterministic
built-in pixel font. The banner proof records every source image SHA, display
scale and horizontal position plus the final banner SHA.

This tool does not create or enhance ink. It only composes already-generated
CT/mesh-derived images and reviewer labels, so the scientific pixels above the
footer remain unchanged.
