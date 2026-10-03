# Held-out geometry evaluation — O3 foundation

Implemented: deterministic point-correspondence residuals on a frozen target
set. Not implemented here: a spiral fitter, native checkpoint adapter,
nearest-surface matching, or proof that a surface stays on the correct sheet.
No real fit has been evaluated by this new tool yet.

`scroliq-geometry-validate` compares known reference XYZ points with model
predictions for the same target IDs. Coordinates are base-resolution CT
voxels in XYZ order. Never mix rescan coordinates, pyramid levels or microns.
The volume-root strings must match exactly; aliases are deliberately refused.

## Freeze before fitting

Create a version-1 specification with these fields:

```json
{
  "schema_version": 1,
  "volume_root": "exact-scan.zarr",
  "coordinate_system": "base_voxel_xyz",
  "tolerance_voxels": 5,
  "fit_ids": ["fit-a"],
  "targets": [{"id": "hold-a", "xyz": [0, 0, 0]}]
}
```

This example is synthetic. Choose and justify the tolerance, correspondence
definition and evaluation points before seeing predictions. Commit the spec
before training/fitting. Calculate its binding hash:

```bash
scroliq-geometry-validate --spec spec.json --print-spec-hash
```

Keep the reference coordinates out of the fitting pipeline. Use
`scrollq-geometry-probe` to certify spatial separation separately; ID
disjointness alone cannot establish independence. Derived supervision,
nearby input influence and checkpoint history require separate provenance.

## Export model predictions

The prediction JSON repeats `schema_version`, `volume_root` and
`coordinate_system`; includes `spec_sha256` from the command above, the real
`checkpoint_sha256`, and `used_fit_ids`; and supplies `predictions`:

```json
[
  {"id": "hold-a", "status": "ok", "xyz": [3, 4, 0]},
  {"id": "hold-b", "status": "failed", "reason": "no prediction"}
]
```

Every ID must belong to the frozen target list (add `hold-b` to that list
before the run if it is intended). Unknown IDs, duplicates, held-out IDs
in fit inputs, undeclared fit IDs and a changed spec are rejected.
Checkpoint identity and fit usage are declarations, not independently verified
training history. A native spiral-fitting exporter is still needed; this
portable JSON boundary makes no claim to be the upstream checkpoint format.

```bash
scroliq-geometry-validate --spec spec.json --predictions predictions.json \
  --out result.json
```

Output paths must be new. Exit 0 means all declared targets have predictions
within the chosen tolerance; 1 means missing/failed/out-of-tolerance targets;
2 means invalid input or I/O failure. None means Grand Prize readiness.

The denominator always includes every frozen target. Missing predictions
and explicit failures cannot increase the within-tolerance fraction. Median
and maximum residuals are explicitly *predicted-only*; interpret them with
the completeness counts. Threshold equality counts as within tolerance.
Empty reference sets are rejected. Results carry canonical input hashes.

## Next evidence milestone

Pin the upstream fitter revision and its exported coordinate mapping. Fit
without the held-out collections, then evaluate predictions for all frozen
targets, including failed regions. Run a deliberately displaced prediction
control; retain the full fit config, checkpoint hash and exclusion evidence.
Report actual residuals without translating them into readability, sheet
identity or topology claims. Synthetic tests currently verify the machinery
only; the October O3 goal remains incomplete.
