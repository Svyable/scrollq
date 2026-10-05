# Dismissed and deferred ideas

This file is intentional. Research debt includes remembering why attractive
ideas were rejected so they do not quietly return without new evidence.

## Global histogram matching

**Status:** DISMISS as a production normalization strategy.

Matching marginal intensity distributions across scans is easy, but it has no
strong material-physics interpretation and can erase subtle signal that may
matter for ink. It also creates a high risk of believing that similar
histograms imply similar acquisition domains.

Keep only as a negative control inside acquisition-normalization experiments.

Reconsider only if a preregistered held-out experiment shows an advantage over
raw-channel-preserving, physically interpretable alternatives.

## Transport-only coordinate invariance

**Status:** DISMISS.

The first version of the coordinate-invariance idea proposed transporting one
already-frozen scalar ink field through UV-A and UV-B and comparing the
pullbacks.

That is mostly tautological. A material-attached false positive is transported
just as faithfully as real ink. Any difference mostly measures rasterization or
resampling.

The surviving experiment is **independent detector inference** in each valid
parameterization, followed by comparison in material coordinates. See
[issue #137](https://github.com/Svyable/scrollq/issues/137).

## Selecting flattening by ink persistence or readability

**Status:** DISMISS.

Using ink agreement, OCR, or apparent readability to choose a UV
parameterization contaminates geometry selection. It can reward a distorted map
because it makes a letterform look stronger.

Flattening selection must remain ink-blind. Ink may test an already-frozen
geometry afterward.

## Learned (Siamese) patch matcher for sheet identity

**Status:** DISMISS for now.

Training a network to say whether two patches show the same papyrus is the
obvious shortcut for [seam authentication](../papyrus-seam-fingerprint.md). It
would be free to exploit scanner, depth, geometry or preprocessing shortcuts,
and a score from it could not be traced to a physical cause. That makes the
evidence harder to interpret than the failure it is meant to catch.

The deterministic correlation experiment must first establish that physical
identity information exists at all. Only then would learned descriptors earn a
place, and then only as an ablation against the deterministic baseline on the
same held-out adjacent-winding set.

## Immediate tile-origin / phase-offset backend

**Status:** DISMISS pending evidence.

A true crop-phase experiment is scientifically interesting, but the current
official flat runner already exposes overlap, stride, and blending controls
while anchoring the tile grid at the origin.

Adding a new backend/patch solely to create phase offsets would be architectural
cost before the simpler nuisance sweep has shown that seam sensitivity matters.

Stage A in [issue #143](https://github.com/Svyable/scrollq/issues/143) therefore
uses existing stride/blend controls. Reconsider a phase-offset extension only
if Stage A finds a reproducible held-out effect.

## Fiber-coordinate canonicalization as a standalone architecture

**Status:** DISMISS for now.

Canonical rotation into an estimated fiber/material frame could reduce
orientation nuisance, but it also depends on another estimated quantity whose
errors may dominate the benefit.

Do not build it as a new architecture. It can return as a small ablation inside
fiber/morphology work if those experiments establish reliable local orientation
and a reason to expect a model benefit.

## Generic prediction hashing for ink

**Status:** DISMISS as redundant.

Ink evidence already records exact prediction-file identity and a canonical
digest of the evaluated prediction, labels, mask, and controls. A new generic
hash layer would duplicate stronger task-specific evidence.

The decision does not prohibit another task from adding its own artifact binding
when a real gap is demonstrated.

## Morphology as a universal rule such as "ink is raised"

**Status:** DISMISS.

Surface morphology is heterogeneous. Do not encode universal rules like:

- ink is always raised;
- ink is always depressed;
- ink is always smoother;
- one fixed micron-scale threshold identifies ink.

The surviving morphology path uses conservative descriptors, papyrus-level
holdout, missingness controls, label controls, and a fail-closed transfer gate.
See [morphology-ink-control.md](../morphology-ink-control.md).

## Large-context semantics as a substitute for physical validation

**Status:** DISMISS as a validation strategy.

Larger receptive fields may improve raw prediction quality, but they also make
it easier for a model to exploit character/word-like context. Attractive
letterforms are therefore not evidence of correctness.

If larger-context models are used, they should face stronger physical
falsification: local-evidence ablation, wrong-surface controls, held-out
evaluation, and exact configuration provenance.

## CGAL `Mesh_smoothing_3` as a ScrollQ dependency

**Status:** DISMISS for current integration; WATCH as a possible diagnostic.
Checked 2026-10-04.

The package exists on CGAL `master`. Its `package_info` describes a component
that takes a **3D volumetric mesh** and relocates vertices to trade element
quality against fit to a geometric oracle, with a result free of inverted
elements. The prize path operates on sheet surfaces and TIFXYZ meshes, not
tetrahedral volume meshes, so there is nothing to apply it to.

On licensing, the package's `license.txt` lists two lines, `GPL (v3 or later)`
and `MIT/X11 (BSD like)`. Which terms govern which part, or whether they are
alternatives, is not established here. Treat it as GPL-encumbered until CGAL's
own licensing statement says otherwise; this is a secondary reason, not the
deciding one. Its release timing (announcement date, CGAL 6.3 schedule) was
**not verified**.

Keep the inversion-barrier idea as a test-design reference for fold/inversion
controls on surface meshes. Do not import the implementation. Reconsider only if
a volumetric mesh becomes part of the evidence chain.

## Learned uncertainty head on a frozen backbone (SegWithU-style)

**Status:** DEFERRED (WATCH). Checked 2026-10-04.

SegWithU (arXiv 2604.15271; `ProjectNeura/SegWithU`, Apache-2.0, last commit
`a3157cfff5e50a69b0c880a3d50edfadb4da00d7` on 2026-07-08) attaches a small
supervised uncertainty head to a frozen backbone and reports separate maps for
calibration and for error ranking. Its published results are on ACDC,
BraTS2024 and LiTS only; no papyrus evidence exists. The repository README
indicates that a full release is still pending, so artifact availability is
unverified.

It cannot be tested here as proposed: it taps **intermediate features of a
frozen backbone**, and ScrollQ owns no surface backbone or checkpoint. It
consumes only a published prediction volume. The head also needs labels, so
isolation of training surfaces from evaluation surfaces is a leakage control,
not a formality.

Trigger to revisit: a surface checkpoint with accessible features and a
license that permits this use. Smallest test then: train only the head on
development surfaces and compare it against entropy, margin and ensemble
variance on held-out sheet switches, bridges and unsupported predictions,
by risk-versus-coverage (AURC) and by how many wrong-winding voxels remain among
the most-confident 50/75/90%. Use the output only for abstention, never as an
extra feature fed to ink detection.

## Accumulating all plausible diagnostics

**Status:** DISMISS as a research strategy.

A broad diagnostic catalog can become a form of avoidance. The primary campaign
needs whole-scroll reconstruction and legible text, not an indefinitely
expanding certification framework.

## 2026-10-04 scan: nothing new adopted from outside the Vesuvius stack

**Status:** DEFER (no adoption).

A pass over newly released ink checkpoints, CT reconstruction methods,
flattening implementations and generic segmentation architectures found none
that clears the evidence, licensing and prize-relevance threshold. Several
generic thin-structure methods remain either domain-remote or insufficiently
licensed. Adopting one now would add model complexity without addressing a
demonstrated Vesuvius failure.

The changes that did earn code that day were all integrity gates against
failures already demonstrated in the official tool/data ecosystem (see
[reproducibility-research.md](reproducibility-research.md) §5-7 and
[geometry-and-coverage-research.md](geometry-and-coverage-research.md) §5-6).
Reconsider a generic method only against a measured, reproduced Vesuvius
failure it would fix, with its licence and the separate Vesuvius data terms
checked.

A new diagnostic earns code only if it does at least one of:

- closes a failed gate in the active campaign;
- materially improves a held-out result;
- produces a reviewer-loadable artifact for a real uncertainty;
- closes a concrete reproducibility ambiguity;
- has a cheap falsification experiment whose positive result would change the
  implementation decision.

Otherwise keep the idea in this folder, run the smallest possible experiment,
or discard it.

## Gaussian-splatting CT reconstruction (FaCT-GS)

**Status:** DISMISS for the prize pipeline. Recorded 2026-10-04 from the
maintainer briefing; the repository was not re-read from the build container.

The top-level license is permissive, but as relayed it excludes
`fact_gs/r2_gaussian` and submodule contents, so full dependency provenance is
not simply "MIT". More importantly ScrolIQ works from *reconstructed*
synchrotron volumes, not the raw acquisition problem this method solves.
Reconstructing measured CT through an optimized Gaussian representation would add
a learned, interpolated stage upstream of extremely weak carbon-ink evidence for
a speed benefit that does not justify the new hallucination surface.

Reconsider only with raw projection data in scope and a preregistered
comparison against the existing reconstruction on a physical control.

## Clinical low-dose CT reconstruction (CSRCT)

**Status:** DISMISS for current incorporation. Recorded 2026-10-04 from the
maintainer briefing.

The method targets clinical low-dose CT and, as relayed, reports results on
simulated data; the article is restricted-access and no permissively licensed
implementation or checkpoint stack was found. The sparse-prior idea is
interesting, but neither licensing nor evidence clears the bar.


## 2026-10-04 / 2026-10-05 overnight negative decisions

The full reasoning is in
[the overnight research ledger](2026-10-04-overnight-research.md). The following
variants were explicitly rejected so they do not return as attractive shortcuts:

- **language-model / Greek-likelihood selection of geometry — DISMISS**:
  semantic plausibility must not choose the physical surface;
- **ink-selected recto direction — DISMISS**: circular evidence;
- **renderer-agreement parameter tuning — DISMISS**: cross-renderer agreement
  is a falsification test, not an optimizer;
- **global nearly constant papyrus thickness — DISMISS**: too brittle under
  compression, fusion and carbonization;
- **global monotonic winding radius — DISMISS**: folds/crushing invalidate an
  ideal spiral rule;
- **global blank-pixel conformal calibration — DISMISS**: heterogeneous easy
  blank papyrus hides the difficult false-positive regime;
- **large-window or checkpoint majority consensus as proof — DISMISS**:
  correlated models can share the same priors and errors;
- **higher-resolution target-scan-derived cross-resolution evidence — DISMISS**
  where prize eligibility forbids that target-derived information;
- **scalar submitted-mesh area as completeness proof — DISMISS**: duplicates
  and wrong-wrap substitutions can preserve total area;
- **automatic graph optimization merely to close loop residuals — DISMISS**
  until diagnostic loop closure itself is validated;
- **averaging ablated or perturbed geometry — DISMISS**: counterfactual surfaces
  intentionally omit or perturb valid evidence and are not equal hypotheses;
- **multi-scale / rotated prediction averaging as independent ink evidence —
  DISMISS**;
- **automatic filling of abstained pixels — DISMISS**: manufactures morphology;
- **automatic exclusion of damaged regions from prize metrics — DISMISS**:
  reviewer adjudication must remain external;
- **inferring physical damage from blank ink output — DISMISS**: circular;
- **automatic rejection from neighboring-sheet response — DISMISS** until the
  shadow test itself is calibrated;
- **neighbor-sheet disagreement as affirmative proof of ink — DISMISS**;
- **universal bit-for-bit reproducibility — DISMISS** in favor of declared
  physical/numerical invariants;
- **snapshot-testing final rendered letter images as the scientific regression
  gate — DISMISS**;
- **using counterfactual papyrus transplantation as training augmentation before
  it earns value as a falsification test — DISMISS**;
- **automatically suppressing every context-sensitive prediction — DISMISS**;
- **rotating final 2-D ink output until text looks coherent — DISMISS**.

These decisions do not block the surviving bounded experiments. They define the
epistemic boundary those experiments must preserve.

## Deferred, not dismissed

The following remain live but should not consume primary-pipeline priority until
their required inputs exist:

- continuous surface-normal ink response curves;
- causal context ablation;
- acquisition-physics normalization/conditioning;
- cross-parameterization detector invariance;
- stride/blend seam invariance;
- independent recto coverage witnesses;
- fiber-texture physical sheet fingerprints, including phase-preserving seam
  authentication (synthetic software controls done; real CT unmeasured);
- sealed-scroll morphology transfer after the source scale discrepancy is
  resolved;
- a learned uncertainty head on a frozen surface backbone, once a backbone
  with accessible features exists;
- CSWinUNETR (cross-shaped stripe attention for thin structures): WATCH. As
  relayed on 2026-10-04 its repository has no explicit software license, and
  public source is not permission to reuse it, so ScrolIQ neither vendors nor
  derives code from it. If a license appears, the smallest experiment is an
  architecture-only A/B on exactly the same licensed Vesuvius training cubes,
  augmentations, optimizer and committed held-out ROIs as the existing surface
  model, promoted on surface coverage, adjacent-winding bridges, Betti/component
  error and sheet-switch count rather than Dice alone. The risk is that a
  mechanism built to reconnect interrupted structures connects two neighbouring
  windings instead.

"Deferred" means the hypothesis survived reasoning, not that implementation has
been approved.
