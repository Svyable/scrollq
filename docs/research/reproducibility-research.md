# Reproducibility and proof-chain research

Two exploratory ideas in this area cleared their promotion gates and are now
part of ScrollQ. They are recorded here because they began as research
hypotheses and because their claim boundaries matter.

## 1. Exact inference-configuration binding

**Status:** INCLUDE. Merged in
[PR #142](https://github.com/Svyable/scrollq/pull/142).

### Problem

A checkpoint hash, inference-script hash, and random seed do not uniquely
identify an inference procedure. The same code and weights can emit materially
different predictions when output-affecting settings differ, including:

- overlap / stride;
- blend mode;
- layer/depth window;
- resolution;
- direction;
- test-time augmentation;
- other model-specific inference knobs.

Without binding those settings, two materially different prediction procedures
can look provenance-equivalent.

### Implemented decision

Model cards can carry a non-empty JSON `inference_config`.
`scroliq-eval` canonicalizes that object and SHA-256 binds it into preflight
and report provenance. Missing configuration blocks rank eligibility.

The contract is deliberately model-agnostic: the evaluator does not hard-code
one ink runner's CLI.

### Why this earned INCLUDE

- concrete reproducibility failure rather than hypothetical architecture;
- small code surface;
- no change to scientific metrics or model outputs;
- deterministic and independently verifiable;
- directly enables nuisance-arm experiments such as stride/blend invariance.

See [model-evaluation.md](../model-evaluation.md).

## 2. Scored-result run identity binding

**Status:** INCLUDE. Merged in
[PR #147](https://github.com/Svyable/scrollq/pull/147).

### Problem

After inference configuration was hash-bound, a stale task-adapter result file
could still be supplied later and scored against a newer/current model card.

That is a distinct provenance failure: the declared run can be exact while the
score record belongs to another run.

### Implemented decision

Task-adapter result files can carry the verified:

- `checkpoint_sha256`;
- `inference_script_sha256`;
- `inference_config_sha256`.

`scroliq-eval` compares them with the identities verified in the current
evaluation. Missing or mismatched identity blocks rank eligibility.

Legacy files remain parseable for migration but cannot rank without the binding.

### Claim boundary

This proves that the **score record** names the same verified run identity.
It does not, by itself, prove that arbitrary prediction-array bytes were
produced by that run. Prediction/evaluated-array identity remains task-specific.

For ink, that stronger artifact binding already exists in
`scroliq-ink-validate`, which records exact prediction-file identity and a
canonical digest of the evaluated prediction/label/mask/control arrays.

## 3. Generic prediction-artifact provenance layer

**Status:** DISMISS for ink as redundant.

After PRs #142 and #147, it was tempting to introduce a new generic subsystem
that would hash prediction arrays for every task.

For ink, this would duplicate stronger existing evidence:

- exact prediction-file SHA-256;
- canonical `evaluated_arrays_sha256`;
- binding of labels, validation mask, and falsification controls;
- Grand Prize provenance checks over the resulting evidence.

The correct design is composition:

1. model/run configuration identity;
2. score-record run identity;
3. task-specific exact artifact/evidence identity.

A generic layer should be reconsidered only if another task has a concrete
artifact-binding hole that cannot cleanly be solved in its own adapter.

## 4. Reproducibility as an experimental enabler

These provenance changes are not merely administrative. They make stronger
scientific experiments possible.

For example, a stride/blend experiment can now produce multiple arms whose
checkpoint and inference code are identical while the exact nuisance
configuration is cryptographically distinct. The result records can then prove
which arm was actually scored.

This is the preferred relationship between infrastructure and research:
implement infrastructure when a concrete experiment or submission claim needs
it, not as speculative certification surface area.

## 5. Producer-success semantic validation

**Status:** INCLUDE (2026-10-04). Extends `scroliq-vc3d-run-guard`;
contract in [vc3d-run-guard.md](../vc3d-run-guard.md).

### Problem

A public VC3D report (maintainers' note; not reproduced here) describes
`vc_grow_seg_from_seed` deleting the surface it just generated and exiting 0
when the volume is an `s3://` path: voxel-size metadata is read through a local
file operation, the resulting physical area falls below the minimum-area check,
and the output directory is removed. Process supervision sees success.

The guard already refused a missing, empty or sub-threshold surface. Three
holes remained: the voxel size was a bare declaration, a no-op copy of the input
passed, and a producer's own metadata was never compared with its vertices.

### Implemented decision

An exit-0 run is `PRODUCER_SEMANTIC_FAILURE` unless the output also has
recomputed physical area from verified voxel spacing, a recorded extent that is
consistent with the declared bbox and the volume bounds, and a decoded-geometry
digest that differs from every declared input. Gates whose evidence was not
supplied are listed in `unevaluated_gates`, not silently passed.

### Why this earned INCLUDE

- a specific code path and reproduction, not a hypothetical;
- very low difficulty and negligible compute; no leakage risk;
- the same gate set applies to any external TIFXYZ producer;
- spurious-ink risk falls indirectly: rendering cannot proceed from silently
  missing or malformed geometry.

Other runners (`scroliq-spiral-run`, `scroliq-spiral-export`) keep their own
receipts; adopting `evaluate_postconditions` there is a follow-up.

## 6. Configured vs effective objective

**Status:** INCLUDE as an audit field and validator (2026-10-04); the Lasagna
experiment that motivated it is WATCH, see
[geometry-and-coverage-research.md](geometry-and-coverage-research.md).
Contract in [objective-audit.md](../objective-audit.md).

A nonzero configured loss weight is not evidence that a term contributed
gradients. Training or optimization passports now have a place to record
per-term evaluation, finite and nonzero counts, accumulated contribution and
gradient norm, and `scroliq-objective-audit` fails closed when a claimed
safety/topology term never activates, or when an ablation arm's "disabled" term
is not actually disabled. Claim boundary: it audits that terms did what the
config says, not that the objective is good.

## 7. Spatial metadata is recomputed, never trusted

**Status:** INCLUDE (2026-10-04). Contract in
[tifxyz-metadata-integrity.md](../tifxyz-metadata-integrity.md).

A report that many verified PHercParis4 spiral-input patches carry `meta.json`
bounds that no longer contain their valid vertices (most stale in Z) is a
metadata-integrity problem, not a new project: a prefilter on a stale box
silently discards valid geometry. The TIFXYZ audit now classifies the declared
bbox against recomputed bounds, the run guard blocks stale output metadata, and
`scroliq-bbox-census` reproduces the count over any patch pack with a positive
control. The census has not yet been run on the real pack.


## 8. Overnight proof-infrastructure additions

The 2026-10-04 / 2026-10-05 research batch identified several proof-chain
mechanisms that are cheap, deterministic, and directly useful to a final
submission. Their full protocols and self-evaluations are recorded in
[the overnight research ledger](2026-10-04-overnight-research.md).

### 8a. Rendering commutativity certificate

**Status:** INCLUDE as proof infrastructure; implementation is not part of this
docs-only batch.

A deliberately independent reference implementation should reconstruct the
declared TIFXYZ→CT sampling operation and compare it with the production
renderer. Whole-vs-tiled, full-vs-cropped, and equivalent-resampling operations
should satisfy preregistered commutativity tolerances.

The reference renderer must not share the production renderer's sampling code.
An asymmetric synthetic coordinate-encoding volume supplies positive controls
for axis swaps, scale mistakes, crop-origin errors, interpolation mismatches and
tile-boundary defects.

### 8b. Metamorphic submission harness

**Status:** INCLUDE as proof infrastructure.

The pipeline should be tested under scientifically equivalent mutations whose
expected relationships are known without ink ground truth: clean/warm cache,
tile order, batch size, monolithic/tiled execution, lossless rechunking and
physically corrected crop-origin translation.

Each mutation binds its expected invariant, numerical tolerance, artifact
hashes and measured deviation into a machine-readable conformance receipt.

### 8c. Fault-injection CI

**Status:** INCLUDE.

Every important provenance/geometry guard should retain at least one deliberately
corrupted positive control that demonstrates the guard actually fails for the
defect it claims to detect. This extends the repository rule that a clean audit
which checked nothing is vacuous.

### 8d. Human-input ledger

**Status:** INCLUDE as proof infrastructure.

For any bounded human intervention, record the region, alternatives shown,
exact response, wall-clock duration, affected geometry, before/after identities
and cumulative human-input time. The ledger documents activity; it does not
define Challenge policy.

### 8e. Constraint leverage accounting

**Status:** INCLUDE as provenance/prioritization evidence.

Record the physical area/topology downstream of each constraint so that a tiny
manual or generated constraint with large causal reach is visible in review and
can be prioritized for independent validation.

### 8f. Preservation explanation packets

**Status:** INCLUDE as proof infrastructure.

For any blank or physically compromised region, package the CT/TIFXYZ
coordinates, physical support evidence, reviewer-loadable location, hashes and
reason code. The packet supplies evidence; it does not automatically alter
legibility accounting.

### 8g. Material-coordinate distortion overlay

**Status:** INCLUDE as a diagnostic experiment.

Compare UV orientation/shear/reversal with independently estimated physical
fiber directions. This converts a qualitative material-coordinate check into a
reproducible review overlay without using ink.

### Claim boundary

None of these INCLUDE decisions means the implementation already exists. This
batch records that the evidence mechanism is worth implementing when its input
dependencies are available. They remain non-blocking relative to the primary
Grand Prize dependency-order campaign.

The batch also rejects two superficially strict reproducibility rules:
universal bit-for-bit equality and snapshot testing final letter images. Both
can preserve the wrong scientific behavior; physical/metamorphic invariants are
the preferred contract.

## Promotion rule for future proof-chain work

A new provenance mechanism should earn INCLUDE only when all of the following
hold:

- two materially different scientific procedures or artifacts are currently
  indistinguishable under the existing evidence contract;
- that ambiguity can change a Grand Prize claim or held-out ranking;
- the new binding can be deterministic and fail closed;
- task-specific evidence cannot already express the distinction more strongly;
- the change does not create a new manual-review dependency;
- CI can objectively verify it.

Otherwise prefer documentation, adapter-local evidence, or DISMISS.
