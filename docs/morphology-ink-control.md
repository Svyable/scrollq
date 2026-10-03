# Morphology-based ink control

**Status:** source-benchmark gate implemented; target transfer blocked. Set 2026-10-03.

This is a falsification/control path, not a new ink detector. It uses the public
optical-profilometry release accompanying *Ink detection from surface topography
of the Herculaneum papyri* to ask whether simple morphology descriptors show a
papyrus-independent relationship to known ink before ScrolIQ considers analogous
signals on sealed-scroll CT.

Machine-readable source pin:
[`artifacts/2026-10-03-morphology-control/source-pin.json`](../artifacts/2026-10-03-morphology-control/source-pin.json).

## Frozen public source

- Dataset: `scrollprize/profilometer`
- Revision: `a806bead2f3b9100c20e19de37814fb285cfeefd`
- Dataset terms: CC BY-NC 4.0
- Paper: DOI `10.1038/s41598-026-58467-1`
- Paper terms: CC BY-NC-ND 4.0
- Opened-source papyri: PHerc. 248, PHerc. 250, and PHerc. 500P2
- Release size: 14 co-registered regions containing 16 letters

Do not copy or adapt paper figures into ScrolIQ. The paper's no-derivatives
license is more restrictive than the dataset license. ScrolIQ's implementation
must remain independently written from the reported method and use only facts,
measurements, and the separately licensed dataset.

## Critical source discrepancy

At the pinned public revision, the dataset metadata records native lateral
sampling of `0.68793625 µm/pixel` in X/Y, while the manuscript reports
`0.34 µm`. The dataset's 3 September 2026 notice says the discrepancy is under
investigation.

That discrepancy is material because the paper's strongest mechanistic claim is
resolution dependence. ScrolIQ therefore treats the source as **physically
scale-uncertain** until the dataset maintainers publish a resolved value.

Consequences:

- no descriptor threshold expressed in absolute microns;
- no claim that an optical feature scale maps to a CT feature scale;
- no target-volume morphology control on a 2027 Grand Prize scroll yet;
- no use of the paper's resolution-collapse point as a CT cutoff.

The current source benchmark may use only dimensionless, rank-normalized, or
pixel-local descriptors whose interpretation does not require choosing between
the two published lateral-sampling values.

## Stage 1 — source-only benchmark

The first experiment is intentionally small. It does not train a classifier and
does not consume Grand Prize CT.

Freeze a manifest for `scroliq-morphology-control` with:

- source revision and both license-evidence URLs;
- the two conflicting sampling values and
  `discrepancy_status: "unresolved"`;
- a fixed descriptor list;
- `source_split: "leave-one-papyrus-out"`;
- `learned_classifier: false`;
- `source_labels_used_for_target_training: false`;
- missingness-mask and label-permutation controls;
- `uses_absolute_micron_thresholds: false`.

Initial descriptor family:

1. **local-gradient rank** — local change magnitude after per-sample
   normalization;
2. **curvature rank** — local second-order shape response without interpreting
   sign as universal elevation/depression;
3. **fiber-relative roughness** — local texture contrast relative to nearby
   substrate rather than an absolute roughness threshold.

These are deliberately conservative. The paper reports that neither bulk relief
sign nor roughness alone is universal across the three papyri, so ScrolIQ must
not encode "ink is raised", "ink is depressed", or "ink is smoother" as a fixed
rule.

### Required controls

**Leave-one-papyrus-out.** Random pixels or random letters are not an acceptable
generalization test. All samples from one papyrus stay out together.

**Missingness-mask control.** The public source records non-finite profilometry
pixels before inpainting. A descriptor must not win merely by learning where
the instrument failed to reconstruct the surface.

**Label permutation.** The same source-benchmark code must collapse under
permuted ink labels. A descriptor that remains strong after permutation is
capturing a region/sample shortcut, not ink morphology.

The first useful result is not a high within-source score. It is evidence that a
descriptor survives papyrus-level holdout and both controls.

## Stage 2 — target control

`target_control` mode is fail-closed in the current implementation.

It becomes eligible only after:

1. the public profilometry sampling discrepancy is resolved;
2. a Stage-1 source benchmark has been committed and bound by SHA-256;
3. one exact eligible Grand Prize volume is frozen;
4. the target ink manifest and evaluation-region IDs were frozen before any
   morphology-control evaluation;
5. ink predictions, OCR, and attractive renders were not used to choose the
   target regions or tune descriptors.

Even then, the first target test remains a **control**, not an ink model. It
should ask whether regions already selected independently exhibit a physical
response consistent with the source benchmark more often than matched negative
controls.

## CLI

```bash
scroliq-morphology-control \
  --manifest morphology-source-benchmark.json \
  --out morphology-source-benchmark.audit.json
```

Exit codes:

- `0`: provenance/design gate passes;
- `1`: usable but partial evidence, including the current unresolved source
  sampling discrepancy;
- `2`: invalid or leakage-prone design.

Outputs are create-only so a later rerun cannot silently overwrite the
preregistered audit.

## Grand Prize relevance

This path can strengthen only the **ink false-positive / hallucinated-ink
falsification gate**. The 2027 Grand Prize permits public external resources
when their terms allow the intended use, requires train/prediction separation,
and requires reproducibility for trained models. The profilometry dataset's
CC BY-NC 4.0 terms permit this noncommercial research/control experiment, but
those terms must remain attached to derived benchmark artifacts.

A future positive morphology-control result would still not prove that a mark
is ink, that text is legible, or that optical profilometry features are
recoverable from CT. It would add one more independent physical test that a
candidate ink result must survive.
