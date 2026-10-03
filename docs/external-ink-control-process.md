# External ink-control process — zero-training ink9um ensemble

**Status:** incorporated process; experiment not yet run. Set 2026-10-03. Machine-readable source pin: [`artifacts/2026-10-03-ink9um-control/source-pin.json`](../artifacts/2026-10-03-ink9um-control/source-pin.json).

This process defines how ScrolIQ may use a newly relevant external ink method
without turning a promising model into an unearned ink claim. The first method
admitted to the process is the zero-training checkpoint-soup + z-window
ensemble from `Nieuwlaar/ink9um-dense-native`.

The method is **control-only** until all Grand Prize provenance gates clear.
It does not become the submission ink model merely because it produces
letter-like structure or improves a benchmark.

## Frozen public source

| Item | Frozen identity | Current treatment |
|---|---|---|
| repository | `Nieuwlaar/ink9um-dense-native@217e7521670db49cde97872ea6a8bdfb80c449f1` | INCLUDE FOR EXPERIMENT |
| code license declaration | README front matter: `license: mit` | permitted for this experiment; preserve evidence |
| zero-training checkpoint | `weights/soup42_last4.safetensors` | INCLUDE FOR EXPERIMENT |
| checkpoint SHA-256 | `ab3f1bdefa53733f4d4c46da6c7713c142bc8c703df5098fe8641757d764849c` | must match exactly |
| checkpoint license evidence | `weights/VERIFY.md`: soup and released parents declared MIT | preserve evidence |
| dense-native checkpoint | `d3d95dc41dcb24ed76b84b5e12ca5dae25d7fb34edf1dfbb93e0186f91e6fc6d` | WATCH; not admitted yet |
| Vesuvius data | CC-BY-NC 4.0 unless a specific asset says otherwise | non-commercial / prize-use constraint |

The GitHub mirror does not expose a top-level `LICENSE` file at this pinned
revision. The code repository itself declares MIT in README metadata and the
weight verification document declares the soup/parents MIT. Preserve those
exact public evidence URLs in the experiment manifest rather than silently
upgrading that into a stronger provenance claim.

The Vesuvius Challenge data portal currently states CC-BY-NC 4.0 unless a
specific asset says otherwise. Any experiment must also retain the exact
dataset/scan citation and any asset-specific exception.

## Why the first experiment is zero-training

The repository contains a stronger dense-native pseudo-label result, but that
path creates materially harder Grand Prize provenance obligations. The 2027
rules require training datasets to be public under CC-BY-NC 4.0 and require
every pseudo-labeling dataset/checkpoint stage plus public experiment tracking.

Therefore the first ScrolIQ experiment uses only the frozen soup checkpoint
and inference-time z-window averaging. It creates no new pseudo-label training
stage and cannot use dense-native outputs to choose its evaluation region.

## Gate 0 — freeze the exact prize target and evaluation region

Do not run candidate inference until the Grand Prize target campaign has
already frozen:

1. exact eligible CT volume root;
2. evaluation-region IDs and 3-D half-open bounds;
3. baseline checkpoint and SHA-256;
4. primary positive-evidence metric;
5. negative-control activation metric(s);
6. maximum tolerated loss on held-out positive evidence;
7. minimum required improvement on negative controls;
8. all allowed inference windows and control transforms.

Evaluation-region selection must be independent of candidate probability maps,
renders, OCR, transcription, or candidate legibility.

Record this in the normal `scroliq-ink-audit` manifest and include the new
`external_method` and `selection_contract` objects. A manifest that allows
the candidate to choose its own evaluation region fails.

## Gate A — external-source and rule provenance

For the zero-training control, the manifest should declare at least:

```json
{
  "external_method": {
    "repository": "Nieuwlaar/ink9um-dense-native",
    "revision": "217e7521670db49cde97872ea6a8bdfb80c449f1",
    "code_license": "MIT",
    "checkpoint_license": "MIT",
    "license_evidence": "https://github.com/Nieuwlaar/ink9um-dense-native/blob/217e7521670db49cde97872ea6a8bdfb80c449f1/weights/VERIFY.md",
    "data_license": "CC-BY-NC 4.0",
    "intended_use_permitted": true,
    "grand_prize_role": "control_only",
    "inference_only": true,
    "uses_pseudolabel_training": false
  },
  "selection_contract": {
    "evaluation_regions_frozen_before_candidate_inference": true,
    "ocr_or_legibility_used_for_selection": false,
    "candidate_output_used_to_choose_evaluation_regions": false
  }
}
```

Do **not** assert `experiment_tracking_public=true` until the public tracking
record for the trained source checkpoint lineage has actually been verified.
Until then, `scroliq-ink-audit` should keep the result PARTIAL rather than
promoting it to submission-grade evidence.

A future pseudo-label-trained candidate fails the audit unless the manifest
also proves:

- all training data public;
- training-data license CC-BY-NC 4.0;
- all intermediate checkpoints public;
- intermediate-checkpoint license CC-BY-NC 4.0;
- experiment tracking public.

This is deliberately stricter than trusting a final public checkpoint.

## Gate B — checkpoint and inference identity

Before inference:

1. verify the soup safetensors SHA-256 exactly;
2. record the upstream `villa` revision used for inference;
3. record Python/PyTorch/CUDA and deterministic settings;
4. record every z-window exactly;
5. record the input surface-volume hashes or immutable source identities;
6. fix and record all stochastic seeds.

Do not weight-average across independent seeds. The pinned source reports that
cross-seed weight averaging collapsed to approximately chance on its benchmark.
If multiple seeds are later used, combine predictions only under a separately
preregistered rule.

## Gate C — false-positive controls

Generate the same frozen evaluation output for:

- the existing baseline checkpoint;
- soup checkpoint, center/default window;
- soup checkpoint, preregistered z-window prediction average;
- the same candidate under ScrolIQ's normal-offset controls;
- adjacent-winding control;
- geometry-perturbation control;
- an independent checkpoint/control arm where available.

The external repository's physics tests are incorporated conservatively:

- **CT-void test:** candidate active veto. Measure both pre-veto and post-veto
  results; promotion requires a preregistered reduction in false-positive
  control activation without exceeding the allowed held-out-positive loss.
- **raw-darkness sign:** REPORT ONLY. The pinned source now reports that this
  sign is close to neutral and that applying it as a veto can remove roughly
  half or more of known ink. ScrolIQ must not use it as an active veto.
- **line-pitch:** REPORT ONLY. Low p may support row organization; high p is
  negative evidence, while failure to obtain low p is not proof of no ink.
- **depth-band gate:** WATCH. It is a promising physical discriminator but the
  pinned implementation describes it as a concept rather than a completed
  filter.

No control is allowed to be tuned by looking for attractive letters.

## Gate D — promotion rule

The candidate can strengthen the **ink false-positive/falsification gate** only
after all of the following are true:

1. `scroliq-ink-audit` has no provenance/leakage failure;
2. evaluation regions were frozen before candidate inference;
3. exact checkpoint/source/data identities are preserved;
4. negative-control activation improves by the preregistered amount;
5. held-out positive evidence stays within the preregistered loss tolerance;
6. displaced/adjacent/geometry controls remain visibly negative;
7. the conclusion is unchanged when candidate renders and OCR are hidden from
   the person making the numeric accept/reject decision.

A pass means the method is a useful independent control or candidate ink
producer on that frozen region. It does not prove that visible marks are text,
does not establish whole-scroll readability, and does not substitute for
Grand Prize train/prediction separation.

## WATCH, blocked under current public evidence: dense-native pseudo-label checkpoint

The dense-native checkpoint is not admitted to a prize-relevant ScrollQ run
yet. Its reported held-out performance makes it worth revisiting, but the
pinned `training/REPRODUCE.md` states that the raw training checkpoints are
not in that repository and only the stripped step-16k state dict ships. The
current Grand Prize rules require pseudo-label datasets and checkpoints at
every stage to be public under CC-BY-NC 4.0. I did not verify a separate public
location containing every required intermediate checkpoint or a complete
public tracking record.

That is a provenance blocker, not a claim that the model is technically weak.
If the missing stage artifacts and tracking become publicly verifiable under
the required terms, instantiate a new dated manifest and never reuse the
zero-training experiment's acceptance thresholds automatically.

## Proof gate strengthened

A successful zero-training experiment strengthens:

- ink false-positive / hallucinated-ink mitigation;
- independent-checkpoint evidence;
- source/checkpoint/data provenance;
- train/prediction leakage discipline;
- reproducibility of inference configuration.

It does **not** strengthen surface identity, unrolling coverage, mesh
parameterization, or column legibility by itself.
