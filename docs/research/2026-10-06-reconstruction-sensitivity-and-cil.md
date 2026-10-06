# Reconstruction-family invariance, calibration sensitivity and generative-geometry screens — 2026-10-06

**Status:** one experiment design INTEGRATED in a bounded role, with its audit
executable (`scroliq-reconstruction-sensitivity`, synthetic controls only);
one CIL feature held at WATCH; one paper held at WATCH for a single audit
practice; three generative-geometry releases DISMISSED. No scoring behaviour,
training path, frozen artifact or Grand Prize execution order changes, and
neither CIL nor ASTRA becomes a ScrolIQ dependency.

## What was read here and what was relayed

Claims about external work come from the 2026-10-06 maintainer briefing unless a
line says it was read here. Read here, through web-search result summaries only
(no page was opened):

- CIL v26.0.0 was published on 17 June 2026 (Zenodo record) and the framework is
  Apache-2.0.
- The ASTRA Toolbox is GPLv3, and the CIL ASTRA plugin is described on a CIL page
  as GPLv3 while CIL itself is Apache-2.0 with "individual plugins" possibly
  differently licensed.
- Vesuvius data are described as CT volumes (TIFF stacks and OME-Zarr) and
  surface segments from ESRF; the search summaries did not mention raw projections.

Not verified here: the CIL 26 feature list (LSQR with optional Tikhonov
regularisation, reconstruction-volume shrinking, the projection-matching geometry
corrector, lower-memory ASTRA operators, centre-of-rotation and Paganin fixes);
the October DRR paper; every claim about T3lescope, OptimusMesh and MEGA; and the
re-check of the official Vesuvius stack and winners page. `www.ccpi.ac.uk` and
`scrollprize.org` are blocked by this container's egress policy, so the release
announcement and the data pages could not be fetched. A search for the 26.0.0
LSQR/Tikhonov feature returned no confirmation.

## 1. CIL 26 as a reconstruction-family reference

**Decision: INTEGRATE EXPERIMENT, in a tightly bounded role.** Use CIL as a
reference implementation to vary the reconstruction mathematics while the
measured projections, geometry and downstream pipeline stay fixed. It is not a
replacement for the official Vesuvius reconstruction, not a learned enhancer, and
not a candidate ink producer.

**What was built:**
[`scroliq-reconstruction-sensitivity`](../reconstruction-sensitivity.md), the audit
that reads each variant's frozen outputs. For each reference ink component it
records persistence across the preregistered family, surface displacement along
the reference normal, neighbouring-sheet separation, fibre-orientation stability,
ink-response position along the normal and the variants' detections inside
known-negative regions. A component present under only one reconstruction
assumption is `reconstruction_sensitive` evidence, not prize-grade ink. The audit
enforces ink-blind early selection, one shared measured dataset, a calibration
variant that differs from its baseline only by a bounded declared perturbation,
failed reconstructions that are listed and never dropped, and variants that did not
vary the volume that cannot pass.

**Relation to the FaCT-GS dismissal.** That entry says to reconsider "only with raw
projection data in scope and a preregistered comparison against the existing
reconstruction on a physical control" ([dismissed](dismissed-and-deferred.md)).
This is that comparison in the narrow form of an invariance test over classical
inverse solutions, with no learned or Gaussian stage between the measurements and
the volume; the dismissal of FaCT-GS itself stands.

**Blockers, in order.**

1. *Raw projections and acquisition geometry for one manageable ROI.* Not
   established here. ScrolIQ holds reconstructed volumes, and the data pages that
   could settle this were unreachable. If projections are not released, the
   experiment cannot start and the audit stays machinery.
2. *Reproducing the geometry exactly* in an external tomography environment
   (detector, centre of rotation, tilt, energy, preprocessing). Any mismatch makes
   an official-versus-CIL difference a statement about the mismatch.
3. *A reproducible official reconstruction* of the same ROI to serve as the
   reference.

**A design caveat the audit cannot remove.** Official-versus-CIL differs in
preprocessing and algorithm at once, so a component lost in LSQR *and* in both
Tikhonov variants points at that difference, not at regularisation. Only the
LSQR-to-Tikhonov contrasts change one declared parameter. Read the per-variant
`absent-in` reasons accordingly (this is written into the doc's limits).

**Licensing, recorded explicitly.** CIL is Apache-2.0, but the ASTRA path it uses
for projectors is GPLv3 (the plugin as well, per the summaries read). The
top-level licence is not inferred for any execution path. The clean initial
experiment is an isolated external environment with an exact transitive
dependency manifest; each variant declares that manifest and its packages'
licences, and the report classifies them (`copyleft_present` for an ASTRA path).
The frozen volumes cross into ScrolIQ as data; ScrolIQ stays MIT and imports
neither package. This extends the pattern of the CGAL and CSWinUNETR entries:
licence review before technical enthusiasm.

**Self-evaluation:** Grand Prize applicability medium-high where projections are
available, none where they are not; direct performance impact unknown, audit
impact high; integration difficulty medium (geometry must be reproduced
exactly); compute medium-high but controlled on a small ROI; training leakage
zero; prediction leakage zero provided ink is excluded from reconstruction
selection (enforced as a declared, unprovable-in-time field); hallucinated-ink
risk low for the experiment itself.

## 2. Acquisition-calibration sensitivity

**Decision: INCLUDE as a bounded arm of the same audit; WATCH CIL's
`LaminographyGeometryCorrector`.**

Vesuvius data are not automatically a laminography problem, so projection-matching
geometry correction is not applied blindly. The generic idea is built in: known
acquisition parameters (centre of rotation first) are perturbed by small amounts
preregistered with their evidence in `calibration_bounds`, the same ROI is
reconstructed with the same algorithm as the baseline, and the audit asks whether
supposed ink survives. If tiny calibration changes manufacture or erase
glyph-like components, the conclusion is greater reconstruction uncertainty, never
the choice of the most readable calibration. A parameter without a preregistered
bound cannot be perturbed, and an out-of-bound value is a spec refusal. This
strengthens an *acquisition-calibration sensitivity* proof gate. CIL's lower-memory
ASTRA wrappers are an enabling optimisation only if the experiment proceeds.

## 3. Standardised reproducible DRR pipeline (October 3 paper)

**Decision: WATCH, retaining one audit practice.** Its application is
medical-CT-derived radiographs rather than inverse synchrotron reconstruction. The
practice adopted: any ScrolIQ forward-projection experiment fingerprints
preprocessing, coordinate conventions, projection geometry and software versions
instead of treating "synthetic projection" as one operation. Those fields are the
`family` fingerprint and per-variant `software`/`algorithm` records in the spec.

## 4. Generative geometry

| Release | Decision | Reason |
|---|---|---|
| T3lescope | **DISMISS** (already recorded earlier on 2026-10-06) | learned completion of sparsely observed surfaces is the wrong inductive behaviour for CT-supported papyrus |
| OptimusMesh | **DISMISS** | autoregressive compact meshes from sparse point clouds; plausible compact topology is not CT-supported papyrus topology |
| MEGA | **DISMISS** | watertight meshes via rendered supervision from 3-D Gaussian scenes, an appearance prior rather than independent CT evidence |

These extend the generative-meshing entries in the
[automesh note](2026-10-05-automesh-harvest-qc.md).

## 5. Official stack re-check

Relayed, not read: the public Villa documentation still names VC3D, Lasagna and
spiral fitting as the active automatic-unwrapping routes with the older
Thaumato-Anakalyptor pipeline deprecated, and the official winners page still
lists the August 2026 patch-based unwrapping, 9-um surface-model/ScrollFiesta and
dense-label ink-checkpoint benchmarking work as the latest Progress Prize
winners. No newer official model or checkpoint was found that supersedes earlier
recommendations. `scrollprize.org` could not be fetched here to confirm.

## Process note

The audit was built before any data exists because a clean result from a family
that did not actually vary is vacuous, and that failure is checkable now: the
no-op control is the same lesson as the configured-versus-effective objective
audit. The real experiment waits on projections nobody here has confirmed exist.
