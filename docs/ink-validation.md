# Held-out ink validation

`scroliq-ink-validate` turns the Grand Prize held-out/false-positive requirement into a reproducible artifact.

It deliberately evaluates **ink signal recovery, not reading**. The primary prediction and every falsification control are scored against the same known binary ink labels and validation mask. The report records the model checkpoint digest, input file digests, model window dimensions, split identity, overlap declaration, balanced accuracy, false-positive rate, F1/IoU, probability separation, and a digest of the exact evaluated arrays.

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
  --model-checkpoint-sha256 <64-hex-checkpoint-digest> \
  --model-window 17x256x256 \
  --control normal-plus-3=heldout/normal_plus_3.tif \
  --control normal-minus-3=heldout/normal_minus_3.tif \
  --control adjacent-winding=heldout/adjacent_winding.tif \
  --out submission/ink-validation.json
```

The command exits zero only when the report is suitable as prize evidence: the split is declared held-out, training overlap is explicitly `none`, both ink and background are present in the validation mask, and at least one falsification control was evaluated.

No arbitrary performance cutoff is imposed. The tool reports measurements and control deltas so reviewers can see whether the correct physical surface carries more ink evidence than deliberately wrong surfaces.

## Why the controls matter

A plausible-looking letter is not enough. Useful controls hold the model and ground truth fixed while changing the physical hypothesis:

- shift the sampled surface along its normal;
- sample the adjacent winding;
- perturb the geometry;
- run an independent checkpoint/fold.

A strong result should remain reproducible on held-out known ground truth while signal degrades under physically wrong controls. This is stricter than a pretty render and produces an auditable artifact that can be pinned from the Grand Prize provenance graph.

## Supported arrays

The CLI accepts 2D `.tif`/`.tiff` or `.npy` arrays. Integer predictions must use their declared encoding (`uint8` or `uint16`) or a dtype that `auto` can infer. Floating predictions in `auto` mode must already be in `[0,1]`; out-of-range floats fail rather than being silently rescaled.
