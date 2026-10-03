# ScrolIQ model registry

Community model submissions live here as one JSON model card per model. The
machine contract is `model.schema.json`; `scroliq-eval` also validates the
same fields without requiring a JSON Schema dependency.

A minimal entry:

```json
{
  "schema_version": 1,
  "name": "nader-ink-v2",
  "author": "Youssef Nader",
  "checkpoint_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "training_data": ["PHercParis4-fragments/train-v2"],
  "held_out_excluded": true,
  "inference_script": "models/nader-ink-v2/infer.py",
  "inference_config": {
    "overlap": 0.5,
    "blend_mode": "hann",
    "layer_start": 0,
    "layer_end": 64
  },
  "license": "MIT",
  "tasks": ["ink"],
  "stochastic": true,
  "random_seed": 17,
  "training_run_url": "https://example.org/public-training-run"
}
```

For repository-local checkpoints, add `checkpoint_path`. For large external
checkpoints, CI/evaluators pass the downloaded file with `scroliq-eval
--checkpoint ...`; the bytes must match `checkpoint_sha256`.

## Fail-closed rules

A model is not rank-eligible if the checkpoint cannot be hash-verified, the
inference script is missing, output-affecting `inference_config` is not
hash-bound, the requested task is undeclared, held-out exclusion is not
explicitly true, a declared training-data identifier overlaps
the held-out manifest, a stochastic model lacks a fixed seed, or any expected
evaluation region is failed/missing.

Training-data identifiers should name the narrowest published dataset/split
that was actually used. Generic names such as `Paris4` are too ambiguous for
blind overlap checks.

See `docs/model-evaluation.md` for the evaluator and blind-runner boundary.

## Grand Prize public release chain

The evaluation card above answers “can this model be evaluated safely?” It does
not by itself prove that every Grand Prize training/pseudo-label artifact has
been published under the required terms.

Use `models/release.schema.json` plus `scroliq-model-release` for that
separate release gate. It verifies CC-BY-NC-4.0 datasets, pseudo-label
checkpoint licensing, public training/inference runs, fixed stochastic seeds,
lineage between training datasets and checkpoints, and local artifact hashes.

See `docs/model-release.md`.
