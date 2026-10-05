# Overnight exploratory research — 2026-10-04 to 2026-10-05

**Status:** research ledger only. No production dependency, scoring behavior,
training path, checkpoint, frozen artifact, or primary Grand Prize execution
order is changed by this note.

This file records the exploratory ideas developed during the 2026-10-04
evening / 2026-10-05 early-morning research run. It is intentionally broader
than the main research index so that useful negative decisions are preserved
without turning the production roadmap into a catalog of speculative systems.

The existing research portfolio remains authoritative. Where an overnight idea
is a refinement of an experiment already in the repository, this note records
the mapping instead of creating a duplicate subsystem.

The common rules remain:

- geometry selection stays ink-blind;
- target-scroll apparent readability never chooses geometry, calibration, or
  nuisance parameters;
- model evaluation is held out by fragment/scroll where appropriate;
- controls are frozen before target results are inspected;
- uncertainty becomes `UNKNOWN` / abstention, not confidence;
- agreement between correlated models or transforms is never called proof of
  ink;
- new evidence layers remain asynchronous from the primary dependency-order
  campaign until their promotion gates pass.

## Batch manifest

| Idea | Decision | Canonical relationship / next evidence |
|---|---|---|
| Registered-rescan ink invariance | **EXPERIMENT FURTHER** | Registered independent acquisitions of the same papyrus should agree more for physical ink than scan-specific artifacts; require visible-ink controls and deliberately broken registration |
| Sheet-identity cycle consistency | **EXPERIMENT FURTHER** | Local sheet fingerprints / neighbor relationships should close around cycles; require injected and real sheet-jump failures |
| Cross-laminar fiber stratigraphy / recto-side oracle | **EXPERIMENT FURTHER** | Estimate fiber orientation through sheet thickness to infer recto direction; require known-side leave-fragment-out calibration and abstention on fused material |
| Fiber-coordinate flattening | **EXPERIMENT FURTHER** | Use physical fiber fields as intrinsic coordinates; require recovery of blinded deliberately distorted trusted geometry and scrambled-fiber null failure |
| Rendering commutativity certificate | **INCLUDE as proof infrastructure** | Independent reference TIFXYZ→CT renderer plus whole/tiled/crop commutativity; implement only as a validator |
| Human annotation budget optimizer | **EXPERIMENT FURTHER** | Rank bounded VC3D interventions by expected recovered physical area/topology per second; require retrospective oracle simulation plus real interaction-time calibration |
| Human-input ledger | **INCLUDE as proof infrastructure** | Append-only record of bounded interventions, duration, hashes, and affected geometry; does not redefine what the Challenge counts as human input |
| Receptive-field ablation ladder | **EXPERIMENT FURTHER; absorbed into causal context ablation** | Compare local, larger-context, and center-masked models/interventions; no separate subsystem until existing causal-context protocol earns it |
| Resolution-degradation survival / synthetic-resolution ladder | **INCLUDE as validation experiment** | Deterministic degradation ladder is cheap and informative even when negative; use held-out physical controls |
| Automatic resolution / PSF adaptation | **EXPERIMENT FURTHER** | Promote only if leave-one-scroll-out gains beat ordinary physical-coordinate resampling without tuning on target text |
| Papyrus mass-balance coverage certificate | **EXPERIMENT FURTHER; extension of independent coverage witnesses** | Independent papyrus-material support versus submitted surface support; require synthetic and real omission / wrong-wrap tests and explicit unknown regions |
| Matched-null ink evidence | **EXPERIMENT FURTHER** | Compare candidates with physically matched verified blank papyrus rather than a global blank pool; require scanner/fragment holdout and abstention under poor support |
| Paired-lamina ribbon consistency | **EXPERIMENT FURTHER** | Model a sheet as a finite-thickness ribbon with two interfaces; require wrong-wrap discrimination beyond single-surface sheetness |
| Radial-order braid certificate | **EXPERIMENT FURTHER** | Detect unexplained relative-order exchanges among neighboring laminae across slices/rays; require robustness to folds, tangencies, tears, and umbilicus uncertainty |
| Evidence-family counterfactual reconstruction | **EXPERIMENT FURTHER** | Rerun geometry while withholding one evidence family at a time; require poisoned-constraint localization on trusted reconstruction |
| Constraint leverage accounting | **INCLUDE as provenance / prioritization evidence** | Record the downstream area/topology affected by removing or perturbing each constraint |
| Calibrated ink abstention | **EXPERIMENT FURTHER** | Optimize selective coverage subject to held-out precision/risk bounds; leave-one-scroll-out calibration is mandatory |
| Checkpoint-disagreement cartography | **EXPERIMENT FURTHER** | Map where materially different released checkpoints disagree; use for review/abstention, not majority-vote proof |
| Surface loop-closure / holonomy certificate | **EXPERIMENT FURTHER** | Compose overlap correspondences around deterministic graph cycles; require injected drift/sheet-jump detection without auto-repair |
| Dual-flattening concordance | **EXPERIMENT FURTHER; maps to cross-parameterization inference invariance** | Run independent inference through two already-valid parameterizations and compare in material coordinates |
| Geometry-conditioned ink uncertainty propagation | **EXPERIMENT FURTHER** | Sample only physically calibrated admissible surface perturbations and report ink sensitivity; do not average them into a prettier image |
| Scanner-frame equivariance audit | **INCLUDE as validation experiment** | Exact lattice symmetries first; arbitrary interpolated rotations are secondary and cannot be hard acceptance rules |
| Normal-depth physical signature | **INCLUDE as validation experiment; refinement of surface-normal response** | Preserve the signed depth-response distribution as evidence; only a held-out physical signature can justify any veto |
| Preservation viability atlas | **EXPERIMENT FURTHER** | Distinguish preserved material, physically compromised material, and unknown using CT/geometry only; must separate actual material loss from segmentation failure |
| Explanation packet generator | **INCLUDE as proof infrastructure** | Reproducible packet for blank/damaged regions containing CT coordinates, geometry evidence, hashes, and reason codes; reviewer decides validity |
| Adjacent-sheet shadow test | **EXPERIMENT FURTHER** | Treat neighboring windings as naturally matched controls for scanner-fixed/model leakage; require trustworthy sheet identity |
| Metamorphic submission harness | **INCLUDE as proof infrastructure** | Test known invariants under tiling, cache, chunking, crop-origin, batch-size, and equivalent-layout changes |
| Fault-injection CI for provenance guards | **INCLUDE** | Every important guard should have at least one intentionally corrupted artifact it demonstrably rejects |
| Counterfactual papyrus transplantation | **EXPERIMENT FURTHER; absorbed into causal context ablation** | Preserve local CT while transplanting matched distant context; require sham-transplant controls |
| Material-coordinate distortion overlay | **INCLUDE as diagnostic experiment** | Quantify UV alignment/shear/reversal against independently estimated physical fiber directions |
| Fiber-frame canonicalized ink model | **DISMISS as standalone architecture for now** | Reconsider only as a controlled ablation after fiber-direction evidence is reliable and ordinary augmentation is a fair baseline |

## 1. Registered-rescan ink invariance

**Decision: EXPERIMENT FURTHER.**

### Hypothesis

When two independently acquired or reconstructed scans cover the same physical
papyrus, a physical ink signal should reproduce after registration more reliably
than some acquisition-specific noise, ring/reconstruction artifacts, or
scanner-frame texture.

For scan A and scan B:

1. register them in physical coordinates without looking at ink output;
2. sample the same frozen surface neighborhood;
3. run the same hash-bound detector independently;
4. transport predictions to common material coordinates;
5. compare correctly registered agreement with deliberately broken
   registration and unrelated-sheet controls.

The first stage is validation only. Cross-scan consistency training is a later
option only if the evaluator shows complementary information exists.

### Promotion gate

Require held-out visible-ink evidence that correctly registered cross-scan
agreement improves precision/calibration at matched recall or suppresses known
false components, while misregistration and wrong-sheet nulls collapse that
advantage.

### Self-evaluation

- prize impact: **high**
- technical plausibility: **high for validation; medium for training**
- evidence burden: **moderate-high**
- implementation cost: **low-medium for evaluator**
- reproducibility burden: **moderate**
- hallucination risk: **favorable as a control; agreement is not proof**
- VC3D compatibility: **high**
- unnecessary surface area: **low if evaluator-only**

## 2. Sheet-identity cycle consistency

**Decision: EXPERIMENT FURTHER.**

### Hypothesis

A hidden jump from one winding to an adjacent winding can remain locally smooth.
Build a local graph whose nodes carry non-text physical sheet fingerprints:
normal profiles, thickness/support, neighboring-sheet distances, curvature and
fiber-frame evidence. Correspondences around A→B→C→A should return to the same
physical sheet identity.

### Minimal experiment

Inject controlled sheet jumps into trusted surfaces and compare ordinary
smoothness with cycle residuals. Negative controls must include folds, tears,
genuine high curvature, compressed valid layers and low-information regions.

### Promotion gate

Require high jump-detection recall at low false alarm on both injected and real
verified failures. If only synthetic failures separate, keep the method out.

### Self-evaluation

- prize impact: **very high if sheet jumps remain a dominant failure**
- plausibility: **medium-high**
- evidence burden: **moderate**
- cost: **moderate**
- reproducibility: **low-medium**
- hallucinated-ink risk: **zero**
- VC3D compatibility: **high**
- surface area: **low as a validator**

## 3. Cross-laminar fiber stratigraphy as a recto-side oracle

**Decision: EXPERIMENT FURTHER.**

### Hypothesis

Rather than treating fibers only as surface lines, estimate dominant in-plane
fiber orientation as a function of signed depth through the sheet. Where the
two papyrus plies remain separable, their orthogonal depth ordering may provide
an ink-blind cue for which normal direction points toward the recto/writing
side.

### Minimal experiment

On known-side fragments or trusted surfaces, sample signed-normal slabs and
derive a calibrated recto probability with an explicit abstain state. Controls:
flipped normals, rotated UV, deliberately offset surfaces, folds, tears, fused
sheets, adjacent-sheet intrusion and low-fiber-SNR material.

### Promotion gate

High calibrated side-direction accuracy at useful non-abstained coverage on
leave-fragment-out evaluation. Fused/damaged cases should move toward unknown,
not confident error.

### Self-evaluation

- prize impact: **high**
- plausibility: **medium-high**
- evidence burden: **moderate**
- cost: **moderate**
- reproducibility: **low-medium**
- hallucinated-ink risk: **zero**
- VC3D compatibility: **high**
- surface area: **low as orientation/evidence provider**

## 4. Fiber-coordinate flattening

**Decision: EXPERIMENT FURTHER.**

### Hypothesis

Use the papyrus manufacturing structure as an intrinsic coordinate system.
Estimate approximately orthogonal tangent vector fields from physical fibers
and solve for UV coordinates whose gradients align with those fields while
regularizing metric distortion.

This asks the physical sheet how it wants to lie flat without using ink or
language.

### Minimal experiment

Take trusted completed geometry, deliberately distort UV, reconstruct a
fiber-aligned parameterization from CT-derived fiber fields, and compare metric
distortion, fiber curvature, seam consistency and recovery of the trusted map.
A scrambled-fiber control must destroy the advantage.

### Promotion gate

Beat the existing flattener on independent geometric/fiber metrics without
increasing unacceptable metric distortion. If scrambled fields perform
similarly, dismiss.

### Self-evaluation

- prize impact: **high for legibility/seam coherence if signal survives**
- plausibility: **medium-high**
- evidence burden: **moderate**
- cost: **moderate**
- reproducibility: **low**
- hallucinated-ink risk: **zero**
- VC3D compatibility: **high**
- surface area: **low-medium as optional refinement backend**

## 5. Rendering commutativity certificate

**Decision: INCLUDE as proof infrastructure. No production renderer change is
implied by this ledger entry.**

### Contract

Build a deliberately small independent reference renderer for the declared
TIFXYZ→CT sampling operation. It should not share the production VC3D rendering
implementation.

Test operations that should commute:

- whole render versus tiled render;
- full TIFXYZ then crop versus cropped TIFXYZ with coordinate correction;
- native render versus preregistered downsample of a higher-sampled equivalent;
- production renderer versus the minimal reference sampler.

Start with an asymmetric synthetic 3-D volume encoding position so axis swaps,
scale errors, interpolation mismatches, crop-origin mistakes and tile-boundary
errors are analytically visible.

### Proof artifact

For each submitted column, bind:

- CT identity/hash;
- TIFXYZ hashes;
- renderer/container identity;
- interpolation and depth parameters;
- reference and production render digests;
- whole/tile and crop commutativity errors;
- scale-bar derivation.

### Why INCLUDE

The contract is deterministic, cheap, independent of ink, directly
reproducible, and capable of detecting submission-invalidating coordinate
failures without a scientific-learning hypothesis.

## 6. Annotation-budget optimization and human-input ledger

### 6a. Annotation-budget optimizer

**Decision: EXPERIMENT FURTHER.**

Treat the permitted human-input budget as a scarce topology resource rather
than distributing it uniformly. For each unresolved region estimate:

- probability the current geometry is wrong;
- physical recto area / topology downstream of the decision;
- expected reduction in error after a bounded human answer;
- observed time needed for that interaction.

Rank interventions by expected recovered physical area/topological risk per
second. Ink confidence and apparent text density are prohibited inputs.

Prototype retrospectively with an oracle over trusted geometry and fixed
budgets, comparing random, local-uncertainty, largest-area and value-per-second
policies. A small real VC3D timing study is mandatory because simulated human
times are not evidence.

### 6b. Human-input ledger

**Decision: INCLUDE as proof infrastructure.**

Keep an append-only ledger of each bounded human action:

- timestamp/order;
- region and machine alternatives shown;
- exact response;
- wall-clock interaction duration;
- affected geometry;
- before/after hashes;
- cumulative input time.

The ledger documents activity; it does not decide what the Challenge counts
toward its human-input allowance.

## 7. Receptive-field ladder and causal context intervention

**Decision: EXPERIMENT FURTHER, but do not create a second subsystem. Extend the
existing causal-context-ablation research.**

The overnight refinement adds two useful arms:

1. a ladder of otherwise comparable effective receptive fields, from
   local-physical evidence to character-scale context;
2. a center-masked large-context arm that preserves surrounding CT while
   removing the candidate stroke's local evidence.

The desirable outcome is not merely higher accuracy with smaller context.
It is evidence that verified ink depends materially on its local CT while
context-only models cannot recreate convincing strokes after center removal.

If large-context ensemble agreement survives local-evidence destruction, treat
that agreement as weak evidence rather than multiplying confidence.

## 8. Resolution-degradation survival and scale-consistency auditing

### 8a. Synthetic-resolution ladder

**Decision: INCLUDE as a validation experiment.**

From held-out known-ink volumes, construct deterministic physically specified
degradation arms: bounded low-pass/MTF attenuation, downsample/reconstruct,
slice-direction degradation where justified, sub-voxel phase shifts and
controlled noise. Map outputs back to common physical coordinates.

Report verified-ink survival, hard-negative survival and component topology
versus effective resolution. A negative result still tells us which checkpoints
are resolution-fragile.

The ladder must use only allowed source data; it must never use a
higher-resolution scan of the submitted target to create target evidence.

### 8b. Automatic resolution/PSF adaptation

**Decision: EXPERIMENT FURTHER.**

Adaptation parameters must come from observable acquisition metadata/physics,
never from apparent text. Promote only with leave-one-scroll-out improvement
over ordinary resampling across more than one degradation family.

### 8c. Multi-scale prediction fusion

**Decision: DISMISS.**

Correlated predictions across synthetic scales are not independent evidence and
averaging can reinforce false strokes.

## 9. Papyrus mass-balance coverage certification

**Decision: EXPERIMENT FURTHER; treat as an extension of the existing
independent recto-coverage witness program.**

### Hypothesis

Construct an independent papyrus-material / sheet-support field in CT space and
compare it with the physical support claimed by all submitted TIFXYZ surfaces.
Look for:

- unexplained papyrus support;
- multiply claimed support;
- disconnected components requiring explicit attribution;
- regions where the independent material estimator itself is unknown.

A scalar sum of submitted mesh area is not enough because duplicate or
wrong-wrap substitutions can preserve total area.

### Minimal experiment

Use synthetic rolled sheets with known area, variable thickness, touching
laminae, detached flakes, omissions and equal-area wrong-wrap substitutions.
Then retrospectively delete known geometry from a trusted real reconstruction.

### Promotion gate

Detect omissions and area-preserving substitutions while fused regions
reliably become unknown. Do not call the resulting bound “100% coverage” unless
the independent denominator is itself justified.

## 10. Matched-null ink evidence

**Decision: EXPERIMENT FURTHER.**

### Hypothesis

A detector score is more interpretable when compared with verified blank
papyrus under similar nuisance conditions than with a global blank population.
Candidate matching may use non-semantic physical descriptors such as scan,
reconstruction regime, curvature, depth, fiber strength/orientation and local
non-text texture statistics.

The simple statistic is a conservative empirical rank within the matched blank
bank. Sparse or poor support becomes unknown.

### Promotion gate

Leave entire fragments/scanners out. Require better calibration or precision at
matched recall than raw scores and approximately honored blank-only error
levels. A wrong-scanner/wrong-regime matching ablation should degrade
calibration.

### Important dismissal

**Global conformal calibration over all blank pixels: DISMISS.** Heterogeneous
easy blank papyrus can hide the hard false-positive regime.

## 11. Paired-lamina ribbon reconstruction

**Decision: EXPERIMENT FURTHER.**

Represent a sheet as a finite-thickness ribbon with two jointly inferred
interfaces and a center surface. A locally smooth wrong-wrap substitution may
still break paired-boundary continuity, thickness support or the expected
interior/exterior profile.

Start with a deterministic 2-D dynamic program over
`(upper_boundary, lower_boundary)`, with an explicit unknown state. Inject
centerline sheet jumps, missing interfaces, compressed sheets and equal-length
adjacent-sheet splices.

Promote only if paired-interface consistency detects wrong-wrap substitutions
that ordinary center-surface sheetness accepts.

**Global nearly constant thickness: DISMISS.** Carbonization/compression makes
that prior too brittle; the useful object is uncertain paired-interface
consistency.

## 12. Radial-order braid certificate

**Decision: EXPERIMENT FURTHER.**

Across many transverse slices and rays from an estimated umbilicus, record the
ordered sequence of submitted-surface intersections. As angle/axial coordinate
changes, those sequences form trajectories. Flag relative-order exchanges only
when local CT cannot support a fold/contact/termination explanation.

States should include:

- supported contact/fold;
- supported termination/tear;
- unexplained order swap;
- unknown.

The method must be tested over an uncertainty envelope for the umbilicus. If
flags explode or move under plausible center perturbations, dismiss.

**Globally monotonic winding radius: DISMISS.** Crushed/folded scrolls violate
that idealized geometry.

## 13. Evidence-family counterfactual reconstruction and constraint leverage

### 13a. Leave-one-evidence-family-out reconstruction

**Decision: EXPERIMENT FURTHER.**

Reconstruct the same region while withholding one independently meaningful
evidence family at a time: surface likelihood, winding constraints, fibers,
umbilicus/spiral prior, patch overlap constraints, manual corrections, etc.

Measure a geometry influence field, topology changes, winding substitutions,
newly unsupported area and flattening distortion.

The desired evidence is not “removing data makes the answer worse.” It is
localization of regions whose geometry depends critically on one fragile source.

### Promotion gate

Inject plausible poisoned constraints into trusted geometry and require
leave-one-family-out influence to localize the consequential wrong region
before the trusted answer is consulted.

### 13b. Constraint leverage accounting

**Decision: INCLUDE as provenance / prioritization evidence.**

For every constraint record the downstream surface area/topology that can change
when it is removed or perturbed. This can inform review priority without
changing the reconstruction.

**Averaging ablated reconstructions: DISMISS.** The ablations intentionally omit
valid evidence and are not equally plausible candidate surfaces.

## 14. Calibrated abstention for ink

**Decision: EXPERIMENT FURTHER.**

Wrap a frozen detector in a third state: `INK / NON_INK / ABSTAIN`. Select
thresholds or a small preregistered stratified rule on calibration data and
evaluate selective coverage versus a lower-bound precision/risk target on an
entire held-out scroll.

The wrapper must remain downstream of the frozen detector. Difficult negatives
such as cracks, folds, fibers and fused sheets should be represented explicitly.

Promote only if leave-one-scroll-out selective prediction materially improves
precision at useful retained-ink coverage. If nominal guarantees collapse under
domain shift, report the failure rather than calling the scores calibrated.

**Filling abstained pixels from neighboring confident strokes: DISMISS.** That
manufactures morphology.

## 15. Checkpoint-disagreement cartography

**Decision: EXPERIMENT FURTHER.**

Run a preregistered panel of materially different checkpoints over frozen
held-out surfaces. Map per-pixel/component disagreement, checkpoint-family
correlation and persistence across thresholds.

The goal is not an ensemble image. It is an epistemic map showing where the
released models disagree and whether that disagreement localizes hard negatives
or domain-specific failure regimes.

Promotion requires incremental false-positive rejection or useful abstention
beyond ordinary confidence, with leave-one-scroll-out evidence.

**Majority-vote ensembling: DISMISS.** Correlated checkpoints do not become
independent measurements by voting.

**Choosing the most letter-like checkpoint: DISMISS.** It directly selects for
plausible text.

## 16. Surface loop-closure / holonomy certificate

**Decision: EXPERIMENT FURTHER.**

Build an overlap graph over independent/overlapping TIFXYZ patches and estimate
physical correspondences from CT/fiber evidence. Compose transforms around a
deterministic cycle basis. Non-zero cycle residual can expose accumulated drift,
sheet jumps, stale transforms, UV shear or patch-identity errors even when each
individual seam looks plausible.

Inject short/long adjacent-wrap substitutions, drift, normal flips, stale
origins and UV shear into trusted geometry. Require detection and culprit-edge
localization while legitimate deformation stays below the review threshold or
becomes unknown.

**Automatically optimizing the graph until loops close: DISMISS.** Internal
consistency can be achieved by a globally wrong reconstruction.

## 17. Dual-flattening concordance

**Decision: EXPERIMENT FURTHER; canonical home is the existing
cross-parameterization inference-invariance experiment.**

For one fixed 3-D surface, generate two independently valid parameterizations,
run the same frozen detector independently through each, map both outputs to
common material coordinates and measure component/pixel concordance versus UV
distortion and seam distance.

Agreement is only evidence that a feature is not obviously representation-
specific; it is not proof of ink.

**Selecting the flattening that produces more legible-looking text: DISMISS.**

**Merging pixels from both flattenings before validation: DISMISS.**

## 18. Geometry-conditioned ink uncertainty propagation

**Decision: EXPERIMENT FURTHER.**

Estimate a physically calibrated local geometry uncertainty envelope from
surface evidence, then sample only admissible nearby surfaces and rerun frozen
ink inference. Preserve the ensemble as a geometry→ink sensitivity field.

Validation has two obligations:

1. the geometry envelope must cover observed real segmentation error at the
   intended rate;
2. ink instability must predict verified ink loss / hard-negative appearance
   beyond raw geometry or ink confidence.

**Monte-Carlo averaging across perturbed surfaces: DISMISS.** Averaging can hide
instability and create a smoother, more persuasive false result.

**Expanding the envelope until letters stabilize: DISMISS.** That tunes geometry
to textual appearance.

## 19. Scanner-frame equivariance audit

**Decision: INCLUDE as a validation experiment.**

Start only with exact information-preserving lattice symmetries: flips,
90-degree rotations and axis permutations when physical spacing permits them.
Transform CT and TIFXYZ together, run one immutable checkpoint, inverse-map the
prediction and measure equivariance defect.

Positive controls should include a deliberately axis-sensitive toy path.
Verified ink and hard negatives determine whether defect has value as an
abstention/review feature.

Arbitrary rotations requiring interpolation are secondary controls, not hard
acceptance rules.

**Test-time averaging over rotations: DISMISS.** Transformed predictions are
correlated and averaging can reinforce false strokes.

## 20. Normal-depth physical signature

**Decision: INCLUDE as a validation experiment; treat as a refinement of the
existing surface-normal response campaign rather than a second production
system.**

Preserve the signed normal-depth response distribution at held-out ink and
matched non-ink locations. Test simple preregistered physical statistics such
as peak offset, response width, near/far decay and signed asymmetry.

The claim must be empirical. Do not assume carbon ink has a one-sided or
surface-centered CT signature in advance.

Promote any depth-consistency veto only after leave-fragment-out evidence
demonstrates a transferable physical signature.

**Training a model to maximize the hypothesized depth signature before that
signature is independently established: DISMISS.**

## 21. Preservation viability atlas and explanation packets

### 21a. Preservation viability atlas

**Decision: EXPERIMENT FURTHER.**

Using only CT/geometry evidence, classify surface regions conservatively as:

- `PRESERVED`;
- `PHYSICALLY_COMPROMISED`;
- `UNKNOWN`.

Potential inputs include sheet support/continuity, local missing material,
tears/boundaries, severe fusion/crushing and whether a stable physical surface
exists through neighboring slices.

The key control is to distinguish actual missing papyrus from missing mesh or
failed segmentation. Pipeline failure must never become an explanation for
blank text.

### 21b. Explanation packet generator

**Decision: INCLUDE as proof infrastructure.**

For each blank/damaged region produce a reproducible packet with:

- TIFXYZ coordinates;
- CT bounding box;
- surface-support / preservation evidence;
- reviewer-loadable cross-sectional views or VC3D locations;
- source hashes;
- reason code and unknown state where applicable.

The packet presents evidence. It does not automatically exclude the region from
legibility accounting.

**Automatically removing `PHYSICALLY_COMPROMISED` pixels from internal prize
metrics: DISMISS.**

**Inferring physical damage from a blank ink model output: DISMISS.**

## 22. Adjacent-sheet shadow test

**Decision: EXPERIMENT FURTHER.**

For a candidate ink component, identify trustworthy neighboring physical
sheet(s) across the local gap and render corresponding controls with the same
detector. A scanner-fixed / reconstruction artifact or wrong-sheet leakage may
repeat across neighboring sheets while true surface-bound evidence should be
more sheet-specific.

This is different from a fixed normal offset: the control intentionally lands
on another physical lamina.

Promotion requires known sheet identity and leave-one-scroll-out evidence that
cross-sheet persistence predicts false positives beyond ordinary ink and
geometry confidence.

**Automatically rejecting every candidate with a neighboring-sheet response:
DISMISS.**

**Treating target-vs-neighbor disagreement as positive proof of ink: DISMISS.**

## 23. Metamorphic submission testing and fault-injection CI

### 23a. Metamorphic submission harness

**Decision: INCLUDE as proof infrastructure.**

Apply transformations whose expected relationship between inputs and outputs is
known without requiring ink ground truth:

- clean-cache versus warm-cache replay;
- monolithic versus tiled inference/rendering;
- tile-order permutation;
- batch-size changes;
- lossless Zarr rechunking / equivalent storage layouts;
- physically equivalent crop-origin translation with matching coordinate
  correction.

Each arm declares its invariant and numerical tolerance before execution.
Intentionally inject one-pixel scale errors, omitted crop origins, flipped
normals, stale predictions and mismatched TIFXYZ/volume identities as positive
controls.

Emit a conformance receipt binding software/container digest, artifact hashes,
mutation, expected invariant, measured deviation, tolerance and result.

### 23b. Fault-injection CI

**Decision: INCLUDE.**

Every important provenance or geometry guard should retain at least one
intentionally corrupted artifact that proves the guard can fail for the defect
it claims to detect. A green audit with no positive control is not evidence.

**Universal bit-for-bit equality: DISMISS.** Scientifically equivalent GPU or
chunked execution may differ numerically.

**Snapshot-testing attractive final letter images as the primary regression
contract: DISMISS.** It can preserve consistently wrong behavior.

## 24. Counterfactual papyrus transplantation

**Decision: EXPERIMENT FURTHER, but absorb it into the existing causal-context
ablation program.**

Preserve a protected local 3-D neighborhood around a candidate while replacing
progressively more distant context with matched non-ink papyrus from a donor
chosen without model output, OCR or letter shape. Run the inverse experiment on
hard false positives using context from verified-ink regions.

Same-patch sham transplants and multiple donor-matching schemes are mandatory.
The useful outcome is a causal-support-radius curve, not a generated image.

**Using transplantation as training augmentation before it proves anything:
DISMISS.**

**Automatically suppressing every context-sensitive prediction: DISMISS.**

## 25. Material-coordinate distortion overlay and fiber-frame canonicalization

### 25a. Material-coordinate distortion overlay

**Decision: INCLUDE as a diagnostic experiment.**

Given independently estimated physical fiber directions, quantify how the UV
parameterization locally rotates, shears or reverses relative to the papyrus
material frame. This turns qualitative fiber-following into a measurable
review layer and can expose UV distortion without reading ink.

### 25b. Fiber-frame canonicalized ink architecture

**Decision: DISMISS as a standalone architecture for now, consistent with the
existing research ledger.**

A controlled ablation remains permissible later:

- baseline;
- orientation metadata only;
- material-frame canonicalization;
- identical held-out data, architecture budget and compute.

Promote only if physical orientation is independently reliable and
leave-one-scroll-out performance beats ordinary augmentation.

**Rotating the final 2-D ink image until text looks coherent: DISMISS.**

## 26. Ideas explicitly absorbed by existing research

The following overnight proposals are useful refinements but should not acquire
separate implementation surfaces:

- **counterfactual surface-perturbation ink stability** → existing
  surface-normal response / surface-lock profiles;
- **surface-offset ink stability** → existing normal-response campaign;
- **receptive-field ablation ladder** → causal context ablation;
- **causal locality audit** → causal context ablation;
- **counterfactual papyrus transplantation** → causal context ablation;
- **dual-flattening concordance** → cross-parameterization inference
  invariance;
- **normal-depth signature** → surface-normal response, with richer stored
  profile statistics;
- **independent recto coverage residual certificate** → independent recto
  coverage witnesses;
- **papyrus mass-balance coverage** → coverage-witness extension, not a
  competing completeness score;
- **recto/verso fiber-parity certificate** → cross-laminar / cross-ply fiber
  evidence;
- **fiber-frame canonicalization architecture** → already dismissed as a
  standalone system; retain only a future controlled ablation;
- **papyrus fingerprint seam authentication** → already implemented as the
  current phase-preserving seam-authentication research path;
- **deterministic volumetric-texture corroboration** → already recorded as
  WATCH in the ink research ledger.

## 27. Additional negative decisions from the overnight run

Keep these explicit so they do not return under new names without new evidence:

- **language-model / Greek-likelihood selection of geometry: DISMISS** —
  downstream semantic plausibility must not choose the physical surface;
- **ink-selected recto direction: DISMISS** — circular validation;
- **renderer-agreement parameter tuning: DISMISS** — renderer agreement is a
  falsification test, not an optimizer;
- **global constant papyrus thickness prior: DISMISS** — too brittle under
  compression/carbonization;
- **global monotonic winding radius: DISMISS** — folds/crushing invalidate the
  ideal spiral assumption;
- **global blank-pixel conformal calibration: DISMISS** — heterogeneity hides
  difficult negatives;
- **large-window ensemble consensus as proof: DISMISS** — correlated models can
  share morphology priors;
- **higher-resolution target-scan-derived cross-resolution evidence: DISMISS**
  when prohibited by the target's prize eligibility constraints;
- **total submitted mesh area as completeness proof: DISMISS** — duplication and
  wrong-wrap substitution can preserve scalar area;
- **automatic loop-closing geometry optimizer: DISMISS until diagnostic loop
  closure itself is validated**;
- **averaging counterfactual / perturbed surfaces: DISMISS**;
- **multi-scale or transformed-prediction averaging as independent evidence:
  DISMISS**;
- **excluding damaged regions from scoring automatically: DISMISS** — reviewer
  adjudication must remain external;
- **using neighboring-sheet disagreement as affirmative ink proof: DISMISS**;
- **bitwise equality as the universal reproducibility criterion: DISMISS**;
- **final-image snapshot tests as the main scientific regression gate:
  DISMISS**.

## Suggested asynchronous experiment order

This is deliberately not the primary dependency-order pipeline. If spare
compute/reviewer attention exists, prefer experiments with the cheapest strong
falsifier and highest information value:

1. rendering commutativity + metamorphic/fault-injection proof infrastructure;
2. scanner-frame exact-symmetry audit;
3. synthetic-resolution ladder;
4. constraint leverage accounting and human-input ledger;
5. matched-null ink calibration;
6. registered-rescan ink invariance where registered pairs exist;
7. adjacent-sheet shadow controls where sheet identity is already trustworthy;
8. sheet-cycle / loop-closure / braid diagnostics only where wrong-wrap risk is
   measured;
9. ribbon, fiber-stratigraphy and fiber-coordinate flattening only after the
   simpler physical diagnostics demonstrate missing information;
10. annotation-budget optimization only after real VC3D intervention timings
    exist.

The default outcome of a failed experiment is **DISMISS**, not “add another
model.” Nothing in this batch should block whole-scroll reconstruction,
submission packaging, or the main Grand Prize dependency-order campaign.
