# VC3D render receipts

`scroliq-vc3d` is the executable handoff between a Grand Prize TIFXYZ mesh
and the raw TIFF later decorated by `scroliq-submission-image`.

A prose `VC3D_WORKFLOW.md` can explain how the pipeline is used, but prose
alone cannot prove which VC3D binary, eligible CT, mesh, physical scale, and
raw render were actually used. The receipt makes those links
machine-checkable.

The wrapper targets the current upstream `vc_render_tifxyz` interface in
ScrollPrize/villa. Upstream requires `--volume`, `--scale`, and
`--group-idx`; a single TIFXYZ is selected with `--segmentation`. For the
Grand Prize column boundary ScrolIQ forces exactly one TIFF slice and uses
`--tif-output`, which yields `00.tif`.

## Render one column

The TIFXYZ must already be named for its final column and its `meta.json`
must identify the exact eligible volume.

```bash
scroliq-vc3d render \
  --root-dir submission-work \
  --binary /opt/villa/bin/vc_render_tifxyz \
  --vc-commit <40-hex-villa-commit> \
  --volume /data/PHerc0813/volumes/<eligible-volume>.zarr \
  --volume-id <eligible-volume> \
  --mesh column_01.tifxyz \
  --column 1 \
  --base-voxel-um 9.362 \
  --group-idx 0 \
  --scale 1 \
  --tif-output-dir raw/column_01 \
  --receipt evidence/column_01.vc3d.json \
  --log evidence/column_01.vc3d.log \
  --vc-arg=--auto-crop \
  --vc-arg=--surface-interpolation \
  --vc-arg=smooth
```

Critical identity and physical-scale flags are controlled by ScrolIQ and
cannot be supplied through `--vc-arg`. In particular, callers cannot
override:

- volume or segmentation;
- render scale or OME-Zarr group index;
- number of slices;
- TIFF or Zarr output destination;
- voxel size or voxel unit;
- multi-part output controls.

The wrapper always passes the declared level-0 voxel size explicitly as
`--voxel-size ... --voxel-unit micrometer`. This removes dependence on a
renderer metadata fallback when proving the physical scale of a submission
render.

The TIFF output directory must be new or empty. A successful single-column
run must produce one readable `00.tif`; stale files are never silently
accepted.

## What is bound

A schema-v1 receipt records:

- the ScrollPrize/villa repository and exact 40-hex source commit;
- SHA-256, byte size, and `--help` fingerprint of the actual
  `vc_render_tifxyz` executable;
- the exact eligible volume identifier and level-0 voxel size;
- the canonical ScrolIQ tree SHA-256 of the complete TIFXYZ directory;
- the TIFXYZ `meta.json` hash, `target_volume`, and 2D scale;
- the exact controlled argv plus explicitly allowed extra arguments;
- group index, render scale, and forced one-slice contract;
- the complete renderer log hash;
- the raw `00.tif` SHA-256, byte size, dimensions, and image mode.

The Villa commit is reproducibility metadata; the executable SHA-256 is the
cryptographic identity of the binary that actually ran.

## Verify a frozen receipt

```bash
scroliq-vc3d verify \
  --root-dir submission-work \
  --receipt evidence/column_01.vc3d.json
```

This re-hashes the TIFXYZ tree, `meta.json`, raw TIFF, and render log,
re-decodes the TIFF, re-checks the eligible-volume target in the mesh
metadata, and reconstructs the critical VC3D argv.

If the original or rebuilt VC binary is available, also verify it:

```bash
scroliq-vc3d verify \
  --root-dir submission-work \
  --receipt evidence/column_01.vc3d.json \
  --binary /opt/villa/bin/vc_render_tifxyz
```

That additionally re-hashes the executable and its `--help` output.

## Relationship to the final image

The receipt intentionally stops at the raw CT/mesh-derived TIFF. The next
step is `scroliq-submission-image column`, which adds the required 1 cm
scale-bar footer without modifying the papyrus pixels.

Grand Prize provenance schema v7 binds these two proofs together. Every render
must declare a hash-pinned `vc3d_receipt`; with `--root-dir`,
`scroliq-provenance` verifies the receipt and requires its raw-output SHA to
equal the submission-image proof's input SHA. The receipt's group index, render
scale, base voxel size, mesh path/tree hash, and eligible volume must also match
the corresponding manifest and scale-proof fields.
