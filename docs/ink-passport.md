# Physical-evidence passport per ink component

`scroliq-ink-passport` emits one machine-readable record per proposed ink
component, and per reviewer-selected letter region. Each record ties the
component to the exact evidence it depends on, so a strong letter can be
audited and rerun without trusting the render it came from.

This is proof infrastructure, not an ink detector. It does not decide that a
component is ink or that a letter is legible, and it changes nothing in the
inference or rendering path. Research decision:
[2026-10-05 relief-witness note](research/2026-10-05-ink-relief-witness.md).

## What each record binds

| field | source | missing means |
|---|---|---|
| `uv_bbox_px`, `uv_centroid_px`, `pixels` | 8-connected components of `prediction ≥ threshold`, or a reviewer `bbox_px` | — |
| `ct.centroid_zyx`, `ct.bbox_zyx` | UV pixels mapped through the submitted TIFXYZ to `level0-voxel-index` `[z, y, x]` | `ct-mapping-incomplete` (a pixel over a mesh hole or outside the grid is never extrapolated) |
| `ink_score` | mean, median and max of the normalized prediction inside the unit | — (a summary, never a verdict) |
| `training_exclusion` | every mapped CT point tested against same-volume training boxes in the `scroliq-provenance` region-set format (half-open, `[z, y, x]`) | `unknown` when no training regions are supplied; never `clear` by default |
| `relief_support` | inside-minus-ring difference (3-pixel matched ring) of an independent relief field in the same UV frame, with a standardized delta; the sign is reported, never assumed | `not-measured` |

The header binds:

- the prediction file's SHA-256;
- the surface's decoded-geometry digest (the same one `scroliq-vc3d-run-guard` uses);
- the checkpoint SHA-256;
- the exact volume ID;
- the training-region, relief and reviewer-region files by SHA-256.

A relief field also needs `--relief-producer` naming how it was computed. A
relief statistic only counts as corroboration when that field was computed
without the ink prediction.

## Status

A unit is one of:

- `complete`: CT fully mapped, exclusion `clear`, relief measured;
- `training-overlap`: at least one mapped point lies inside a same-volume
  training box;
- `incomplete`: anything else.

The passport's status is the worst of its units. It is `unverified` when no
unit was inspected, for example when nothing passes the threshold.

## UV → CT mapping

`--pixels-per-vertex` declares how many prediction pixels span one TIFXYZ grid
step. It is a claim, so it is checked: the prediction's shape must equal the
grid shape × the factor, to within one factor. A pixel centre `p` maps to grid
coordinate `(p + 0.5) / ppv − 0.5`. Centres up to half a step outside the grid
are clamped to its edge. The point is interpolated bilinearly, and only when
all four surrounding vertices are valid.

This matches a render whose output grid is an integer or fixed multiple of the
TIFXYZ grid. For a render made with other `vc_render_tifxyz` settings, first
confirm the declared factor against the render's
`scroliq-submission-image` proof.

## CLI

```bash
scroliq-ink-passport \
  --prediction column01_ink.tif --threshold 0.5 \
  --surface column01.tifxyz --pixels-per-vertex 4 \
  --volume-id <exact eligible volume root> \
  --checkpoint-sha256 <64-hex> --model-id <id> \
  --training-regions training-regions.json \
  [--relief relief_support.tif --relief-producer "<method + commit>"] \
  [--regions reviewer-letters.json] \
  --out out/column01.passport.json
```

`reviewer-letters.json` is `{"regions": [{"id": "...", "bbox_px": [x0, y0, x1, y1]}]}`.
Its pixel boxes can be taken from the `scroliq-legibility` ledger. Output is
create-only.

## Not covered

The passport does not:

- check that the training-region declaration is truthful;
- check that the prediction was produced by the named checkpoint (that is
  `scroliq-eval`'s preflight);
- produce a relief field.

The relief witness itself is an open experiment; see the research note.
