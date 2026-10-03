# Held-out ink validation

`scroliq-ink-validate` turns the Grand Prize held-out/false-positive requirement into a reproducible artifact.

It deliberately evaluates **ink signal recovery, not reading**. The primary prediction and every falsification control are scored against the same known binary ink labels and validation mask. The report records the model checkpoint digest, input file digests, model window dimensions, split identity, overlap declaration, balanced accuracy, false-positive rate, F1/IoU, probability separation, threshold-free ROC AUC, and a digest of the exact evaluated arrays. ROC AUC uses deterministic average ranks for tied prediction values, so quantized 8-bit/16-bit maps are scored without arbitrary tie ordering.

## Example

```bash
scroliq-ink-validate \
  --prediction heldout/prediction.tif \
  --labels heldout/inklabels.tif \
  --validation-mask heldout/validation_mask.tif \
  --prediction-scale uint8 \
  --threshold 0.5 \
  --split-id public-kfold-fold-3 \
  --held-out \
  --training-overlap none \
  --ground-truth-source-url https://scrollprize.org/... \
  --label-ancestry independent \
  --label-source-sha256 <64-hex-label-provenance-digest> \
  --model-checkpoint-sha256 <64-hex-checkpoint-digest> \
  --model-window 17x256x256 \
  --control normal-plus-3=heldout/normal_plus_3.tif \
  --control normal-minus-3=heldout/normal_minus_3.tif \
  --control adjacent-winding=heldout/adjacent_winding.tif \
  --out submission/ink-validation.json
```

The command exits zero only when the report is complete enough to pin as prize evidence: the split is declared held-out, training overlap is explicitly `none`, label ancestry is explicitly `independent` of the evaluated model/teacher lineage, both ink and background are present in the validation mask, and at least one falsification control was evaluated. The declaration is not independently proven by this command; `scroliq-provenance` separately checks region-set exclusion.

Pseudo-labels and teacher-derived dense labels remain useful development evidence, but they must be declared `related` (or `unknown` when ancestry cannot be established) when the evaluated checkpoint descends from the same teacher family. Such a report is measured and written normally but fails the prize-evidence gate, preventing circular validation from being promoted to independent proof. `--label-source-sha256` can pin the teacher artifact or provenance record that establishes the ancestry decision.\n\nNo arbitrary performance cutoff is imposed. The tool reports measurements and control deltas so reviewers can see whether the correct physical surface carries more ink evidence than deliberately wrong surfaces.

ROC AUC is reported alongside thresholded metrics rather than replacing them. This matters for cross-scroll and leave-one-region-out model checks where authors publish AUC: ScrolIQ can now reproduce that threshold-independent discrimination measure inside the same hash-pinned artifact while still retaining false-positive rate, balanced accuracy, calibration-sensitive Brier score, and physical falsification controls.

For every control, the report also records `primary_minus_control_roc_auc`. A positive value means the submitted physical surface separates ink from background better than that deliberately wrong control under the same labels and mask; it is evidence about the tested hypothesis, not proof of readable text.

## Why the controls matter

A plausible-looking letter is not enough. Useful controls hold the model and ground truth fixed while changing the physical hypothesis:

- shift the sampled surface along its normal;
- sample the adjacent winding;
- perturb the geometry;
- run an independent checkpoint/fold.

A strong result should remain reproducible on held-out known ground truth while signal degrades under physically wrong controls. This is stricter than a pretty render and produces an auditable artifact that can be hash-pinned from the Grand Prize provenance graph through `held_out_validations[].path` and `held_out_validations[].sha256`.

## Supported arrays

The CLI accepts 2D `.tif`/`.tiff` or `.npy` arrays. Integer predictions must use their declared encoding (`uint8` or `uint16`) or a dtype that `auto` can infer. Floating predictions in `auto` mode must already be in `[0,1]`; out-of-range floats fail rather than being silently rescaled.
