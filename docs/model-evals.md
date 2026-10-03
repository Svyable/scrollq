# ScrolIQ model evaluation harness

`scroliq-eval` is the entry point for a community-model evaluation layer inside
ScrolIQ. The goal is a blind, reproducible evidence harness for ink detection,
geometry, and surface segmentation rather than a winner-takes-all benchmark.

## First implemented slice

The current command is intentionally a **preflight**, not a scorer. It binds and
hashes four things before any model can become rank-eligible:

1. the model registry entry,
2. the exact checkpoint,
3. the exact inference script, and
4. the held-out dataset manifest.

It also checks the held-out dataset and region identifiers against the model's
declared complete training inventory. Any checkpoint mismatch, inference-code
mismatch, declared overlap, unknown overlap, task mismatch, or malformed
manifest blocks evaluation. A passing preflight still reports
`rank_status: not_evaluated`; no model receives a score merely because its
metadata is well formed.

This is deliberate fail-closed behavior. `held_out_excluded: true` is a
declaration, not proof, and does not override an overlap detected from dataset
or region IDs.

Example:

    scroliq-eval \
      --model models/community/example.json \
      --dataset heldout/ink-v1.json \
      --checkpoint checkpoints/example.ckpt \
      --root-dir . \
      --out out/example.preflight.json

The registry schema is `models/schema.json`; the held-out dataset contract is `evals/dataset.schema.json`.

## Model registry contract

Each model entry records the task, checkpoint SHA-256, inference-script
SHA-256, full declared training-dataset inventory, optional exact training
region IDs, a declaration that the inventory is complete, the required
CC-BY-NC-4.0 training-data license, a fixed random seed, and a public experiment
tracking URL. The model's code license is recorded separately.

The current overlap proof is exact-identifier based. It can demonstrate that a
published inventory is internally disjoint from the held-out manifest, but it
cannot detect a model author omitting or aliasing a training source. Future
registry revisions should bind a separately published training-data manifest
and every iterative pseudo-label/checkpoint stage by digest.

## Evaluation report contract

Task adapters will extend the preflight record, not replace it. Every measured
model report should contain:

- one row per held-out region, including failures;
- a point estimate and deterministic 95% percentile-bootstrap interval over
  regions;
- `n`, the bootstrap seed, and the bootstrap sample count;
- failure counts and named failure categories;
- exact checkpoint, inference-code, dataset-manifest, prediction, and scoring
  digests;
- task-specific metrics without collapsing incompatible evidence into one
  opaque score.

The helper `bootstrap_region_ci()` already implements the deterministic
region-level uncertainty contract. Model ordering should later use the same
rank-band principle as the scan leaderboard: overlapping uncertainty is shown
as a band, not a fake precise order.

## Task adapters planned next

**Ink detection.** Reuse `ink_validation.py` per held-out region. Preserve its
falsification controls, training-overlap gate, and signal-recovery framing.
Aggregate region metrics with region-level confidence intervals; do not call
the result reading accuracy.

**Geometry.** Reuse `geometry_validation.py` for frozen held-out point
correspondences and retain failures/missing predictions in the denominator.
Add region-level aggregation without claiming sheet identity or topology.

**Segmentation.** Add a new adapter that compares predicted held-out surfaces to
truth meshes. The metric set should include coverage/completeness and geometric
distance in the exact eligible volume frame, with explicit tolerances and
failure accounting. Do not reduce this to a single IoU-like number until the
surface representation and correspondence rules are frozen.

## Blind held-out execution and CI security

Do **not** expose private held-out truth to arbitrary code from a pull request.
In particular, do not use a privileged `pull_request_target` job that checks
out and executes contributor code.

Use a two-stage protocol instead:

1. Ordinary PR CI validates the public model card, hashes, schema, packaging,
   and reproducibility metadata with no private truth or secrets available.
2. A trusted evaluator takes the immutable PR commit/checkpoint digest and runs
   inference in an isolated container or runner with no repository write token,
   no unrelated secrets, and preferably no outbound network. Only the evaluator
   receives the private held-out inputs. The dataset manifest binds the private
   truth with `truth_commitment_sha256`; a public source URL is optional. The
   evaluator publishes the hashed result, not the truth labels.

This preserves blind evaluation while keeping the "submit by PR" workflow
safe enough for community code.

## Why this belongs in ScrolIQ

The model result becomes another evidence layer attached to the same exact scan
and volume provenance that ScrolIQ already tracks. That avoids a second,
parallel identity system and lets future model-evaluation evidence slot into
passports, Grand Prize provenance, and the site without pretending model
performance and scan health are the same quantity.
