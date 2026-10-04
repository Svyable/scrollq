# VC3D semantic run guard

`scroliq-vc3d-run-guard` closes a reproducibility hole that ordinary process
supervision cannot: an external geometry program can exit successfully while
producing no usable surface.

The guard is intentionally generic enough for VC3D geometry commands such as
`vc_grow_seg_from_seed`, but it does not claim that every VC3D program emits
TIFXYZ. Use it only when the preregistered expected product is a TIFXYZ
surface.

## Contract

Before launch the guard requires that the expected output directory and both
log paths do **not** exist. This prevents a stale surface from being mistaken
for a newly generated result.

After the command exits, the guard requires all of the following:

- the process launched and returned exit code zero;
- the expected TIFXYZ directory was newly created;
- the surface passes the non-vacuous structural part of `scroliq-mesh`
  (the audit itself must not be `fail`);
- the declared minimum number of valid vertices exists;
- the declared minimum number of valid quads exists;
- the measured 3D surface area is finite, positive, and at least the frozen
  minimum area;
- when requested, a supplied Villa surface-preflight report must bind the
  exact output to the declared CT volume.

A zero exit code with any failed postcondition is recorded explicitly as
`exit_zero_but_postcondition_failed=true`.

This is the `PIPELINE_EXECUTION_INTEGRITY` proof gate. It is deliberately
narrow: passing it does not establish winding identity, held-out geometric
accuracy, topology, ink, or Grand Prize completeness.

## Example

```bash
scroliq-vc3d-run-guard \
  --output-tifxyz out/grown.tifxyz \
  --volume-root s3://vesuvius-challenge/.../volume.zarr \
  --voxel-size-um 7.91 \
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

The receipt hashes stdout, stderr, the resolved executable when it is a local
file, and all TIFXYZ semantic files through the embedded mesh audit. The
`--out` receipt is create-only.

## Why this exists

A public VC3D failure report showed a growth command accepting an `s3://`
volume, computing zero area through an unsupported filesystem path, deleting
the grown surface for falling below its minimum-area rule, and nevertheless
returning success. ScrollQ therefore treats process success as necessary but
not sufficient evidence.

The guard reuses existing ScrollQ geometry auditing rather than adding a
second TIFXYZ parser or a parallel definition of surface validity.
