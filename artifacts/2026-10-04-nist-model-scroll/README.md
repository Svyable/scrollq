# NIST synthetic carbonized scroll — evaluation-only blind benchmark

**Status 2026-10-04: registered, unpinned, not run.** Frozen once published; pinning
the acquisition or sealing the truth means a new `as_of` and a new dated directory,
not an edit of this one.

[`benchmark-manifest.json`](benchmark-manifest.json) registers a physically
manufactured, written, rolled and carbonized papyrus scroll as an
**evaluation-only** physical control. It is not training data. Both truth items
(the known text and the leaded-letter locations) are `sealed_truth` and
`training_eligible: false`. The mechanism is documented in
[`docs/blind-control.md`](../../docs/blind-control.md).

## What is pinned, and what is not

| item | state | why |
|---|---|---|
| DOI, landing URL | **not recorded** | the NIST hosts could not be reached from the build container (egress policy returned 403 on `data.nist.gov` and `doi.org`), so no identifier was read from the source and none is guessed |
| license | **not verified** | the manifest carries the *statement relayed in the maintainer briefing* (NIST open-data license for the data, CC0 for the paper) with `verified: false` and no evidence URL |
| acquired-bytes inventory | **not recorded** | nothing was downloaded; the 620 TIFF slices / 32-bit / 130 µm isotropic figures are `volume.claimed`, sourced to the briefing, and unchecked against any file |
| sealed-truth commitment | **not recorded** | no truth bytes are held |

`scroliq-blind-control validate --manifest benchmark-manifest.json` accepts this
manifest as well-formed and reports `pin_status: unpinned`;
`--require-pinned` exits non-zero, and `commit` / `seal` refuse until the pins exist.
`tests/test_blind_control.py` asserts that none of these four items was filled in
without evidence.

## To finish the pin (needs network access to the source)

1. Download the volume. Read the catalog entry and the license text.
2. `scroliq-blind-control inventory --root <download> --out inventory.json`.
3. Write a new dated manifest with the DOI, landing URL, license evidence URL
   (`verified: true` only once the text was read), and the inventory's
   `file_count`, `total_bytes` and `tree_sha256`.
4. Compare the inventory against any checksums the source publishes.
5. Add the dataset to `THIRD_PARTY_NOTICES.md` with its verified terms.

## Same-run triage record (recorded, not implemented)

These dispositions come from the 2026-10-04 maintainer briefing. None of the
repositories or papers could be re-read from this container, so license
statements are relayed, not verified here.

| item | disposition | recorded reason |
|---|---|---|
| NIST synthetic carbonized-scroll CT | **INCLUDE, evaluation-only** | public CT of a specimen whose text predates scanning; lead ink gives real absorption contrast; near-zero training-leakage risk if kept evaluation-only |
| CSWinUNETR (MICCAI 2026) | **WATCH** | no explicit software license found in the surfaced repository, so ScrolIQ neither vendors nor derives from it; if a license appears, run an architecture-only A/B on identical licensed Vesuvius cubes, augmentations, optimizer and held-out ROIs, judged on surface coverage, adjacent-winding bridges, Betti/component error and sheet-switch count; risk: gap-bridging may join neighbouring windings |
| FaCT-GS (ECCV 2026) | **DISMISS** for the prize pipeline | the top-level license excludes `fact_gs/r2_gaussian` and submodule contents, and ScrolIQ holds reconstructed volumes rather than the raw acquisitions it targets, so it would add a learned stage upstream of weak carbon-ink evidence |
| CSRCT | **DISMISS** | aimed at clinical low-dose CT, evaluated on simulated data, article restricted-access, no permissively licensed implementation found |

Why the control matters, as relayed: the official 2026 ink-label documentation
states that unopened-scroll ink masks have no infrared ground truth and are
refined with model pseudo-labels, so a further pseudo-label-derived accuracy gain
is intrinsically less informative than a specimen whose writing was known before
it entered the scanner.

## Claim limits

Success on this volume is **not** validation of carbon-ink detection on ancient
papyrus and is not evidence that any Herculaneum model works. See the
`claim_limits` in the manifest; they are copied into every report and passport
stage.
