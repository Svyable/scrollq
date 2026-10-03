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
