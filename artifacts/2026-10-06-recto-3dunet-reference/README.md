# Official recto-surface 3D U-Net — frozen external baseline (registered, unpinned)

**Status 2026-10-06: registered, unpinned, not run.** Frozen once published;
pinning the checkpoint means a new `as_of` and a new dated directory, not an
edit of this one.

[`reference.json`](reference.json) registers the Vesuvius Challenge
`scrollprize/surface_recto_3dunet` checkpoint as a **frozen geometry
baseline**: any future ScrolIQ surface-model claim has to beat it, and its own
previous version, on scroll-disjoint geometry evidence. It does not replace
any predictor. ScrolIQ owns no surface backbone today; it consumes published
prediction volumes.

## What is pinned, and what is not

| item | state | why |
|---|---|---|
| model card revision, checkpoint SHA-256, byte size | **not recorded** | `huggingface.co` is blocked by the build container's egress policy (403), so nothing was downloaded and no hash is guessed |
| architecture, I/O, loss, loader keys, training scrolls, patch counts | **claimed** | read from a web-search snippet of the card only; not checked against the embedded `model_config` |
| epoch 3504 | **claimed** | from the 2026-10-06 maintainer briefing only |
| checkpoint license (MIT) | **not verified** | relayed; `verified: false` |
| training-data terms (CC BY-NC 4.0 tomography) | **not verified** | relayed; recorded **separately** so the checkpoint label is never read as relicensing the scans |
| training ancestry | **scroll level only** | PHerc0139, PHerc1667, PHerc0343P, PHerc0500P2, PHercMANBp; scan IDs and annotated regions unknown, so every volume of these scrolls counts as in-ancestry |

`tests/test_frozen_reference.py` asserts that none of the unpinned fields was
filled in without evidence and that the two licenses stay separate.

## Ancestry against the prize targets

All 13 Grand Prize volumes in `DEFAULT_MANIFEST` (as of 2026-09-30) are
scroll-disjoint from the five training scrolls, by scroll ID. Two conflicts
must be settled before any run:

- **PHerc0343 vs PHerc0343P.** PHerc0343 is a First Letters target; 0343P is
  in the training ancestry. Whether they are one physical object is not
  established here, so PHerc0343 is **not** treated as held-out.
- **PHerc0139.** Most of ScrolIQ's surface campaigns read the published
  `PHerc0139` `surface-recto-090.zarr` prediction. PHerc0139 is a training
  scroll, so no PHerc0139 number is held-out evidence for this checkpoint.

## To finish the pin (needs network access to Hugging Face)

1. Download the checkpoint at a fixed revision; record the revision, SHA-256
   and size.
2. Hash the embedded `model_config` canonically, then check it against the
   claimed architecture/I/O.
3. Read the card's license text and data terms and record evidence URLs
   (`verified: true` only once read).
4. Write a `models/` card (`scroliq-eval` contract) with `training_data`
   naming the narrowest identifiers the card supports and
   `held_out_excluded: true` only against a manifest that excludes all five
   scrolls.
5. Add the checkpoint and its data terms to the third-party notices.

## Smallest experiment once pinned

One eligible, scroll-disjoint volume (not PHerc0343 until resolved). Freeze
and seal the crop set before inference. Run this checkpoint and each
candidate surface source over exactly the same crops with a fixed inference
config. Score only on geometry gates already in the repo: CT support
(`scroliq-prediction-support`), sheet count/separation, sheet switching and
topology (`scroliq-segmentation-validate`, `scroliq-segmentation-uq`),
winding consistency (`scroliq-winding-conservation`), cross-roll impostors
and renderability. Ink never chooses between them.
