# Ink relief witnesses, relief-conditioned training and per-component passports — 2026-10-05

**Decisions:**

- **INCLUDE** the per-component physical-evidence passport
  (`scroliq-ink-passport`, [contract](../ink-passport.md)).
- **EXPERIMENT FURTHER** on a CT-native geometry-only relief witness.
- **DISMISS for now** relief-conditioned ink training.

No inference, training or rendering path changes.

## What already exists (correcting the premise)

The proposal says ScrollQ has no topography, surface-offset or depth-profile
ink work. It does, and the new experiment must build on it rather than
duplicate it:

| existing | what it does | relation to the relief witness |
|---|---|---|
| [`scroliq-morphology-control`](../morphology-ink-control.md) + `scroliq-morphology-benchmark` | Pins the public profilometry release of the topography paper (`scrollprize/profilometer@a806bead…`, CC BY-NC 4.0). Preregisters a leave-one-papyrus-out, rank-normalized descriptor benchmark with label-roll and missingness controls. Blocks CT transfer outright | the **optical** half: is morphology an ink signal at all, papyrus-held-out |
| [`scroliq-normal-response`](../normal-response.md) | Runs the frozen ink model at signed normal offsets (−6…+6 voxels) and records per-component depth profiles | surface-locking of the **model's** response, not physical relief |
| [2026-10-05 research note](2026-10-05-winding-conservation-and-watch.md) §3 | Records the paper's resolution bandwidth as WATCH | the source of the sampling caveat below |

**The sampling caveat still holds.** The pinned release records
0.688 µm/pixel; the manuscript says 0.34 µm, and the dataset's own notice says
the discrepancy is unresolved. The phenomenon — morphology separates written
from unwritten papyrus — does not depend on that number. Every absolute scale
derived from the paper does, including the resolution cutoff.

What is genuinely new here is a **CT-native** witness: relief measured from the
submitted mesh and the raw CT, never from optical profilometry and never from
the ink map.

## 1. Geometry-only relief witness — EXPERIMENT FURTHER

**Hypothesis.** The ink layer changes the local papyrus surface. After
low-frequency sheet curvature is removed, a residual microtopography field
computed from TIFXYZ + raw CT separates verified ink from matched non-ink
papyrus. It does so independently of the ink network.

**Witness construction.** The witness never reads the ink probability.

1. From the submitted TIFXYZ, sample CT along the local normal at each surface
   point. Estimate the papyrus–air boundary per normal ray as a sub-voxel
   surface height.
2. Remove low-frequency sheet shape with a fixed-scale smoother. Its scale is
   the only nuisance parameter fit on training fragments.
3. Write the residual as `relief_support.tif` in the render's UV frame.
   `scroliq-ink-passport --relief` then attaches an inside-vs-matched-ring
   statistic to every frozen candidate component.

**Decisive test, frozen before any held-out number is read:**

- Freeze ScrollQ's ink candidates first, per fragment.
- Fit only the curvature and fiber-removal scales, on training fragments.
- On entirely held-out fragments, compare AUROC/AUPRC of
  *raw ink probability* against *ink candidate × relief witness*.
  - The reference is the visible/IR ink on detached fragments, where writing
    is exposed.
  - Hard negatives: blank papyrus, cracks, fiber crossings, damaged surfaces.
- No Greek, OCR or language information enters.

**Controls.** All three are required. A witness that survives any one of them
is measuring shape, not ink.

- **Label roll:** the toroidal shift already used by the morphology benchmark.
- **Mesh offset:** run the witness on a surface displaced ±2–4 voxels along
  the normal, which reuses the `normal-response` offsets.
- **Missingness / damage:** score the reconstruction-failure mask on its own.

**Promotion gate.**

1. The held-out fragment AUPRC of candidate × witness exceeds raw probability.
2. The fragment-level bootstrap CI excludes zero gain.
3. All three controls collapse to chance (within 0.05 AUROC).
4. The witness's sign is consistent across held-out fragments, or is reported
   per fragment. A fixed "ink is raised" rule stays dismissed.

**Blockers and honest risks:**

- **Labelled fragments.** Calibration needs detached fragments that have CT, a
  mesh and an external visible/IR ink reference. None is pinned in ScrollQ
  yet. Pinning one, with license evidence and hashes, is the first step.
- **Resolution.** The optical result degrades sharply with lateral sampling.
  Whether fragment CT at typical voxel sizes, after meshing and normal
  sampling, keeps enough relief is exactly what is unknown. A null result at
  ~8 µm is a plausible outcome and must be published as such.
- **Shared inputs.** The mesh is shared with the ink model's input. An
  independent witness means no shared *learned* component, not no shared data.
  Mesh errors can still correlate both.

Self-evaluation:

| criterion | rating |
|---|---|
| prize impact if validated | high |
| plausibility | high for the phenomenon; **open** for CT transfer |
| evidence burden | medium |
| cost | medium |
| reproducibility | good |
| hallucination risk | low (no linguistic prior) |
| leakage | low with fragment-level splits |
| VC3D compatibility | high (one more surface field) |

## 2. Relief-conditioned ink model — DISMISS for now

Feeding relief or curvature channels into the ink network would entangle the
two evidence sources and destroy the witness's independence. It would add a
retraining surface, and it could teach the network to turn cracks or fiber
texture into letter-shaped positives.

Reconsider only after the independent witness passes its held-out promotion
gate. Even then, the fused model must be compared against witness-as-gate on
the same held-out fragments. Recorded in
[dismissed-and-deferred.md](dismissed-and-deferred.md).

## 3. Physical-evidence passport per component — INCLUDE

Implemented as [`scroliq-ink-passport`](../ink-passport.md), emitted from
existing provenance rather than a new subsystem. It reuses:

- the `scroliq-provenance` region-box format and overlap test;
- the `scroliq-ink-validate` prediction loaders;
- the TIFXYZ decoder and decoded-geometry digest.

For each 8-connected component or reviewer letter region it records:

- UV extent;
- level-0 CT coordinates through the submitted mesh;
- prediction and surface hashes;
- checkpoint SHA-256;
- point-by-point training-region exclusion;
- the raw ink score;
- the relief-support statistic, or `not-measured`.

Missing evidence stays `unknown` or `not-measured`, never `clear`. It does not
improve a weak letter; it makes every strong letter auditable.

Self-evaluation:

| criterion | rating |
|---|---|
| prize impact | medium |
| plausibility | very high |
| evidence burden | low |
| cost | low |
| reproducibility | low burden |
| hallucination risk | favourable |
| VC3D compatibility | high |
| added surface area | minimal |
