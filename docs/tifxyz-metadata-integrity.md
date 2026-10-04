# TIFXYZ metadata integrity: recompute, then compare

**Rule.** Spatial metadata is always recomputed from a surface's valid
vertices and compared with what `meta.json` declares. A declared bbox is never
used alone for a proof-relevant decision such as filtering, separation or
selection.

## Why a stale bbox is dangerous

A bbox that *contains* its surface is an upper bound: filtering on it can only
keep too much. A **stale** bbox, one that valid vertices lie outside of, is not
an upper bound at all. A spatial prefilter built on it silently discards real
geometry, and nothing fails. One such report concerns the PHercParis4
spiral-input pack of verified patches (maintainers' note: a little over a
hundred patches, most stale in Z, the worst by several hundred slices; **not
reproduced here**: run the census below to obtain a repository-traceable count).

## What changed

`scroliq-mesh` (`audit_tifxyz`) always recomputes `observed_bbox_xyz` and now
classifies the declared bbox in `bbox.status`:

| Status | Meaning |
| --- | --- |
| `consistent` | declared bbox contains the recomputed bounds (loosely or exactly) |
| `stale` | valid vertices lie outside it by more than the tolerance; `stale_axes`, `excess_voxels_xyz` and `max_excess_voxels` say where and by how much |
| `undeclared` | no bbox in `meta.json`; there is nothing to be stale |
| `unreadable` | present but malformed (wrong shape, non-numeric, non-finite, minima above maxima) |
| `unverified` | the surface has no valid vertices, so there is nothing to compare; never reported as `undeclared` |

A stale bbox adds a `stale-bbox` review finding. The audit's own tolerance
stays at 1e-3 voxel (unchanged); the run guard and the census use 1 voxel
because producers quantize bounds to integers. Slack (a loose box) is recorded
as `max_slack_voxels` but is not a defect.

`recompute_bbox`, `compare_bbox` and `geometry_digest` are importable from
`scrollq.tifxyz_audit` so other code does not re-implement validity rules.

`scroliq-vc3d-run-guard` adds a blocking `spatial_metadata_consistent` gate
([guard contract](vc3d-run-guard.md)).

## Census over a patch pack

```bash
scroliq-bbox-census --root path/to/verified_patches --out out/bbox-census.json \
  [--validity tifxyz|nonnegative-xyz] [--tolerance-voxels 1] [--workers 8] \
  [--all-rows] [--fail-on-defects]
```

For every TIFXYZ directory under `--root` it recomputes the bounds from the
decoded vertices, compares them with `meta.json`, and counts the valid
vertices a filter on the declared box would lose
(`vertices_outside_declared_bbox`). The summary gives patches inspected, counts
by status, stale counts per axis, the worst excess and the lost-vertex total.

Built-in controls (lesson 9):

- every run first passes a **positive control**: planted exact, stale-Z (654
  voxels), stale-X and undeclared patches must be classified correctly, or the
  verdict is `control-failed`;
- a census that inspected **nothing** is `unverified`, never `clean`.

### Validity rule matters

The audit's rule (`tifxyz`) treats a vertex as valid when `z > 0` (VC3D marks
holes with −1). The upstream spiral convention counts a vertex valid when every
coordinate is ≥ 0 (`nonnegative-xyz`). They differ only for `z == 0` or
negative x/y. The census records which rule ran; **compare a count with a
published one only under the same rule**, and run both when reproducing.

The census has not been run on the real pack in this repository (data hosts are
reachable from CI, not from every development environment). Commit its output
create-only under a dated `artifacts/` directory when it is run.

## Where declared bounds are consumed

| Consumer | Uses declared bounds as | Disposition |
| --- | --- | --- |
| `scroliq-mesh`, `scroliq-vc3d-run-guard` | compared against recomputed bounds | now flags / blocks stale |
| `scroliq-passport` | carries the audit's `bbox` block through | now includes `status` |
| `bin/winding_patch_index.py` → `bin/winding_attach.py` (PHercParis4 O2 step 3) | download prefilter selecting which patches to read; the pre-registered scope was chosen from `meta.json` bounds | **frozen, not edited.** Attachments are a lower bound if any in-scope patch had a stale box. Run the census over the same pack; any rerun with recomputed bounds is logged as a deviation per [the protocol](winding-attachment-protocol.md), as a separately labelled arm |
| `scrollq-geometry-probe` (`candidate_bbox`) | the candidate pool's `bbox` drives window ordering and the fit/held-out separation certificate | the frozen 2026-09-30 pool's PHerc0800/PHerc0813 candidates carry `meta_sha`, `uuid`, `area_vx2`, `scale` and a float `bbox` alongside `bounds_status: "complete"`, which reads as a copy of each atlas mesh's `meta.json` (an inference from the fields, not a recorded fact); `complete` records that bounds were present, not that they were checked against vertices. The pool is frozen and is not edited. A **new** split should recompute bounds with `recompute_bbox` before certifying separation |
| `scroliq-sheetness-plan` | computes its cutout box from surface points | recomputed already; no change |

Declared bounds may still be used as a hint to *skip reading* only when they
have been verified against the vertices; otherwise read the geometry.
