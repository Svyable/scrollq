# winding-sync, constraint-gauge and flattening nondeterminism

**Status:** research decision, 2026-10-06. This note adds
`scroliq-winding-sync`, `scroliq-constraint-gauge` and `scroliq-render-noise`,
plus a dated synthetic calibration
(`artifacts/2026-10-06-winding-sync-synthetic/`). No scoring behaviour,
frozen artifact or Grand Prize execution order changes.

## Sources and what they claim

None of the following figures is reproduced in this repository except where
noted. Cite them as the projects' own reports.

- **`winding-sync`** (MIT) treats pairwise winding observations as an L1
  synchronization problem over integers. The constraint matrix is totally
  unimodular, so the LP optimum is integral. Its synthetic benchmark at 10%
  corrupted constraints reports BFS 0.454, L2 0.812 and L1 0.973. At 3.7
  edges/node, L1 reaches 1.000 while BFS stays at 0.528.
- **`constraint-gauge`** scored `winding-sync`'s *automatic* constraint
  generator against human winding ground truth. The generator's internal
  metric read 0.670 exact agreement; external truth gave 0.050, with a mean
  absolute residual of 21.5 windings. L1 still beat BFS on that graph
  (0.050 vs 0.017), but the dominant error is the measurement generator.
  During development, smoothing halved the recovered winding count while the
  internal agreement improved to its best value, 0.863.
- **`vesuvius-autoresearch`** (MIT) reports that Lasagna flattening is
  nondeterministic on byte-identical inputs: about 7 voxels of in-plane
  layout shift and 3.04% change in `total_fg_pixels`. Deterministic PyTorch
  algorithms made x/y/z.tif bit-identical (24 pixels of repeat variation) at
  about 9.5× the cost. With that floor, a ±4-voxel displacement of one fitted
  surface changed recovered ink by −19.77% inward and −4.48% outward.
  Independently fitted surfaces stayed variable.

What *is* reproduced here: the reconciler behaviour on synthetic graphs.
L1 promotes on a redundant graph and gives no material gain on a
bridge-heavy one; see the artifact README.

## Decisions

| Idea | Decision | Implemented as | Next evidence |
|---|---|---|---|
| L1 integer winding synchronization of *trusted* observations | **INTEGRATE** | `scroliq-winding-sync` ([doc](../winding-sync.md)): BFS / L1 / L2 reconcilers, integrality-checked LP, frozen planted-corruption campaign with bridge and BFS-tree classes | Human-verified Villa/ScrollQ winding graph, frozen with cyclomatic number and bridge count; PROMOTE only under the frozen rule |
| External calibration for every winding-constraint producer | **INTEGRATE EXPERIMENT** | `scroliq-constraint-gauge`: sealed truth, producer-neutral scoring, internal metrics recorded as not evidence, confidence must earn weight per bin | First sealed human-verified pair set; score human, automatic and reconciled producers on it |
| `winding-sync` automatic constraint generator | **WATCH** | none; may be scored by the gauge in isolated experiments | External exact agreement must rise substantially; never feeds prize geometry before then |
| `winding-sync` direct surface extraction | **DISMISS** for now | none | An end-to-end real-scroll demonstration; it inherits the generator's noisy winding field |
| Deterministic flatten/render or a measured noise floor for small-effect claims | **INTEGRATE NOW** for controlled experiments | `scroliq-render-noise`: passport `measurement_noise` block, k × floor rule, determinism mode required | First within-surface perturbation experiment records it; not required on every production render |

## General rule

**Internal consistency ≠ external correctness.** Cycle consistency,
constraint-satisfaction rate and recovered winding range are never accepted
as evidence that generated constraints are right. Optimising them can select
the more wrong system.

## Provenance

The code of `winding-sync` and `vesuvius-autoresearch` is MIT. Vesuvius CT,
meshes and annotations keep their own dataset provenance. Current Challenge
scans and legacy EduceLab scans are distinct datasets and must be recorded
separately in passports.
