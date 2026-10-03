# Model evaluation harness

`scroliq-eval` is ScrolIQ's task-neutral evaluation envelope for community
models. It standardizes the parts that should be identical across ink,
geometry, and segmentation evaluation: exact model/data binding, leakage
checks, deterministic uncertainty, failure accounting, and cryptographic
provenance.

It deliberately does **not** replace task metrics. Ink metrics continue to come
from `scroliq-ink-validate`; geometry metrics continue to come from
`scroliq-geometry-validate`; the segmentation adapter will define the
predicted-surface versus held-out-truth metric. Those adapters emit per-region
results using `models/results.schema.json`.

## Contracts

The harness consumes three JSON contracts:

1. A community model card under `models/`, validated against
   `models/model.schema.json`.
2. A held-out dataset manifest, validated against
   `models/dataset.schema.json`.
3. A task-adapter region-results file, validated against
   `models/results.schema.json`.

The held-out manifest names every expected region and the primary metric. It
also declares a `failure_value`. Failed or missing regions receive that value
and remain in the denominator; they are never silently dropped. Any failed or
missing region also makes the model ineligible for ranking.

The final report contains a point estimate, percentile-bootstrap 95% confidence
interval over regions, `n`, explicit failures, a fixed bootstrap seed, and
SHA-256 provenance for the model card, dataset manifest, checkpoint, inference
script, canonical output-affecting inference configuration, results, and
evaluator code.

## CLI

Preflight a model against a held-out set before spending compute:

```bash
scroliq-eval \
  --model models/nader-ink-v2/model.json \
  --dataset /secure/evals/ink-holdout-v1/public-manifest.json \
  --checkpoint /cache/nader-ink-v2.ckpt \
  --root . \
  --check-only \
  --out out/nader-ink-v2.preflight.json
```

Aggregate task-adapter results:

```bash
scroliq-eval \
  --model models/nader-ink-v2/model.json \
  --dataset /secure/evals/ink-holdout-v1/public-manifest.json \
  --checkpoint /cache/nader-ink-v2.ckpt \
  --results out/nader-ink-v2.regions.json \
  --root . \
  --out out/nader-ink-v2.eval.json
```

A ranked report requires every preflight check to pass, the task-adapter result
file to echo the exact verified checkpoint/script/config hashes for the
inference run it scored, and every expected region to return a valid score for
the declared primary metric.

### Inference configuration identity

The model card's `inference_config` object records output-affecting settings
that are not captured by the inference-script or checkpoint hashes. Examples
include patch overlap, blending mode, depth/layer windows, resolution, test-time
augmentation, and other model-specific inference knobs. `scroliq-eval`
canonicalizes this JSON object, records its SHA-256 in the preflight/report
provenance, and fails rank eligibility when the object is absent.

Paths that vary per evaluation region (input, output, checkpoint file location)
should not be encoded here unless they themselves change model behavior.
The goal is to make two materially different inference procedures
cryptographically distinguishable without hard-coding one model family's CLI
into the task-neutral evaluator.

The trusted task adapter must also copy the verified
`checkpoint_sha256`, `inference_script_sha256`, and
`inference_config_sha256` into the result file's `provenance` object.
`scroliq-eval` compares those values to the bytes/configuration verified in
the current evaluation and blocks ranking on a missing or stale identity. This
prevents a result JSON produced under one inference procedure from being
silently scored as though it came from another. It does not by itself prove
that arbitrary prediction files came from that run; runner-to-prediction
artifact binding remains the responsibility of the task adapter.

## Blind evaluation boundary

Private held-out truth must never be exposed to model-submission code. A GitHub
pull request is untrusted input: a malicious inference script could simply
upload labels if the labels are mounted into the same networked job.

The intended CI architecture therefore has two trust domains:

- **Untrusted inference runner.** Validate the PR, verify the checkpoint hash,
  then run the submitted inference code against blind inputs only. The runner
  should be a locked container/VM with no secrets and, for private evaluation,
  no outbound network. Its only durable output is model predictions plus
  provenance.
- **Trusted evaluator.** After the inference process exits, a separate trusted
  job mounts the hidden truth, runs the task-specific validator, emits the
  per-region results contract, and calls `scroliq-eval`. Submission code does
  not execute in this job.

This separation preserves a genuinely blind set while still allowing a
model-author PR to trigger evaluation automatically.

## Leakage rule

`model.training_data` and `dataset.evaluation_data` use exact dataset/split
identifiers. Any intersection blocks ranking. `held_out_excluded: true` is an
additional author attestation, not a substitute for the identifier check.

For stronger protection, community-held private sets should publish immutable
hashes of their public manifests before evaluation and keep a separate private
truth manifest. Region IDs must stay stable across both halves.

## Uncertainty and ranking

ScrolIQ reports the mean primary metric and a deterministic 95% percentile
bootstrap confidence interval over held-out regions. The bootstrap seed is part
of the dataset manifest and is therefore fixed before any model is evaluated.

The future `model-evals.html` page should rank by uncertainty bands rather
than pretending close point estimates are exact. Models whose intervals overlap
should share a rank band unless a preregistered comparison rule says otherwise.

## Adapter roadmap

The next implementation layer is intentionally narrow:

- **Ink:** adapter over `scroliq-ink-validate`, one region score per blind
  label/mask region, preserving falsification-control evidence.
- **Geometry:** adapter over `scroliq-geometry-validate`, with held-out targets
  and missing predictions kept in the denominator.
- **Segmentation:** new held-out surface metric comparing predicted surfaces to
  truth meshes, with explicit topology/coverage failure modes rather than a
  single flattering distance statistic.

Once all three adapters emit the same region-results contract, CI can evaluate
community models without changing the ranking/provenance layer.
