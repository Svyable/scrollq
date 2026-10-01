# Grand Prize blind probe protocol

This protocol is the second stage after `scrollq-grand-prize`. Its purpose is
to decide whether to commit the full unrolling campaign to **PHerc0800**,
**PHerc0813**, or **PHerc1447** using evidence from the actual prize-eligible
volumes.

These are intentionally different hypotheses rather than the top three rows of
a weighted ranking: PHerc0813 is the scan-quality leader, PHerc1447 has the
strongest existing public-segment bootstrap, and PHerc0800 combines six public
segments with better exact-volume imported surface-support evidence than either.
The imported support metric is sensitivity evidence, not a readability claim.

Official references:

- Grand Prize rules: https://scrollprize.org/prizes
- Spiral fitting: https://scrollprize.org/tutorial_spiral
- Winding constraints: https://scrollprize.org/open_problems/winding_annotations
- Ink detection: https://scrollprize.org/tutorial5

## Principle

Do not optimize for pretty renders. Optimize for evidence that survives
held-out geometry checks and falsification controls.

The comparison is deliberately blind and symmetric:

- same number of sampled regions per scroll;
- same tools and hyperparameters across all three first-wave targets;
- same maximum human-verification time;
- same held-out fraction;
- fixed random seed where randomness is unavoidable;
- exact prize-eligible volume only;
- no same-scroll higher-resolution data.

## Stage A — provenance and integrity gate

For each target:

1. Record exact volume ID, voxel size, energy, source URLs, and hashes/ETags
   where available.
2. Run zarr-pyramid-audit against the CT, surface prediction, and lasagna
   inputs.
3. Run ScrolIQ against the exact eligible CT volume.
4. Record the surface-prediction and lasagna model IDs and pyramid levels.
5. Fail closed on high-severity storage/integrity findings.

No geometry or ink result is considered interpretable until this gate passes.

## Stage B — deterministic 24-region geometry sample

Define the occupied scroll support and umbilicus in CT coordinates. Sample 24
seed regions per scroll using a fixed spatial design:

- 3 axial bands: lower / middle / upper;
- 2 radial shells: inner / outer;
- 4 sectors around the umbilicus.

This yields 3 x 2 x 4 = 24 regions distributed across the body rather than
whatever areas happen to look easiest.

For each region:

1. Inspect the released surface and lasagna predictions.
2. Generate a local patch using the same method and settings on both targets.
3. Verify whether the patch follows exactly one sheet using CT continuity and,
   where visible, horizontal papyrus fibers.
4. Record failures explicitly: no usable seed, sheet switch, prediction
   unsupported by CT, topology break, ambiguous winding, or tool failure.
5. Record human-verification time.

Do not delete failed regions from the denominator.

## Stage C — hold-out split before spiral fitting

Before any global fit, deterministically assign the 24 regions:

- 18 fit regions;
- 6 held-out geometry regions.

The six held-out regions must never become spiral-fit inputs. They exist only
to test whether the fitted surface predicts independently verified geometry.

After the split is frozen, certify spatial separation with
`scroliq-geometry-probe --minimum-fit-holdout-gap-voxels <N>`, where `N` is
predeclared from the largest spatial influence radius of any fit input or
derived supervision used by the experiment. The certificate measures the
Euclidean gap between fit and held-out candidate axis-aligned XYZ boxes in
base-resolution voxel space. A positive box gap is conservative evidence: if
the boxes are at least `N` voxels apart, the contained surfaces are at least
that far apart. A zero box gap is only ambiguous — it does not prove the
surfaces touch — and must be resolved with an exact surface-distance check
before the held-out region can be called independent.

The gap threshold is an exclusion rule, not a split optimizer: changing it
must never reshuffle which regions are held out after results have been seen.

Store the split and its separation certificate in a checked-in JSON manifest.

## Stage C.5 — optional certified winding constraints

Before the spiral pilot, run a target-local diagnostic of the public PCU
certified-winding method from `Jashann/vesuvius-scrolling`, pinned to commit
`4f4997adcccaa9124ab5af02605233f7e3388c69`.

PCU is not assumed to transfer at its published Paris 4 precision. Its own
report shows strong improvement in one band and no measurable improvement in a
harder band, so use it conditionally:

1. Generate certificate statistics on the **fit cores only**.
2. Record certified/gold constraint density and coverage by axial band.
3. If coverage is sparse or unstable, keep the baseline spiral fit rather than
   forcing low-confidence constraints.
4. If used, feed only the pre-declared confidence tier into the fit and keep
   the configuration/weight fixed across the first-wave targets.
5. Never use PCU output as the sole held-out reference: PCU and the spiral fit
   share Lasagna-derived information. Held-out scoring remains based on
   independently verified CT/fiber geometry.

The upstream code is MIT. Upstream scroll-derived constraints/checkpoints are
CC BY-NC-SA 4.0; preserve attribution and do not silently relicense them.

## Stage D — 1,000-slice pilot spiral

The official spiral-fitting tutorial recommends beginning with roughly a
1,000-slice range before scaling to the whole written region.

For each target, run the same pilot configuration with:

- verified fit patches;
- same-winding fibers/lines where available;
- relative-winding annotations where needed;
- umbilicus;
- released lasagna normals / gradient guidance at the metadata-declared scale;
- fixed optimizer seed;
- online experiment tracking for any stochastic run.

Keep the generated run folder intact: checkpoint, satisfaction metrics,
overlays, and winding meshes.

## Stage E — geometry decision metrics

Evaluate the pilot on the six held-out regions, not just the fit inputs.

Record at minimum:

- held-out patch-to-fitted-surface distance distribution in voxels;
- held-out single-winding agreement;
- observed sheet-switch count;
- self-intersection / topology failures;
- fit-input satisfaction metrics;
- axial coverage achieved;
- human minutes spent creating/verifying constraints;
- failed-region count from the original 24-region denominator.

Do not collapse these into a single opaque score. Compare the targets as a
multi-objective evidence table.

A target advances only if its global fit is geometrically credible on held-out
regions, not merely on the annotations used to fit it.

## Stage F — blind ink probe

Only after Stage E passes:

1. Flatten/render the held-out-correct geometry.
2. Run identical ink inference on both targets.
3. Keep model windows physically small enough that outputs are tied to local CT
   evidence rather than long linguistic context.
4. Use checkpoints/training data that do not overlap the prediction regions.
5. Record all seeds and exact model/checkpoint hashes.

Every promising ink region gets falsification controls:

- correct surface;
- +3 voxel normal offset;
- -3 voxel normal offset;
- adjacent winding;
- perturbed geometry;
- independent checkpoint / fold.

A candidate is stronger when the signal is stable across independent models
but localized to the correct physical surface and degrades under the offset
controls.

No papyrological interpolation is used to decide whether this stage passes.

## Stage G — target commitment

Commit the whole-scroll campaign only after the evidence table exists for all
three first-wave targets: PHerc0800, PHerc0813, and PHerc1447.

The decision record must state:

- which target was selected;
- which evidence dimensions drove the decision;
- where each non-selected target was stronger;
- unresolved risks;
- exact artifact paths supporting every claim.

If none of the three produces credible held-out geometry, expand the same
protocol to PHerc0191, PHerc0211, and PHerc0268. PHerc1203 should not enter a
surface-support comparison until its prize-eligible 9.362 µm volume has been
audited directly; the currently imported PHerc1203 support survey used the
ineligible same-scroll 2.403 µm volume.

## Human-time accounting

Start the Grand Prize manual-input ledger now, even though this is still a
pilot. Record each manual activity with start/end time and purpose. This keeps
the eventual automated pipeline comfortably inside the prize's documented
human-input allowance and prevents undocumented annotation debt from building
up during experimentation.
