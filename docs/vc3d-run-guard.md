# VC3D semantic run guard

`scroliq-vc3d-run-guard` closes a reproducibility hole that ordinary process
supervision cannot: an external geometry program can exit successfully while
producing no usable surface, a physically impossible one, a surface whose own
metadata contradicts its vertices, or a byte-for-byte copy of its input.

Exit status is therefore treated as **necessary, never sufficient**. A producer
that exits 0 while any postcondition fails is reported as
`PRODUCER_SEMANTIC_FAILURE`, not as success.

The guard is intentionally generic enough for VC3D geometry commands such as
`vc_grow_seg_from_seed`, but it does not claim that every VC3D program emits
TIFXYZ. Use it only when the preregistered expected product is a TIFXYZ
surface.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `PRODUCER_OK` | exit 0 **and** every evaluated gate passed |
| `PRODUCER_SEMANTIC_FAILURE` | exit 0 but at least one postcondition failed |
| `PRODUCER_PROCESS_FAILURE` | the process did not launch, or exited non-zero |

A non-zero exit is never rescued by a good-looking output. The CLI exits 0 only
for `PRODUCER_OK` and 2 otherwise; the receipt's `verdict`, `failed_gates` and
`process.exit_zero_but_postcondition_failed` say which kind of failure it was.

## Contract

Before launch the guard requires that the expected output directory and both
log paths do **not** exist (no stale surface can be mistaken for a new one),
that every declared `--input-tifxyz` is a readable TIFXYZ, and that any
`--volume-meta` is valid. Declared inputs are digested **before** the run, so a
producer cannot redefine what its input was by editing it.

After the command exits, these gates are evaluated:

| Gate | Passes when |
| --- | --- |
| `process_exit_zero` | the process launched and returned 0 |
| `new_output_present` | the expected TIFXYZ directory was newly created |
| `command_output_decodes` | the `scroliq-mesh` audit does not fail |
| `valid_vertices` / `valid_quads` | at least the declared minimum exist |
| `finite_positive_surface_area` | recomputed area is finite, > 0 and ≥ `--min-area-cm2` |
| `voxel_spacing_verified` | the declared voxel size does not contradict `--volume-meta` (and, with `--require-verified-voxel-spacing`, agrees with it) |
| `spatial_metadata_consistent` | the extent was recomputed from vertices and any declared `meta.json` bbox contains them (within `--bbox-tolerance-voxels`, default 1) |
| `extent_within_volume` | the recomputed extent lies inside `--volume-meta` `width`/`height`/`slices` |
| `ct_volume_binding` | with `--require-ct-preflight`, a validated Villa surface preflight binds the exact output to the declared CT |
| `output_differs_from_inputs` | the output geometry digest differs from every `--input-tifxyz` (`--input-relation grows` also requires more valid vertices than each input) |
| `inputs_unmodified` | every declared input has the same geometry digest after the run |

### What "recomputed" means

Area, extent and bounds come from the decoded `x/y/z` vertex coordinates. The
guard never reads an area, bbox or voxel-size field from the producer's own
`meta.json` except to *compare* the declared bbox against the recomputed one.
Physical area is `surface_area_voxels2 × (voxel_size_um / 10 000)²`, so it is
only as trustworthy as the voxel size — which is why that size can be checked
against an independent, hashed source.

### Voxel spacing

`--voxel-size-um` is a declaration. The reported failure was exactly a producer
reading voxel-size metadata through a path that cannot work for an `s3://`
volume, so the guard does not fetch it either: supply a local copy of the
VC3D-style volume `meta.json` with `--volume-meta` (it must carry `voxelsize`
in µm; `width`, `height` and `slices` additionally enable the bounds gate). The
file's SHA-256 and value are recorded in the receipt. A contradiction always
fails; agreement marks the spacing `verified`.

### The geometry digest

`output_differs_from_inputs` compares a digest of the **decoded** geometry: the
validity bitmap plus the float32 coordinates of valid vertices. Re-encoding the
TIFFs, regenerating a `meta.json` uuid, or leaving junk in masked-out cells does
not change it, so a "new" output that is the same surface is still a no-op.

### Gates that were not exercised

A gate whose independent evidence was not supplied is **not silently passed**.
It appears in the receipt's `unevaluated_gates` (for example
`voxel_spacing_verified` when no `--volume-meta` was given, or
`output_differs_from_inputs` when no `--input-tifxyz` was declared), and the
`limitations` text says a pass does not cover them.

## Example

```bash
scroliq-vc3d-run-guard \
  --output-tifxyz out/grown.tifxyz \
  --input-tifxyz seeds/seed.tifxyz --input-relation grows \
  --volume-root s3://vesuvius-challenge/.../volume.zarr \
  --voxel-size-um 7.91 \
  --volume-meta volumes/PHerc-X.meta.json --require-verified-voxel-spacing \
  --min-valid-vertices 1000 \
  --min-valid-quads 500 \
  --min-area-cm2 0.25 \
  --stdout-log out/grow.stdout.log \
  --stderr-log out/grow.stderr.log \
  --out out/grow.receipt.json \
  -- vc_grow_seg_from_seed ... --output out/grown.tifxyz
```

For prize-grade volume binding, first produce the official Villa surface
preflight artifact and add:

```text
--surface-preflight-report out/surface-preflight.json --require-ct-preflight
```

The receipt (schema version 2) hashes stdout, stderr, the resolved executable
when it is a local file, and all TIFXYZ semantic files through the embedded mesh
audit, and records the recomputed `physical` block, the `extent` (voxels and
µm, plus the declared-bbox comparison) and the input/output geometry digests.
The `--out` receipt is create-only.

## Claim boundary

A pass proves that **this invocation** produced a newly created surface that
satisfies the declared postconditions. It does not prove sheet identity,
held-out accuracy, topology, ink, or Grand Prize completeness. The 1-voxel
bbox tolerance reflects that producers quantize bounds to integer voxels; a
sub-voxel excess is rounding, not staleness.

## Why this exists

A public VC3D failure report (supplied in the maintainers' research note; **not
reproduced in this repository**) describes a growth command accepting an
`s3://` volume, computing zero area through an unsupported filesystem path,
deleting the grown surface for falling below its minimum-area rule, and
nevertheless returning success. The tests reproduce that failure's *shape*
with a stand-in producer, not the upstream tool. ScrolIQ therefore treats
process success as necessary but not sufficient evidence.

The guard reuses the existing TIFXYZ audit rather than adding a second parser
or a parallel definition of surface validity. Spatial-metadata handling is
described in [TIFXYZ metadata integrity](tifxyz-metadata-integrity.md).
