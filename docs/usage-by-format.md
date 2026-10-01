# Run ScrolIQ on your data, by format

Each ScrolIQ tool reads one community format, never modifies it, and writes
one JSON report with the evidence behind its verdict. The two mesh tools share
one status vocabulary (`pass`, `partial`, `fail`) and one set of finding kinds;
the other tools use verdicts specific to their stage (for example `TRAIN` /
`CAUTION` / `DO NOT TRAIN` for `scrollq-health`, `unknown` for an unmeasured
passport stage).

Install once:

```bash
pip install -r requirements-ci.txt && pip install -e .
```

| You have | Format | Command | Answers |
|---|---|---|---|
| a CT volume on dl.ash2txt.org | OME-Zarr v3, sharded | `scrollq-health`, `scrollq-score`, `scroliq-scan-map` | Is it intact? How healthy are its voxels, and where? |
| a CT volume in the open S3 bucket | OME-Zarr v2, uncompressed | `scroliq-chunk-audit` | Do stored chunks match the declared shape? |
| a traced surface | TIFXYZ (`x/y/z.tif` + `meta.json`) | `scroliq-mesh` | Is the mesh connected, hole-free, fold-free and near-isometric? |
| a traced surface | Wavefront OBJ triangle mesh | `scroliq-obj` | The same, plus non-manifold edges, winding and UV fold-overs |
| winding annotations | VC3D PointCollections JSON | `scroliq-winding` | Are the annotations well-formed, covering, and in radial order? |
| fiber traces | CSV `trace_id,x,y,z` | `scroliq-fiber` | Do the traces have gaps or sharp turns? |
| an ink prediction | `.npy` / `.tif` arrays + labels + mask | `scroliq-ink-validate` | Does it beat falsification controls on held-out ground truth? |
| several of the above | the reports | `scroliq-passport` | What is measured, and what is still `unknown`, per Open Problems stage? |

## CT volumes

```bash
# integrity (zarr-pyramid-audit) + scan health, one TRAIN / CAUTION / DO NOT TRAIN verdict
scrollq-health --root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr

# where in the volume each observation was made
scroliq-scan-map --root <same root> --grid 6 --out out/PHerc0813.scan-map.json

# open-bucket OME-Zarr v2: declared vs stored chunk sizes
scroliq-chunk-audit --index artifacts/2026-10-01-bucket-index/metadata.min.json.gz --out out/chunks.json
```

The 0–100 scan-health score is triage only. It is not a readability score.

## Surfaces

```bash
# TIFXYZ, bound to the exact CT volume it was traced on
scroliq-mesh --tifxyz <segment>/mesh/<name>.tifxyz \
  --volume-root community-uploads/forrest/volcomp/<scroll>/volumes/<volume>.zarr \
  --out out/segment.mesh.json

# OBJ
scroliq-obj --obj <segment>/mesh/intermediate/<segment>_original.obj --out out/segment.obj.json
```

Both report the same finding kinds where they apply (`connectivity`, `hole`,
`edge-jump`, `normal-reversal`, `isometry-distortion`), so a TIFXYZ and an OBJ
of the same segment can be compared directly. `scroliq-mesh` can also validate
an official VC3D `vc_tifxyz_selfcross` report (`--selfcross-report`) and a
`vesuvius.surface_preflight` CT-support report (`--surface-preflight-report`).

`artifacts/2026-10-01-corpus-mesh-audit/run.sh` runs both tools over every
published mesh in the open bucket.

## Annotations and traces

```bash
scroliq-winding --dataset <dir with abs_winding.json etc.> --umbilicus <umbilicus file> --out out/winding.json
scroliq-fiber traces.csv --out out/fibers.json
```

## Ink

```bash
scroliq-ink-validate --prediction pred.tif --labels labels.tif --validation-mask mask.tif \
  --split-id my-split --held-out --training-overlap none \
  --ground-truth-source-url <url> --model-checkpoint-sha256 <sha> --model-window <window> \
  --control plus_normal=pred_plus3.tif --control minus_normal=pred_minus3.tif \
  --out out/ink.json
```

See `docs/ink-validation.md` for what each control falsifies.

## Put it together

```bash
scroliq-passport --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --root <volume id> --scan-map out/PHerc0813.scan-map.json \
  --mesh-audit out/segment.mesh.json --winding-audit out/winding.json \
  --out out/passport.json
```

`docs/walkthrough-pherc0813.md` follows one Grand Prize target through every
report.
