# Surface-normal response falsification

`scroliq-normal-response` is an experimental held-out control for ink
predictions. It asks a physical question that a visually plausible render
cannot answer: does a frozen detector respond most strongly at the submitted
papyrus surface, or does the response persist or peak away from that surface?

This is a falsification artifact, not an ink detector and not a readability
score.

## Frozen v1 protocol

The primary prediction is offset zero. Protocol v1 requires predictions from
the same frozen checkpoint and inference path at exactly these non-zero signed
offsets along the local surface normal:

`-6, -4, -2, +2, +4, +6` voxels.

The tool measures:

- mean ink and background response at every offset;
- center advantage over the strongest non-zero offset;
- the fraction of ink/background pixels with a strict maximum at offset zero;
- unique-peak offset histograms, with ties reported rather than awarded to zero;
- the effect of a conservative center-wins gate on precision, recall, false
  positive rate, and balanced accuracy at the already-declared ink threshold.

Schema v2 also measures **connected predicted components**. Components are
defined once from the nominal prediction using 8-connectivity and then held
fixed across every offset. For each component the report records the mean
probability-vs-depth profile, nominal advantage over the strongest off-surface
mean, peak offset(s), an off-surface persistence ratio, and a coarse
half-nominal support span. Small components can be excluded with
`--min-component-pixels`.

The fixed-support rule matters: offset maps are never re-thresholded or
re-segmented to manufacture apparent persistence. A component is a review
candidate when its nominal-surface mean is **not strictly greater** than every
non-zero-offset mean. That rule creates a falsification queue; it is not a
claim that the component is false ink.

The center-wins gate is fixed: a pixel must already pass the declared ink
threshold and its zero-offset probability must be strictly greater than every
non-zero-offset probability. The tool does not tune a margin from evaluation
data.

## Provenance requirements

A protocol-complete report binds:

- the model checkpoint SHA-256;
- the exact surface geometry SHA-256;
- a frozen sampling-manifest SHA-256;
- the primary, labels, validation mask, and every offset map by SHA-256;
- split identity and the explicit training-overlap declaration.

Optionally provide a level-0 `(H,W,3)` surface-coordinate map with
`--surface-xyz`. The file is SHA-256 bound into the report and gives each
review-candidate component a deterministic physical review point. Those points
can be exported to VC3D without inventing a winding annotation:

```bash
scroliq-vc3d-review \
  --input heldout/normal-response.json \
  --kind normal-response-component \
  --scroll PHercParis4 \
  --out heldout/normal-response.points.json
```

The sampling manifest should record the CT source, geometry identifier,
normal-orientation convention, interpolation/sampling settings, offset
construction, model/inference command, and relevant code revision. The command
hashes the manifest but intentionally does not reinterpret it; the provenance
graph remains responsible for linking the manifest to public/reproducible
inputs.

## Example

```bash
scroliq-normal-response \
  --prediction heldout/prediction.npy \
  --labels heldout/inklabels.tif \
  --validation-mask heldout/validation-mask.tif \
  --normal-offset heldout/n-6.npy@-6 \
  --normal-offset heldout/n-4.npy@-4 \
  --normal-offset heldout/n-2.npy@-2 \
  --normal-offset heldout/n+2.npy@2 \
  --normal-offset heldout/n+4.npy@4 \
  --normal-offset heldout/n+6.npy@6 \
  --prediction-scale unit \
  --threshold 0.5 \
  --split-id public-heldout-fold-3 \
  --held-out \
  --training-overlap none \
  --ground-truth-source-url https://example.org/public-ground-truth \
  --model-checkpoint-sha256 <64-hex> \
  --model-window 17x256x256 \
  --surface-geometry-sha256 <64-hex> \
  --surface-xyz heldout/surface-xyz.npy \
  --min-component-pixels 4 \
  --sampling-manifest heldout/normal-sampling-manifest.json \
  --out heldout/normal-response.json
```

## Interpretation

`experimental_evidence_ready: true` is only a design/provenance completeness
flag. Promotion still requires empirical evidence that held-out true ink is
more sharply and consistently localized than background and hard false
positives across folds or checkpoints.

The kill criterion remains unchanged: if curves are flat, checkpoint-specific,
or equally center-peaked for false positives, wrong surfaces, or adjacent
windings, discard the method rather than tuning it against target-scroll text.

This layer is intentionally independent of the main dependency-order pipeline.
It can be omitted without changing scan-health scoring, geometry reconstruction,
unrolling, or ordinary ink inference.
