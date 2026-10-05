# Winding conservation (layer count, pitch, identity continuity)

**scroliq-winding-conservation** checks a stitched winding solution against
conservation laws that no single surface was built to satisfy. It is
evaluation-only: it reads geometry and winding labels, never ink, and never a
reference solution.

Research context and decision: [2026-10-05 research note](research/2026-10-05-winding-conservation-and-watch.md).

## Input

- `--solution`: an `.npz` with `xyz` (N × 3, base-voxel XYZ, the VC3D order)
  and `winding` (N integer labels). A whole scroll or a large window.
- `--umbilicus`: the upstream `umbilicus.json` (`control_points` with x/y/z,
  linear in z, extrapolated beyond the ends; the same reader as
  `scroliq-winding`).
- `--branch-cut-degrees`: the angle, in the umbilicus frame
  (`atan2(y − y_axis, x − x_axis)`), at which labels step by one. Default 0.
- `--voxel-um`: optional, so the pitch is also reported in µm.

## Invariants

The solution is binned into (θ, z) cells: 72 angular bins of 5°, starting at
the branch cut, and 16-voxel z bins. Within a cell, a label's crossing is the
median radius of its points (at least 3 points are needed).

| family | rule (frozen in `winding_conservation.py`) | catches |
|---|---|---|
| `layer_count` | the label-free crossing count equals the label span. Crossings closer than 0.3 × the ray's median gap count as one. Consecutive labels step by the solution's orientation (±1) | deleted, coincident and merged identities; skipped labels |
| `pitch` | every label-free gap lies within 0.6–1.4 × the ray's median gap | missing sheets (2×), merges (1.5×), coincident surfaces |
| `continuity` | for each cell boundary (θ neighbours with wrap, z neighbours), follow each shared label: l → l, and l → l ± 1 at the declared cut. The median radial shift and the shift difference between consecutive labels must both stay ≤ 0.5 × pitch. An interior label must not vanish | duplicated or merged identities that shift outer labels; sheet switches; wrong branch cut |
| `support` | a crossing's points/radius is at least 0.5 × the cell median | partial deletions inside a cell |

A cell is evaluated once it has at least 3 gaps (4 crossings). `status` is one
of four values:

- `consistent`: evaluated, nothing flagged;
- `review`: flagged cells are listed with their z range, θ range and families;
- `not-evaluated`: nothing could be evaluated;
- `unverified`: the built-in positive control failed to fire.

`measure` always runs that positive control: it deletes the median winding over
45° × 64 voxels at the solution's median z and requires the window to flag more
cells than the unmodified solution does.

These thresholds are ScrollQ's own. They were written before any real solution
was measured, and none was taken from `vesuvius-sheet-tools`. Changing one
means a new method version and a new calibration artifact.

## Calibration

`calibrate` plants four defects into a solution: the built-in synthetic spiral
by default, or `--solution` for a real one.

- **delete:** winding k is removed inside the footprint.
- **duplicate:** k is emitted twice, 1 voxel apart, and outer labels shift +1.
- **merge:** k and k+1 become one surface halfway between them, and outer
  labels shift −1.
- **switch:** k's surface is replaced by k+1's own vertices. Local CT seating
  is unchanged; only identity is wrong.

The ladder covers θ extents of 2.5–360° and z extents of 4–128 voxels, with 16
seeded placements each. A family *fires* when any cell in the footprint,
dilated by one cell, carries its flag. Next to each detection rate, the null
rate is the same footprint measured on the unmodified solution. The *smallest
reliable extent* is, per z extent, the smallest θ extent from which every
larger θ extent reaches a detection rate of at least 0.95.

```bash
scroliq-winding-conservation calibrate --seed 0 --placements 16 --out out/calibration.json
scroliq-winding-conservation measure --solution sol.npz --umbilicus umbilicus.json \
  --voxel-um 7.91 --branch-cut-degrees 0 --out out/conservation.json
```

Synthetic result: [`artifacts/2026-10-05-winding-conservation-synthetic/`](../artifacts/2026-10-05-winding-conservation-synthetic/README.md).
No real stitched solution has been measured yet.

## What it does not show

A `consistent` report says the labels are self-consistent at cell resolution.
It does not establish:

- CT support;
- recto coverage;
- that the labels match the physical windings.

A flag is a review cue. Folds, tears, crushed regions and the scroll's own
start and end break these invariants legitimately. Defects smaller than about
one cell barely move a cell's median radius. Fixed 5° cells are long at large
radius, so real false-alarm rates must be measured on real solutions.
