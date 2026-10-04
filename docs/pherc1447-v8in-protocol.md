# PHerc1447 v8-in held-out ink campaign

**Status: frozen protocol; no external metric is accepted as a measured
ScrolIQ result until reproduced from immutable inputs.**

This campaign evaluates the public Youssef Nader ~8–9 µm `v8-in` ink release
against PHerc1447 winding data under the 2027 Grand Prize evidence rules. The
eligible Grand Prize CT target is PHerc1447 volume `20250521151220`. The
official prize page remains authoritative if eligibility changes.

External release roots:

- model: `YoussefMoNader/ink-8um-v8in`
- PHerc1447 finetune: `YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062`
- training corpus: `YoussefMoNader/ink-8um-v8-patchpack`
- PHerc1447 surfaces/labels/predictions:
  `YoussefMoNader/ink-8um-pherc1447-surfaces`

The author-reported scores are motivation for this campaign, not input data.

## Freeze before evaluation

Before reading or publishing any ScrolIQ score, resolve all four Hub repositories
with `scroliq-hf-pin`. Commit those JSON pins to a new dated artifact directory.
The campaign may not use a moving `main` reference after that freeze.

Download every checkpoint, inference/training script or config, label, validation
mask, prediction and geometry artifact used in scoring from the resolved commit.
Hash the local bytes. If an expected artifact cannot be pinned and hashed, that
arm is `blocked`, not silently replaced.

The release metadata must also establish:

1. exact source CT volume/resolution for every PHerc1447 render;
2. model layer/depth order and all output-affecting inference settings;
3. training-data identities at the narrowest published split level;
4. whether training or inference is stochastic and the fixed seed for each;
5. public training and inference experiment-run records required by the prize;
6. dataset/checkpoint licenses required by `scroliq-model-release`.

Missing public experiment tracking is a release-compliance failure even when a
checkpoint produces good predictions.

## Pre-registered evaluation arms

### A. Base-model zero-shot transfer

Run the immutable base `v8-in` checkpoint on PHerc1447 w058, w060 and w062
without any PHerc1447 training or fitting. Each winding is a separate held-out
region. This is the strongest cross-scroll generalization claim in the release.

Primary metric per winding: **ROC AUC** from `scroliq-ink-validate`.

Required companion metrics: balanced accuracy, false-positive rate, F1, IoU,
Brier score, ink/background probability margin and both-class presence.

No aggregate may drop a failed or missing winding. If the common
`scroliq-eval` adapter is used, its failure value remains in the denominator.

### B. Same-scroll leave-one-winding-out adaptation

Evaluate a finetuned checkpoint only on the winding explicitly excluded from
that checkpoint's training. The released `loo-w062` checkpoint may therefore
be scored on w062 after its training-data declaration is verified.

Predictions for another held-out winding may be preserved as evidence, but they
are not called reproducible LOO model results until the exact producing
checkpoint, training split and inference identity are public and pinned.

Zero-shot and same-scroll LOO results are never pooled into one generalization
number.

## Mandatory falsification controls

Every scored winding must include at least one physical/input falsification
control in the same `scroliq-ink-validate` artifact. The campaign will prefer
two:

- **layer-order control:** rerun inference with the depth/layer order reversed
  relative to the frozen correct preprocessing contract;
- **surface-offset control:** render the same XY surface coordinates after a
  frozen normal displacement, then rerun identical inference.

Controls use the same labels and validation mask as the primary surface. Report
`primary_minus_control_roc_auc` and the existing thresholded/control deltas.
A positive delta supports physical specificity; it is not proof of readable
text.

If a control cannot be generated reproducibly from the released geometry, the
winding does not become prize-evidence-ready merely because its primary AUC is
high.

## Leakage boundary

Base zero-shot evaluation requires a verified declaration that no PHerc1447
training data entered the base checkpoint.

LOO evaluation requires exact region/split identifiers showing the scored
winding was excluded. Same-scroll neighbouring windings are not automatically
disjoint: where training/prediction regions are spatially representable, bind
them using the Grand Prize half-open level-0 voxel region contract.

Any uncertainty is `unknown`/blocked, not `none`.

## Source-volume rule

PHerc1447 Grand Prize evidence must ultimately trace to eligible volume
`20250521151220`. A surface, label or prediction derived from another
PHerc1447 scan may be scientifically informative but cannot silently stand in
for the eligible CT in the final provenance graph.

ZPA remains responsible for CT/Zarr source integrity and physical-resolution
attestation. ScrolIQ consumes that evidence; it does not duplicate it.

## Campaign outputs

A completed dated campaign contains:

- four immutable Hub pin JSON files;
- local byte-hash inventory;
- normalized model card(s);
- `scroliq-model-release` report;
- exact region/split manifest;
- one `scroliq-ink-validate` report per winding and model arm;
- falsification-control predictions and hashes;
- common `scroliq-eval` aggregation where applicable;
- commands, environment/container identity, seeds and public run URLs;
- limitations distinguishing ink recovery from papyrological legibility.

Only after those artifacts exist may reproduced numbers be promoted into the
Grand Prize readiness page or submission methodology.
