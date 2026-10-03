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

### Promotion gate

Promote only if real-papyrus controls show that:

- coherent artificial mesh deletions are detected at useful recall;
- intact-surface false flags remain localizable and low;
- adjacent/wrong-winding substitution is not accepted as valid coverage;
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
after coordinate registration, stitching should be reviewed.

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
