# Ink and false-positive research

This note consolidates the exploratory ink ideas developed outside the primary
dependency-order pipeline. The emphasis is not on producing more visually
convincing text. It is on making false ink harder to survive.

## 1. Surface-normal response curves

**Status:** EXPERIMENT FURTHER. The frozen v1 measurement harness is now
implemented as `scroliq-normal-response`, but no empirical promotion has been
made. Existing one-off normal controls remain useful; the continuous response
curve still has to earn inclusion on held-out data.

### Hypothesis

If ink is physically tied to the recto surface, a frozen detector evaluated on
the same held-out material at signed offsets along the surface normal should
show a reproducible response maximum near the true sheet. Cracks, internal
fibers, neighboring windings, or geometry leakage may have broader, shifted, or
flatter profiles.

A minimal frozen displacement series is something like:

`-6, -4, -2, 0, +2, +4, +6` voxels.

Useful measurements include:

- center advantage over the strongest off-surface response;
- peak displacement;
- near/far decay;
- signed asymmetry;
- response width;
- consistency across neighboring material points.

### Executable v1

The committed harness fixes the non-zero displacement grid at
`-6, -4, -2, +2, +4, +6` voxels and treats the submitted-surface prediction
as offset zero. It reports the per-offset ink/background response curve, the
zero-surface advantage over the strongest off-surface response, strict
zero-peak fractions, unique-peak histograms, and a conservative center-wins
gate applied at the already-declared ink threshold. Ties never count as
surface-localized.

A protocol-complete run must also bind the exact surface geometry by SHA-256
and hash a frozen sampling manifest that records the normal convention, CT
source, interpolation/sampling settings, and inference command. Partial or
custom offset grids are still measured, but they fail the v1 completeness
gate rather than silently becoming comparable evidence.

`experimental_evidence_ready` means only that this held-out falsification
artifact is complete enough to inspect. It is deliberately not a claim of ink,
legibility, or Grand Prize readiness. See
[normal-response.md](../normal-response.md).

### Component-level advance

The v2 report now closes a gap in the original pixel-only design: it freezes
8-connected components from the nominal prediction and measures each entire
component on the identical material support across the full offset stack. This
produces per-component peak offsets, nominal-vs-off-surface mean advantage,
off-surface persistence, and coarse depth-span evidence.

This is materially stronger for glyph-like false positives because a plausible
letter is evaluated as one coherent prediction rather than as disconnected
pixels. It also avoids re-segmenting each offset, which would permit spatial
drift to masquerade as depth persistence.

With an optional hash-bound surface XYZ map, non-nominal-peak components become
native VC3D review points through `scroliq-vc3d-review --kind
normal-response-component`. No automatic suppression is applied. The component
layer remains **EXPERIMENT FURTHER** until held-out real-ink campaigns show that
component depth specificity separates true ink from false positives across
folds/checkpoints.

### Promotion gate

Promote only if held-out true ink shows materially stronger and more stable
surface localization than false positives and controls, across folds/checkpoints.
Geometry must be frozen before any ink response is inspected.

### Kill criterion

Dismiss the continuous-profile layer if curves are flat, checkpoint-specific,
or equally center-peaked under wrong-surface / shuffled / adjacent-winding
controls.

### Self-evaluation

- prize impact: **high if discriminative**
- plausibility: **high**
- evidence burden: **moderate**
- implementation cost: **low**
- reproducibility burden: **low-moderate**
- hallucination risk: **low; intended to reduce it**
- VC3D compatibility: **high**
- unnecessary surface area: **small if kept as an analysis artifact**

## 2. Causal context ablation

**Status:** EXPERIMENT FURTHER.

### Hypothesis

A plausible-looking prediction is more trustworthy if the model actually needs
local physical CT evidence to produce it. Freeze a checkpoint and held-out
region, then intervene on the input:

- preserve the local physical neighborhood while destroying progressively more
  distant context;
- preserve distant context while destroying the central physical evidence;
- use at least two corruption families, such as matched-papyrus replacement and
  block shuffling.

The desired signature is asymmetric: distant-context removal should preserve
more genuine-ink performance than destruction of the central evidence.

### Why this is distinct

Normal-offset controls ask **where** the supporting signal is. Context ablation
asks **what evidence causes the model to fire at all**. A letterform that
survives destruction of its local CT evidence is a serious warning even if the
ordinary score looks strong.

### Promotion gate

Require the same direction of effect across held-out folds/checkpoints and at
least two intervention families. False positives must not exhibit the same
local-evidence dependence as true ink.

### Kill criterion

Dismiss if corruption family, radius, or checkpoint determines the conclusion,
or if the intervention mostly creates out-of-distribution artifacts.

### Self-evaluation

- prize impact: **high if discriminative**
- plausibility: **high**
- evidence burden: **moderate**
- implementation cost: **moderate**
- reproducibility burden: **moderate**
- hallucination risk: **potentially strongly reduced**
- VC3D compatibility: **high**
- unnecessary surface area: **low if implemented as an experiment only**

## 3. Morphology/topography corroboration

**Status:** INCLUDE as a staged source-control framework; sealed-scroll target
transfer remains EXPERIMENT FURTHER.

See [morphology-ink-control.md](../morphology-ink-control.md).

### Hypothesis

Ink may alter local surface morphology independently of the CT texture channel.
A morphology-only branch can therefore serve as independent physical
corroboration rather than merely another semantic ink model.

The clean experiment is a matched comparison:

1. CT-only;
2. morphology-only;
3. late-fusion CT + morphology;
4. a conservative consensus map where independent branches agree.

The strongest value would be lower false-positive rate at useful recall, not a
prettier render.

### Evidence requirements

Leave-one-papyrus-out validation is essential. Surface-reconstruction errors,
instrument missingness, and resolution dependence must be controlled. The
current implementation correctly fails closed on absolute-scale target transfer
while the public profilometry sampling discrepancy remains unresolved.

### Self-evaluation

- prize impact: **high**
- plausibility: **medium-high**
- evidence burden: **high**
- implementation cost: **moderate**
- reproducibility burden: **moderate**
- hallucination risk: **potentially lower, but correlated errors are possible**
- VC3D compatibility: **high**
- unnecessary surface area: **acceptable only as a falsification/control path**

## 4. Acquisition-physics normalization and conditioning

**Status:** EXPERIMENT FURTHER.

### Hypothesis

Cross-scroll generalization may be limited partly by acquisition/reconstruction
domain shift rather than by insufficient semantic context. Instead of enlarging
the model window, preserve the raw CT channel and add physically interpretable
scan conditioning.

Candidate arms:

- baseline preprocessing;
- model conditioning on acquisition metadata such as voxel size, beam energy,
  and relevant reconstruction parameters;
- reference calibration using stable materials such as air / Nylon 12 where
  valid and available, while retaining the untouched raw channel;
- metadata conditioning + reference-calibrated auxiliary channel.

### Evaluation

Use leave-one-scroll or, preferably, leave-one-acquisition-regime-out
evaluation. Random patch splits are not sufficient. Measure held-out PR-AUC,
F1/FPR, and cross-regime variance. Freeze calibration masks and transforms
before inspecting target-scroll readability.

### Self-evaluation

- prize impact: **high if domain shift is material**
- plausibility: **high**
- evidence burden: **moderate**
- implementation cost: **low-moderate**
- reproducibility burden: **low**
- hallucination risk: **low**
- VC3D compatibility: **excellent**
- unnecessary surface area: **small as an optional input adapter**

## 5. Cross-parameterization inference invariance

**Status:** EXPERIMENT FURTHER. Tracked in
[issue #137](https://github.com/Svyable/scrollq/issues/137).

### Hypothesis

A frozen detector should produce materially consistent evidence for the same
physical papyrus when inference is performed through two independently valid
surface parameterizations, once predictions are mapped back into
triangle/barycentric material coordinates.

This tests representation sensitivity, not whether deterministic coordinate
transport is deterministic.

Useful outputs:

- held-out metric per parameterization;
- material-coordinate probability agreement;
- thresholded IoU / precision-recall agreement;
- component or stroke persistence;
- disagreement versus UV distortion, seams, and rasterization footprint;
- consensus precision/FPR at a predeclared recall floor.

### Important negative result

The original transport-only form is **DISMISSED**. If one already-frozen scalar
field is merely re-rasterized through UV-A and UV-B, true ink and
material-attached false positives should both persist. That experiment would
mostly measure interpolation.

### Promotion gate

Require a real detector whose input path depends on the representation, a
second valid parameterization, and a held-out gain or meaningful falsification
signal beyond ordinary resampling error.

## 6. Stride/blend/seam invariance

**Status:** EXPERIMENT FURTHER. Tracked in
[issue #143](https://github.com/Svyable/scrollq/issues/143).

### Hypothesis

Ink predictions should not depend strongly on arbitrary sliding-window stride,
overlap, or blending choices over the same physical region.

The current Villa flat runner already exposes enough controls for a cheap first
experiment:

- baseline overlap + Hann blending;
- one alternate stride/overlap;
- one alternate non-pathological blend mode.

Measure held-out discrimination, prediction agreement, component persistence,
and disagreement as a function of distance to tile boundaries.

Only if this Stage-A sweep shows material sensitivity should a true tile-origin
phase intervention be considered.

### Promotion gate

A consensus method earns promotion only if it lowers held-out FPR or improves
precision at a frozen recall floor, repeats on another fold/checkpoint, and has
a mechanistic relationship to seam/tiling nuisance variables.

### Self-evaluation

- prize impact: **medium-high**
- plausibility: **high that outputs vary; unknown that consensus helps truth**
- evidence burden: **moderate**
- implementation cost: **low for Stage A**
- reproducibility burden: **low**
- hallucination risk: **potentially reduced**
- VC3D compatibility: **excellent**
- unnecessary surface area: **low if kept as an experiment wrapper**


## 7. Deterministic volumetric-texture corroboration

**Status:** WATCH. Clean-room experiment only. Do not copy, vendor, modify, or
depend on the deposited implementation; do not feed this signal into training
or weak-label generation.

### External result and provenance

Korotetskyi and Haindl, *Volumetric Texture Analysis for Unsupervised Ink
Detection in Herculaneum Papyri* (2026), DOI
[10.5281/zenodo.20766169](https://doi.org/10.5281/zenodo.20766169), applies
three training-free 3-D signals directly to an unwrapped CT depth slab:
first-order statistics, Laws texture energy, and block spatial
autocorrelation. The published method fuses the volumetric responses, projects
them through a depth prior, applies a soft Markov random field, and adaptively
thresholds the result.

The Zenodo record reports evaluation on 25 manually annotated PHerc.172
specimens, with the best individual descriptor at mean MCC 0.374 and positive
MCC on every specimen. It also reports partially recognizable structure on a
full segment agreeing with an overlapping community ink prediction. Treat
those as **external reported results**, not ScrollQ measurements.

The Zenodo record currently exposes a 259.2 MB submission archive and paper,
but its Rights field states only copyright © 2026 Oleksandr Korotetskyi and
Michal Haindl. No MIT/Apache/BSD/CC software license was established in the
2026-10-04 review. Therefore the deposited implementation is not an admissible
dependency for ScrollQ unless a compatible license is later established.

### Why it is distinct

This is not another morphology/topography branch. It operates on volumetric CT
texture rather than surface relief, requires no learned checkpoint, and can
produce an inspectable per-voxel evidence field. Its highest-value role is
therefore as an independent witness for existing false-positive controls:
synthetic detectability, derivation invariance, normal-response / local-evidence
tests, and hallucinated-ink review.

The independence is the feature. Turning the signal immediately into another
training feature or pseudo-label source would weaken that independence and can
create circular agreement, especially because unopened-scroll ink labels are
iteratively expanded from model predictions rather than infrared ground truth.

### Smallest clean-room experiment

Independently implement only the three published standard descriptors from
their mathematical definitions. Do not consult or translate the deposited
source implementation.

Freeze one held-out surface slab, descriptor parameters, depth handling,
normalization, and comparison metrics before reading the target result. Compare
the deterministic evidence maps with the current frozen learned ink model under
four preregistered conditions:

1. known / papyrologically supported ink;
2. supervised non-ink;
3. harmless derivation or intensity perturbations;
4. synthetic planted strokes used only as a detectability control.

Record rank correlation and top-k spatial overlap, but make the primary review
artifact the four-way support partition:

- learned + texture;
- learned only;
- texture only;
- neither.

A letter-like learned prediction that lacks deterministic texture support and
is unstable under harmless derivation changes should carry less evidentiary
weight. Texture agreement alone must never be promoted to proof of ink.

### Promotion gate

Promote from WATCH to EXPERIMENT FURTHER / INCLUDE only if the clean-room
implementation adds reproducible discrimination on ScrollQ's independently
committed controls, including supervised negatives, without using target
predictions to choose parameters. Cross-scroll evidence is required before any
production weighting is considered.

A successful result may enter only as a post-hoc evidence channel or
corroboration gate at first. Training use requires a separate decision,
separate leakage analysis, and compatible licensing evidence.

### Kill criterion

Dismiss if the deterministic descriptors mainly reproduce generic papyrus
texture, if agreement is driven by the same annotations/predictions used to
evaluate the external paper, if performance collapses outside PHerc.172, or if
the added channel cannot separate learned-model-only false positives from
supported ink better than existing controls.

### Self-evaluation

- prize impact: **medium-high through validation credibility, not expected raw leaderboard gain**
- plausibility: **medium-high**
- evidence burden: **moderate-high; independent held-out controls and cross-scroll replication**
- implementation cost: **low-medium**
- reproducibility burden: **low if parameters and clean-room provenance are frozen**
- hallucination risk: **low as inference-only corroboration; higher if fed back into training**
- licensing risk: **blocking for reuse of deposited code; low for an independently authored implementation of published standard methods**
- VC3D compatibility: **high as a registered evidence texture / review channel**
- unnecessary surface area: **low if kept outside the predictor and dependency graph**


## Research ordering

These experiments should not all run at once. Prefer the cheapest strong
falsifier available for the current held-out asset:

1. use existing normal-offset / wrong-surface controls;
2. test stride/blend sensitivity if the detector runner is already available;
3. run context ablation if a suspicious semantic-context failure remains;
4. pursue acquisition conditioning when cross-scan generalization is the
   measured bottleneck;
5. pursue morphology corroboration only under its source/scale gate;
6. pursue cross-parameterization inference only when a genuinely independent
   second valid UV path exists.

The criterion is not novelty for its own sake. Each layer must eliminate a
failure mode the existing evidence cannot already eliminate.
