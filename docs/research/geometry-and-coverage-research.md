# Geometry, coverage, and sheet-identity research

These ideas target the physical reconstruction problem: staying on the correct
papyrus sheet, proving that the submitted surface is complete enough, and
making geometry errors easier to falsify before ink enters the loop.

## 1. Independent recto coverage witnesses

**Status:** EXPERIMENT FURTHER. Tracked in
[issue #151](https://github.com/Svyable/scrollq/issues/151).

The existing recto-coverage audit is intentionally honest about its boundary:
it can prove complete accounting of a declared reference inventory, but it
cannot discover papyrus omitted from that inventory.

### Hypothesis

Freeze a second geometry-generating evidence source that does not consume the
submitted mesh inventory, sample high-confidence candidate sheet locations from
it, and ask whether the submitted/unrolled surface explains those witnesses in
3-D.

Possible witness families include:

- an independently trained volume-level surface predictor;
- CT-local sheetness / Hessian-ridge evidence frozen on non-target data;
- an independently produced public surface proposal.

The witness is not ground truth. Its purpose is to falsify completeness.

### Minimal metric

For each frozen witness point:

1. find the nearest submitted surface point/triangle;
2. record 3-D distance;
3. optionally record normal agreement and winding/order consistency;
4. classify explained/unexplained using a predeclared rule.

Report unexplained witness fraction, connected clusters, distance quantiles, and
axial/winding localization rather than collapsing everything into one score.

### Tier-0 result

A deliberately simple synthetic wound-sheet test was used before adding any
production code:

- 28,800 independent witness samples;
- coherent missing patch equal to 3% of the synthetic sheet;
- iid witness-position noise with sigma 0.35 synthetic units;
- nearest-surface tolerance 1.5 units.

The prototype flagged about 2.896% of all witnesses after the omission,
corresponding to about 96.3% recall inside the deliberately removed region,
with about 0.0072% false flags outside it. Replacing the missing region by a
one-winding/wrong-winding surface produced essentially the same failure signal.

At tolerance 2.0 units, intact false flags fell to zero while missing-region
recall remained about 94.9%.

This establishes only that the proposed complement statistic behaves sanely on
controlled wound geometry. It does not establish that a real CT-derived witness
is reliable.

### Tier-1 real-papyrus deletion calibration

A frozen PHerc0139 experiment then reused the public w035 TIFXYZ on the exact
9.362 µm CT together with the independently published `surface-m7` prediction
already frozen for the wrong-wrap campaign. Six deletion centers came from an
earlier geometry-only plan rather than from witness strength.

The first protocol version is preserved as a formal **FAIL**: its largest
41×41 deletion consumed its entire 41×41 evaluation window, so the required
outside-stability statistic had no outside witnesses. The 21×21 and 31×31
arms nevertheless had recall 1.0 and outside stability 1.0. The protocol was
not rewritten in place.

A separately merged v2 changed only the evaluation window to 51×51. All source
identities, centers, deletion sizes, witness association, tolerances, synthetic
parallel-sheet control, and decision thresholds were unchanged.

V2 passed every preregistered Stage-A gate at the primary 8-voxel tolerance:

- omission recall: median 1.0 and minimum per-patch 1.0 for 21×21, 31×31,
  and 41×41 deletions;
- outside stability: minimum 1.0 for every deletion size;
- +20-voxel parallel substitution: median recall 1.0 and minimum outside
  stability 1.0 for the preregistered 31×31 and 41×41 arms;
- minimum supported witnesses per frozen 51×51 region: 1,168;
- median supported witnesses: 1,636.5;
- supported fraction of valid centered-normal material vertices ranged from
  about 0.449 to 0.822, median about 0.658;
- no sampled prediction or CT chunks were missing.

Artifacts:

- [v1 preregistration](../../artifacts/2026-10-03-coverage-witness-pherc0139-prereg/)
- [v1 measured FAIL](../../artifacts/2026-10-03-coverage-witness-pherc0139-run/)
- [v2 preregistration](../../artifacts/2026-10-03-coverage-witness-pherc0139-prereg-v2/)
- [v2 measured PASS](../../artifacts/2026-10-03-coverage-witness-pherc0139-run-v2/)

The important conclusion is narrower than the perfect deletion scores suggest.
Stage A deliberately associates independent predictions to known material
within ±2 voxels, so large deletion distance is expected once that association
exists. The stronger evidence is that the independent source supplies
substantial support across all six preselected real-papyrus regions.

### Newly exposed bottleneck: sheet identity

The same independent geometry source is known to contain competing sheet
candidates: the earlier frozen wrong-wrap experiment found separated,
CT-supported `surface-m7` geometry at 32/32 reference probes, typically
13–29 voxels from the w035 surface.

Therefore **surface existence is not physical sheet identity**. Promoting a raw
"unexplained surface prediction = omitted recto" rule would generate ambiguity
from adjacent windings.

The next useful experiment should be identity- or continuity-aware. One
promising direction is a **boundary/collar-connected coverage witness**:
seed the independent prediction only from intact submitted-surface material
around a candidate gap, then ask whether the same independent connected sheet
continues through the gap. Hidden deleted material may be used for scoring but
not for seeding or candidate selection. A successful version should also
measure whether competing neighboring-sheet controls are mistakenly joined to
the seeded component.

This is complementary to the fiber-texture fingerprint idea below: topology
may provide a cheaper sheet-identity signal; fiber texture becomes useful where
topological continuity is insufficient.

### Promotion gate

Promote only if real-papyrus controls show that:

- coherent artificial mesh deletions are detected at useful recall;
- intact-surface false flags remain localizable and low;
- adjacent/wrong-winding substitution is not accepted as valid coverage or is explicitly marked ambiguous rather than silently counted;
- the result replicates across regions and preferably witness families;
- thresholds are frozen without looking at Grand Prize target failures;
- unexplained clusters can be exported as reviewer-loadable locations.

### Self-evaluation

- prize impact: **high**
- plausibility: **medium-high**
- evidence burden: **high**
- implementation cost: **low-moderate once witness inputs exist**
- reproducibility burden: **low-moderate**
- invalid-evaluation risk: **medium if witness predictions are mistaken for truth**
- VC3D compatibility: **high**
- unnecessary surface area: **low only after real deletion controls discriminate**

## 2. Fiber-texture fingerprints for physical sheet identity

**Status:** EXPERIMENT FURTHER.

The current fiber audit deliberately checks geometry/provenance without
claiming that a trace is the correct physical fiber or even the correct sheet.
That is the gap this idea targets.

### Hypothesis

Papyrus fiber texture can act as a local physical fingerprint. Extract small CT
neighborhoods along the candidate surface, rectify them into a local tangent
frame, and compute a deterministic descriptor of the fiber pattern.

A surface that silently jumps to an adjacent winding may remain smooth,
sheet-like, and geometrically plausible while the local fiber fingerprint
changes abruptly.

Start with simple, auditable descriptors:

- dominant oriented-gradient / structure-tensor bands;
- multiscale 1-D and 2-D texture signatures;
- local frequency/orientation histograms;
- descriptor evolution along a material path.

Do not start with a large learned embedding. A self-supervised representation is
a later option only if simple descriptors fail for identifiable reasons.

### Falsification design

On public or verified surfaces:

1. sample tangent-aligned descriptors at fixed physical spacing;
2. measure continuity along known continuous paths;
3. inject synthetic short sheet switches onto a nearby winding;
4. inject easier nonadjacent-sheet substitutions;
5. test switch lengths such as 1, 2, 4, 8, and 16 mm;
6. report switch recall at a fixed false-alarm density and localization error.

An overlap-cycle variant can compare independently generated patches that claim
to cover the same material region. If their CT-derived fingerprints disagree
after coordinate registration, stitching should be reviewed. That variant is
specified, and its synthetic software controls executed, in
[the seam-authentication protocol](../papyrus-seam-fingerprint.md) (below).

### Executable cross-ply frame stage

A first measurement harness is now implemented as `scroliq-fiber-frame`. It
consumes a shallow CT slab that has already been rectified into
`(normal-depth, y, x)` surface coordinates. Within each spatial tile it builds
a 2-D structure tensor independently at each depth, clusters the depth-wise
axial orientations into two unordered modes, and compares those two-axis frames
between neighboring tiles.

The first synthetic positive control is intentionally narrow: a continuous
8-depth crossed-sinusoid slab yields no frame-switch findings, while rotating
both depth modes by 35 degrees on exactly one half of the surface produces only
the four expected tile-boundary findings at a 25-degree preregistered review
threshold. This demonstrates that the statistic is sensitive to a coherent
cross-ply frame splice rather than to mode ordering. It is **not** evidence that
real carbonized papyrus exposes recoverable cross-ply modes.

The report binds the exact NPZ slab, candidate-surface geometry digest, exact CT
volume root, and a frozen sampling-manifest digest. Optional level-0 XYZ
coordinates turn flagged boundaries into deterministic VC3D PointCollections
through `scroliq-vc3d-review --kind fiber-frame-discontinuity`.

The scientific status remains **EXPERIMENT FURTHER**. Real-CT adjacent-winding
controls, legitimate folds/tears/joins, low-texture regions, and cross-scroll
replication are required before the field may influence reconstruction.

### Promotion gate

Require separation between same-sheet continuity and adjacent-winding controls
on real CT, not just synthetic descriptor perturbations. Legitimate folds,
tears, cracks, low-SNR regions, and reconstruction discontinuities must be
represented in the negative/ambiguous set.

### Self-evaluation

- prize impact: **high**
- plausibility: **medium-high**
- evidence burden: **moderate-high**
- implementation cost: **moderate**
- reproducibility burden: **low-medium**
- hallucinated-ink risk: **essentially none; ink is not used**
- invalid-evaluation risk: **medium if smooth fibers are treated as ground truth**
- VC3D compatibility: **high via review points/regions**
- unnecessary surface area: **low if introduced as a diagnostic after real controls**

## 2a. Phase-preserving microtexture seam authentication

**Status:** EXPERIMENT FURTHER. Executable on synthetic sheets only; no real-CT
measurement exists. Full specification and decision rule:
[papyrus-seam-fingerprint.md](../papyrus-seam-fingerprint.md).

Sheetness asks whether a surface is papyrus-like. Fiber tests ask whether its
structure is coherent. Winding and braid tests ask whether its topology is
plausible. This idea asks a different question: **is this literally the same
physical piece of papyrus?** An adjacent winding can be smooth, sheet-like,
similarly oriented and similarly thick; it should not reproduce the same
microscopic arrangement of fiber crossings, voids and cracks.

### Hypothesis

When a seam joins patch A to patch B, the two independently sampled shallow CT
slabs in the claimed overlap, rectified into local tangent coordinates and
band-passed, contain a sharp, unique, geometrically compatible phase-correlation
peak if and only if they read the same material. The peak position is then a
residual-displacement estimate for seam refinement.

How this differs from the existing `tangent-fiber-spectrum-v1` descriptor above:
that descriptor compares orientation/spectral statistics of one patch against
another and returns a similarity. The seam authenticator keeps phase, so it
returns a correspondence: a displacement, a depth lag, a peak calibrated against
phase-randomized surrogates of the same slab, and an explicit
`UNKNOWN` when the texture cannot carry an answer. (An early prediction that the
magnitude descriptor would be blind to phase randomization was tested and
**falsified**: on synthetic shifted copies it does separate them. The difference
is the output, not a failure of the older descriptor.)

### What the first run found

- A bare correlation test accepts a through-going crack shared by two different
  windings (33 of 40 impostors) and accepts featureless papyrus whose two
  patches read the same voxel noise. Both are fixed by gates that are ablated in
  the committed artifacts so the hazard stays visible.
- Slabs from one CT volume share voxel noise, so a peak there certifies "same
  voxel neighborhood", not independent physical identity. Only a registered
  independent rescan arm can test physical microstructure.

### Promotion gate

INCLUDE only if held-out real overlaps separate reliably from
immediately-adjacent-winding controls and recover known displacement, with
low-information regions abstaining. DISMISS, without adding a learned matcher,
if performance comes mainly from gross fiber direction, depth, or shared
rendering artifacts. Details and the proposed numeric criteria are in the
protocol.

### Self-evaluation

- prize impact: **high** (a green/red/gray certificate on every patch join; possible sub-voxel seam refinement)
- plausibility: **medium-high**; 9 µm resolution may erase the useful scales
- evidence burden: **moderate**
- implementation cost: **low for the prototype (done), moderate for robust tangent-slab sampling**
- reproducibility burden: **low**
- hallucinated-ink risk: **zero; ink is never read**
- invalid-evaluation risk: **medium-high**: shared voxel noise and shared rendering pixels can fake identity (now measured, not just feared)
- VC3D compatibility: **excellent via per-seam status and correlation-surface review**
- unnecessary surface area: **low if it stays a seam validator/refiner**

## 3. Cross-parameterization geometry/ink separation

**Status:** the geometry side is already represented by the ink-blind
flattening benchmark; the detector-sensitivity extension remains EXPERIMENT
FURTHER in issue #137.

A core research principle emerged from the flattening work:

> Geometry should be selected with geometry-only evidence. Ink may test a frozen
> representation afterward, but may not select the representation.

This keeps two questions separate:

- Is UV-B geometrically safer/better than UV-A?
- Does a frozen detector behave consistently under two already-valid
  parameterizations?

The first belongs to
[flattening-benchmark.md](../flattening-benchmark.md). The second belongs to
the research experiment in the ink note.

## 4. Fiber-coordinate canonicalization

**Status:** DISMISS as a standalone model architecture for now.

Rotating model patches into a canonical local material/fiber frame is
plausible: it could remove orientation as a nuisance variable and make the
detector more invariant.

The problem is evidence. Fiber orientation is itself estimated, can be noisy,
and may add more error than it removes. There is no current demonstration that
canonicalization improves cross-scroll ink generalization.

Reconsider only as an ablation inside the fiber/morphology research:

- baseline model;
- model with orientation supplied as metadata;
- model with canonical rotation;
- identical held-out split.

No standalone subsystem should be added merely because the representation is
conceptually elegant.

## Research ordering

Geometry research should remain downstream of measured campaign failures:

1. keep the official Spiral/baseline reconstruction campaign primary;
2. use existing geometry validators to localize actual failure modes;
3. use independent coverage witnesses only to falsify missing-surface claims;
4. use fiber fingerprints only when wrong-sheet/sheet-switch risk is a measured
   problem;
5. never use target-scroll ink readability to select geometry.

The aim is reliable recoverable surface, not a larger geometry toolbox.
