# PHerc0826 baseline reproduction check

A successful optimizer exit is not enough to call a GPU run the frozen
PHerc0826 baseline. `scroliq-spiral-reproduction-check` sits between
`scroliq-spiral-run` and `scroliq-spiral-export` and verifies the
published structured sanity context for the same bounded fit.

```bash
scroliq-spiral-reproduction-check \
  --run-dir /runs/pherc0826-bounded-01 \
  --out /runs/pherc0826-bounded-01/reproduction-check.json
```

The gate re-verifies the frozen recipe and stdout hashes, then locates the
single Villa `satisfaction_metrics_fitted.json` in the run receipt inventory
and verifies those bytes before reading them.

For the frozen recipe, a `sanity-match` requires:

- **480,117** tracks loaded;
- exact z ROI `[11000, 12000)`;
- structured `total_tracks` equal to the stdout load count;
- `satisfied_tracks_fraction` rounding to the published **12.6%**;
- `satisfied_track_points_fraction` rounding to the published **41.6%**.

Those percentages are reproduction diagnostics, not correctness targets.

The public context also records `dr_per_winding = 14.8851` voxels. This
dependency-light gate does not import PyTorch only to deserialize the
checkpoint, so that value remains explicitly listed as mechanically unverified
instead of being silently claimed.

`scroliq-spiral-export` requires this report explicitly, independently recomputes the same check from the run bytes, requires semantic equality with the supplied report, and verifies that it is a `sanity-match` bound to the exact run receipt. The gate therefore cannot be bypassed by editing the JSON or invoking the official export wrapper directly. A drift report is
itself useful evidence that the supposedly frozen baseline differs before a
reconstruction intervention is introduced.
