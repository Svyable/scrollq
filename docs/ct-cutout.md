# Provenance-bound CT cutouts

`scroliq-ct-cutout` extracts a bounded level-0 CT box for local geometry
experiments while preserving the coordinate and source lineage needed to make
the result reproducible.

This exists because a hash of a local NumPy array is not enough. A sheetness or
horizon experiment also needs to prove **where those bytes came from** inside
the exact eligible CT volume.

## Contract

The command requires:

- a public HTTP(S) CT URL whose suffix is the exact `volume_root`;
- a ZPA report for that exact root;
- ZPA `integrity=PASS`;
- `source_attestation.state=PRESENT` using
  `zpa-metadata-semantics-v1`;
- audited level-0 axes exactly `z,y,x`;
- a half-open global ZYX box fully inside the audited source shape.

The current reader intentionally reuses ScrolIQ's strict Vesuvius Zarr-v2
`uint8` reader. Live level-0 shape and chunk geometry must match the ZPA
report. Any touched chunk that is not physically stored causes extraction to
fail instead of accepting an implicit fill value.

## Example

```bash
scroliq-ct-cutout \
  --ct-url https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0800/volumes/<exact-volume>.zarr \
  --volume-root PHerc0800/volumes/<exact-volume>.zarr \
  --zpa-report out/exact-volume.zpa.json \
  --start 2100,3000,4000 \
  --stop 2200,3128,4128 \
  --out out/cutout.npy \
  --manifest out/cutout.json
```

Both output paths are create-only. Existing files are never overwritten.

## Manifest

The JSON manifest records:

- exact `ct_url` and `volume_root`;
- the SHA-256 of the exact ZPA report;
- the audited metadata-semantics attestation;
- audited level-0 shape, chunk shape, and dtype;
- the global half-open ZYX bounding box;
- the local-to-global transform
  `global_zyx = local_zyx + start_zyx`;
- every source chunk coordinate touched by the extraction;
- zero missing chunks;
- output shape, dtype, and cutout SHA-256.

That transform is the bridge between local arrays and the repository's
level-0 voxel-index provenance convention. A local probe `[z,y,x]` can be
translated back to one exact global CT coordinate without inference.

## Fail-closed controls

The tests pin several failure cases:

1. a box crossing chunk boundaries must reproduce the exact source voxels;
2. a missing touched chunk aborts instead of becoming zeros;
3. negative, empty, or out-of-bounds boxes are rejected;
4. a ZPA report for another root is rejected;
5. non-ZYX audited axes are rejected;
6. source/output hashes and the coordinate transform are retained;
7. URL aliases and output overwrite attempts are rejected.

## Claim boundary

A valid cutout manifest establishes source and coordinate lineage for one local
level-0 array. It does not establish that a coordinate is papyrus, that a
surface follows the correct winding, that topology is correct, or that ink is
present or readable.

The immediate consumer is the frozen sheetness-control experiment. The next
step is to require `scroliq-sheetness-eval` to verify this manifest so every
surface, normal-offset, and wrong-wrap probe can be traced back to the exact
eligible CT.
