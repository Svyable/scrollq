# Structure-aware conformal uncertainty sets for surface predictions

**Status:** EXPERIMENT FURTHER. Queued 2026-10-04. **Not preregistered; nothing
is frozen and no CT or prediction data has been read for this experiment.**

This note queues one post-hoc audit experiment. It does not change a surface
model, a mesh, or the production campaign.

## Motivation

A surface predictor has two qualitatively different failures:

- **boundary error** — the sheet is here, but its position is uncertain;
- **structural omission** — a winding, fragment, or component was never
  recovered, so no amount of local expansion can reach it.

A conformal set built by growing the prediction (probability thresholding,
isotropic dilation) can keep its formal coverage guarantee while becoming
operationally useless: missed components saturate the calibrated score and the
calibrated radius grows until the set is vacuous. The 2026 UNSURE workshop paper
below makes this argument for 3D tumor segmentation. It maps directly onto the
"crushed region / missing winding" problem, where voxelwise confidence conflates
the two failure classes.

The downstream use is evidential, not predictive: a claim of the form "the
surface is localized within this region" is allowed only where a *calibrated*
set achieves its preregistered held-out coverage. Elsewhere the correct output is
abstention or "structurally unresolved". Ink predictions on sheets whose identity
falls outside the validated envelope must not be counted as independent textual
evidence. This is an eligibility rule applied after geometry is frozen; ink is
never used to choose or tune the envelope.

## Verified upstream facts (checked 2026-10-04)

| Item | Verified | Source |
|---|---|---|
| Paper: Vargas, Rossi, Zuluaga (EURECOM), *Beyond Morphological Dilation: Revisiting Conformal Prediction for 3D Tumor Segmentation*, UNSURE 2026 (MICCAI workshop), 2026-09-27 | yes | <https://www.eurecom.edu/en/node/4941475> |
| Abstract claim: dilation sets become vacuous under disconnected segmentation errors; instance-level CP separates boundary and structural errors; geodesic CP replaces isotropic dilation; unified method eliminates vacuity over 100 BraTS 2021 splits | as stated in the abstract; **not reproduced here** | same |
| Code: `robustml-eurecom/conformal-tumor-segmentation`, **MIT** (`Copyright (c) 2026 The Authors`), one commit "Initial release" 2026-08-14, abbreviated SHA `a6e09a9` | yes (raw `LICENSE`) | <https://github.com/robustml-eurecom/conformal-tumor-segmentation> |
| Methods in code: `threshold`, `dilation`, `geodesic`, `instance`, `unified`; synthetic-phantom unit tests (`pytest -q`, quantile exactness, coverage validity, vacuity) | yes (README) | same |

The full 40-hex SHA was not visible from the page used. Resolve and record it
before any code is vendored or any result cites the upstream implementation.

### What the upstream code actually does (corrections to the intake brief)

Read from `conformal/conformal.py` at the revision above; only that file was
read, so anything not listed is unverified.

- **Finite-sample quantile.** `k = ceil((n+1)(1-alpha))`. If `k > n` the
  threshold falls back to a cap and the result is flagged **vacuous**. A
  threshold at the cap is also vacuous. This is the same rule the existing
  `scroliq-segmentation-uq` already uses.
- **Mondrian groups are ground-truth tumor size strata** (`size_stratum`), not
  scan or scroll. Per-scroll / per-scan / voxel-size / crushed-vs-regular strata
  would be a ScrollQ *adaptation*, not existing upstream behavior. This repo has
  no Mondrian code.
- **The instance-level guarantee is not containment.** It is a two-part claim:
  matched components covered at tau, **and** a structural-miss fraction bounded
  by `beta*`, with `alpha` split `alpha/2` each (Bonferroni). A case with no
  matched component satisfies the spatial clause trivially. Missed structure is
  therefore *quantified*, not contained. For a sheet this means a completely
  missed winding raises the missed-area mass; it does not become covered.
- **The geodesic cost map is not defined in that file** (it reads cached
  `geo_*` curves produced elsewhere). Do not describe the geodesic construction
  as verified until `morphology.py` / `scores.py` have been read.

## Relationship to `scroliq-segmentation-uq`

[`scroliq-segmentation-uq`](../segmentation-uncertainty.md) is a **region-level
scalar** audit over trusted scorer outputs (`symmetric_p95_voxels`,
`truth_component_recall_any`). It already separates boundary from complete
component omission and rejects vacuous bounds. This experiment tests the
complementary **voxel/set-level** layer: whether a calibrated *uncertainty set*
(not a scalar bound) contains the correct physical sheet. If the set-level
constructions add nothing beyond the scalar gate, the correct outcome is to
close this note.

## Smallest experiment

Freeze everything first; the prediction model is never altered.

**Inputs (candidate, to be verified).** The independently published PHerc0139
`surface-m7` level-0 prediction and the public w035 TIFXYZ on the exact
9.362 µm volume, as already used by the wrong-wrap, coverage-witness and
connectivity experiments. ScrollQ owns **no surface model or checkpoint**, only
this published prediction volume.

**Must verify before preregistration.** The stored array is uint8 and the repo
thresholds it at `>127`. Sample chunks and report the value histogram. If it is
effectively binary, the probability-thresholding arm is degenerate and
confidence-guided geodesic expansion has nothing to follow; the experiment then
needs a graded source or is closed.

**Three constructions**, each calibrated only on the calibration ROIs:

1. probability thresholding;
2. ordinary isotropic dilation;
3. instance-level + confidence-guided geodesic expansion (the paper's
   construction, implemented independently unless reuse is explicitly approved
   below).

**ROI split.** Calibration ROIs and proof ROIs are disjoint in space (certified
with `scrollq-geometry-probe`, not by ID alone). **The six PHerc0139 centers used
in the wrong-wrap, coverage-witness and connectivity experiments are
development-exposed and are excluded from the proof set.**

**Failure classes**, reported per class, never pooled:

| Class | Source | Role |
|---|---|---|
| small boundary offset | natural | coverage test |
| neighboring-winding switch | natural: `surface-m7` is known to contain separated, CT-supported competing windings 13–29 voxels from w035 (32/32 probes) | coverage test |
| false bridge | natural where present, else injected | coverage test / control |
| hole | injected by deletion | positive control |
| completely missed sheet fragment | injected by deletion | positive control |

Injected classes are **controls that show the vacuity detector can fire**, not
coverage evidence: a conformal guarantee holds only for the calibration/test
distribution, so a hand-built failure process certifies nothing about natural
failures. Natural-ROI coverage and injected-control sensitivity are reported
side by side.

**Reported per construction and stratum:** empirical held-out coverage of the
correct physical sheet versus nominal; vacuity flag and calibrated radius;
set volume/area relative to the reference sheet; and **structural-miss mass**
(area fraction of reference sheet with no predicted support within tolerance),
reported separately from boundary coverage.

**Abstention semantics.** A region may be labelled "surface localized within
this uncertainty region" only if its stratum's calibrated set met the
preregistered held-out coverage and was not vacuous. Otherwise it is
`structurally_unresolved` or `abstain`; never silently covered.

### Exchangeability and sample size

Formal validity needs calibration and test cases from a comparable
distribution. Different scrolls, scans, voxel sizes and crushed versus regular
geometry are separate strata, never pooled to reach a sample size.

The rank rule requires `n >= 1/alpha - 1` calibration ROIs **per stratum**: 19
at `alpha = 0.05`, and **39** where the instance-level `alpha/2` split applies.
A stratum below that is reported vacuous, not rounded up. With a single scroll
and a handful of ROIs this is the likely binding constraint, so the
preregistration must state the achievable `n` per stratum before anything is run
and state the loosest `alpha` it will accept in advance.

### Freeze before any data is read

- exact prediction and CT identities (URL, shape, hash) and reference TIFXYZ;
- ROI centers/sizes for calibration and proof, with the disjointness check;
- `alpha`, strata definitions, tolerance, and maximum non-vacuous radius;
- the stored-value histogram result above;
- injection recipes and seeds for the control classes;
- the decision rule (below), computed by code, not by judgement.

## Promotion gate

Promote to a production audit layer only if, on untouched natural ROIs and in
every stratum that was kept:

1. the winning set-level construction achieves its nominal held-out coverage
   and is **not vacuous** where the dilation/threshold constructions are;
2. it beats both baselines on structural-miss accounting (does not hide missed
   mass inside a large radius);
3. the injected missed-fragment and hole controls are detected rather than
   absorbed;
4. neighboring-winding switches are either excluded from the validated envelope
   or explicitly marked unresolved, not silently counted as covered;
5. results replicate across more than one stratum or scroll, or the claim is
   scoped to the single stratum tested.

A FAIL is preserved next to any later run. Thresholds are not tuned after
observation. A PASS authorizes an unchanged holdout preregistration, not a
Grand Prize claim.

## Self-evaluation

Proposer's assessment, adopted against the shared rubric; to be revised after the
histogram and sample-size checks.

- prize impact: **high as an audit layer**, medium on segmentation quality
- plausibility: **medium-high**
- evidence burden: **medium-high**
- implementation cost: **medium-low** once a graded prediction exists
- reproducibility burden: **low** (post-hoc, deterministic)
- invalid-evaluation risk: **medium** — exchangeability, and injected controls
  mistaken for coverage evidence
- hallucinated-ink risk: **low**; ink is used only afterward as an eligibility
  filter, never to select geometry
- VC3D compatibility: **medium-high** via review regions for unresolved areas
- surface area: **low**; remove the experiment cleanly if the gate fails

## Reuse and licensing

The upstream code is MIT, so reuse is legally possible. The default remains an
independent ScrollQ implementation, matching
[`scroliq-segmentation-uq`](../segmentation-uncertainty.md). If code is vendored
instead, the same change must add the full upstream SHA, license text and
redistribution notice to `THIRD_PARTY_NOTICES.md`, as that file requires.
