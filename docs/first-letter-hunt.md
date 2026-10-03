# First-letter hunt: evidence-first candidate triage

`scroliq-first-letter-hunt` ranks *where to inspect next* on an unread scroll. It does not recognize letters and does not certify ink. The command exists to stop the most expensive failure mode in First Letters work: promoting a plausible-looking model artifact before checking whether it is tied to the correct physical sheet.

A candidate only enters the `review` queue when all of the following are true:

- at least two primary prediction maps are present and carry two distinct checkpoint SHA-256 values;
- the same 2D window has `-3` and `+3` voxel normal-offset controls;
- adjacent-winding and geometry-perturbation controls are present;
- the median primary above-threshold signal is non-zero (or exceeds a preregistered `--min-primary-signal-fraction`);
- the primary signal fraction is greater than every falsification control by more than the preregistered `--min-localization-margin`.

Among candidates that pass those gates, the queue is deterministic and deliberately weight-free: localization margin first, then cross-checkpoint positive-mask IoU, surface CT-support fraction, majority-consensus signal fraction, and finally candidate ID. There is no opaque "letter score".

## Manifest

Paths are relative to the manifest unless absolute.

```json
{
  "volume_root": "PHerc0490A/volumes/20250521151210-8.640um-1.2m-116keV-masked.zarr",
  "prediction_threshold": 0.5,
  "candidates": [
    {
      "id": "z9274-window-001",
      "bbox_zyx_half_open": [[9274, 1000, 2000], [9338, 1400, 2400]],
      "surface_support_frac": 0.97,
      "primary_predictions": [
        {
          "path": "pred/fold0.npy",
          "checkpoint_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "seed": 0,
          "direction": "forward"
        },
        {
          "path": "pred/fold1.npy",
          "checkpoint_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "seed": 0,
          "direction": "forward"
        }
      ],
      "controls": [
        {"path": "controls/minus3.npy", "kind": "normal_offset", "offset_voxels": -3},
        {"path": "controls/plus3.npy", "kind": "normal_offset", "offset_voxels": 3},
        {"path": "controls/adjacent.npy", "kind": "adjacent_winding"},
        {"path": "controls/perturbed.npy", "kind": "geometry_perturbation"}
      ]
    }
  ]
}
```

Run it with the exact eligible CT root pinned at the command line:

```bash
scroliq-first-letter-hunt hunt.json \
  --expected-volume-root PHerc0490A/volumes/20250521151210-8.640um-1.2m-116keV-masked.zarr \
  --out review-queue.json
```

Every input array is SHA-256 hashed into the report. The tool accepts 2D `.npy`, `.tif`, and `.tiff` predictions, normalizing unit floats, uint8, or uint16 data under the same fail-closed rules used by the held-out ink validator.

## PHerc0490A preregistration

The first campaign target is the exact First Letters volume `20250521151210` at 8.640 µm / 116 keV. The public m7 surface-prediction survey in `axiosdevs/herculaneum-scroll-tools` reports 25.9255% sampled phantom voxels overall. We use that external survey only to choose an axial search band; it is not an ink result and is not evidence that a particular traced surface is seated correctly.

The frozen band-selection rule is:

1. use the survey's exact eligible-volume `per_plane` rows;
2. discard candidate windows intersecting the first or last 1,000 CT slices;
3. consider only contiguous 64-slice windows wholly contained in one measured slab;
4. maximize pooled CT support `1 - sum(phantom) / sum(positives)`;
5. break ties by mean prediction-positive voxels, then lower `z0`.

On the upstream file at Git blob `26d66ccac89a880a73a4bc8a9727097679d014fb`, this selects **z=9274..9337 inclusive** (half-open `[9274, 9338)`): 848,531,539 prediction-positive voxels, 213,573,919 phantom voxels, and pooled CT support **0.7483017316578494**. The frozen derivation receipt lives in `artifacts/2026-10-02-pherc0490a-first-letter-hunt/`.

That only chooses *z*. Within this band, candidate surfaces still have to be grown/seated against CT, audited, rendered, and passed through the controls above. No candidate is called a letter until a human can identify the character letter-by-letter and the physical-control evidence survives.

## Relationship to the other ink tools

Use `scroliq-ink-audit` for declared training/evaluation region separation and required-control provenance. Use `scroliq-ink-validate` on public known-ground-truth data to measure held-out ink recovery and false positives. Use `scroliq-first-letter-hunt` only for ranking unknown-ground-truth windows after inference. These are complementary layers, not substitutes.
