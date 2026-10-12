# E8 features with a protected task subspace

**Status: implemented, synthetic-tested; real CT embeddings unmeasured.**
`scroliq-e8-moonshot` tests a memory moonshot: retain reusable approximate dense
features alongside selected original linear-probe scores, rather than discard
most features when a volume exceeds memory. No segmentation model is modified.

The experiment is motivated by Jacob Sussman's
[E8 Fourier research](https://github.com/jacobalansussman/wht-power-saving-lean)
and [QuIP#](https://proceedings.mlr.press/v235/tseng24a.html). They are distinct
results. Sussman's exact-arithmetic asymptotic construction is not imported or
claimed as a numerical speedup. QuIP# compresses model weights; this independently
written MIT experiment compresses feature rows. It does not reproduce E8P,
QuIP# fine-tuning or their GPU kernels. No external code, weights or data used.
Sven requested the moonshot; Codex implemented and tested this experiment.

## Mechanism

Calibration alone fits channel centering/scaling, a seeded signed eight-channel
Hadamard rotation, and residual-stage radii. Each eight-channel block stores one
byte selecting zero or one of E8's 240 length-squared-two roots. At 1, 2 or 4
stages the indices cost 1, 2 or 4 bits per channel. This finite root shell is not
the whole infinite E8 lattice. There is no trained table of 256 unconstrained
vectors, no padding of dimensions, and no entropy coder.

The root-shell search uses geometry directly. Its best integer root selects the
two largest absolute coordinates; its best half-integer root selects coordinate
signs and repairs parity at the smallest absolute coordinate. Compare those two
candidates with zero. Tests compare it to an independent coordinate-distance
oracle, including ties. The CPU timing only compares these finite-shell kernels.

For frozen independent linear probes W, the projection arm stores s = xW in
float64 and reconstructs

$$\widetilde x = \widehat x + (s-\widehat x W)W^\dagger.$$

In exact arithmetic, W-dagger W = I implies reconstructed probe scores equal
original scores. This is the minimum Euclidean-norm correction to satisfy the
probe equations. Our NumPy implementation casts back to float32, checks every
score and zero-threshold decision at encoding, and escapes to the original row
if numerical error exceeds the tolerance or any decision flips. Rank-deficient
probes are rejected. Tests cover multiple probes. Decoder does not need labels.

The escape-only arm retains original rows without a projection. Both mechanisms
are applied identically to a scalar control, whose clipping ranges minimize
calibration MSE over a fixed 41-point RMS grid. Scalar codes are bit-packed;
E8 codes are uint8. Archive sizes include model parameters, normalization,
weights/dual, side-channel scores, row offsets, escapes and NPZ overhead.

**The protected scores are deliberately stored information.** Preserving them
does not show improved ink detection. If the consumer only needs the existing
probe's scores, store those scores alone. This codec's potential use is retaining
approximate reusable embeddings while preserving selected existing heads. Other
heads, nonlinear segmentation, cosine neighbors, faint physical ink and future
training gradients have no preservation guarantee. More protected heads cost
more bytes and can erase the memory advantage.

## Reproduce

```bash
OPENBLAS_NUM_THREADS=1 scroliq-e8-moonshot --synthetic --out out/e8-new-run.json
OPENBLAS_NUM_THREADS=1 python scripts/e8_kernel_benchmark.py --out out/e8-new-kernel.json
python -m pytest tests/test_e8_codec.py -q
```

Outputs are create-only. Evidence is frozen in
[`artifacts/2026-10-12-e8-feature-moonshot/`](../artifacts/2026-10-12-e8-feature-moonshot/).
No result constitutes a real-data prize gain. The synthetic suite has three
development stress cases, not three independent CT populations: isotropic
features, rescaled anisotropic features, and a shifted evaluation distribution.
They share base randomness. The separate weak-coordinate control tests whether
bulk compression can damage a small discriminating coordinate.

Development deviations: the initial byte-only gate could not recognize lower
distortion at an equal budget, so it was extended to a 10% MSE improvement within
a 2% byte premium. The initial max-range scalar baseline was replaced by
calibration-optimized clipping before the final comparison. These were synthetic
development decisions; there has been no real-data evaluation or blind claim.
The final source, rule, environment and implementation hashes are in the report.

## Real fixture contract

```bash
scroliq-e8-moonshot --fixture frozen-features.npz --out out/e8-real.json
```

NPZ loading disables pickle. Required arrays:

| Key | Shape / meaning |
| --- | --- |
| `embeddings` | N x D, finite float32-representable values; D divisible by 8 |
| `labels` | N binary 0/1 labels for a documented discrimination task |
| `split` | N strings: calibration / evaluation |
| `groups` | N physical specimen identities; calibration/evaluation disjoint |
| `sample_ids` | N unique extraction identities |
| `embedding_training_groups` | Explicit one-dimensional identities; none may overlap evaluation |
| `source_kind` | Scalar string real / synthetic |
| `checkpoint_sha256` | Scalar lowercase SHA-256; real cannot use the zero placeholder |

Codec fitting and the binary ridge probe use calibration rows only. Evaluation
labels are used only for reporting AUROC, recall and false-positive rate; neither
encoding nor the escape/projection rules access them. A checkpoint hash and
declared groups do not independently prove extraction/training lineage. Bind the
fixture to ScrolIQ's existing held-out model-evaluation/provenance evidence before
using its report for a scientific claim. Real inputs remain local and untracked.

The fixed experiment grid includes all methods, rates and protection arms; every
arm is reported. The diagnostic gate requires informative raw probes in every
evaluation group, zero decision flips, bounded probe error, at least 4x actual
compression and either 5% fewer bytes or 10% lower MSE within 2% extra bytes than
matched scalar protection. Synthetic passes mean TEST_ON_REAL_DATA; real passes
mean CANDIDATE_FOR_DOWNSTREAM_VALIDATION. Neither promotes a production model.

Next: freeze real scroll-disjoint embeddings from one pinned checkpoint and
compare reusable-feature discrimination, thin-sheet separation, weak-ink recall
and a frozen downstream segmentation head at matched total memory. For GEMS,
use buffered spatial groups and require a held-out pooled distance-weighted
Tversky comparison after decoding actual fault predictions. The generic codec
does not itself evaluate the GEMS metric. Stop if the scalar control wins, the
side channel consumes the gain, or downstream rare-signal recovery falls.
