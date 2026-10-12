# E8 task-subspace moonshot — synthetic evidence

Date: 2026-10-12 UTC. Base repository commit:
`0f28713b7224dfe899155f2bb81f1b91597baed5`.
Independent MIT implementation by Codex at Sven's request. No raw CT, checkpoint,
competition rasters, external code or prize submission used.

Commands, run in the repository's `.venv` after the documented CI setup:

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/scroliq-e8-moonshot --synthetic --out out/e8-release.json
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/e8_kernel_benchmark.py --out out/e8-kernel.json
```

Both exit 0. Exact source SHA-256 hashes and environment are in `synthetic.json`.
`kernel.json` records the input hash, local CPU timing and exhaustive-oracle check.
Outputs copied here without editing. Re-run to new create-only paths.

## Final comparison

The projection side channel stores original linear-probe scores; it is counted
in the archive size. Every projection arm has zero probe decision flips on every
synthetic group. This does not measure real ink or fault recovery.

| Index bits/channel | Actual float32 compression | E8 MSE reduction vs optimized scalar, isotropic / anisotropic / shifted | Frozen verdict |
| --- | --- | --- | --- |
| 1 | 8.458x | 11.489% / 11.980% / 11.148% | TEST_ON_REAL_DATA |
| 2 | 6.688x | 12.282% / 10.771% / 11.362% | TEST_ON_REAL_DATA |
| 4 | 4.715x | -18.144% / -17.924% / -25.690% | NO_MATERIAL_GAIN |

The four-bit E8 arm is worse than the optimized scalar control. Keep that
negative result. Escape-only protection has less than 1.4x compression in these
cases and fails the fourfold storage gate. No arm claims a prize improvement.

The weak-coordinate control loses 232/512 original decisions without protection;
both escape and projection protection retain all decisions with zero measured
coordinate-score error. The controlled coordinate is not physical ink.

## Kernel check

For 32,768 eight-dimensional vectors, the closed-form root-shell search agrees
with an exhaustive coordinate-distance oracle on every index. Median of three
local CPU runs: 0.0230 seconds vs 0.4522 seconds, a 19.66x ratio. This compares
our geometric finite-shell search to brute force in NumPy; it does not compare
against production quantization kernels or imply faster FFTs/model inference.

## Limits and next gate

Three scenarios share base synthetic randomness, not independent scrolls.
No runtime performance is inferred from storage ratios. AUROC and decisions are
only for the stored, calibration-fitted binary ridge probe. Orthogonal feature
directions, nonlinear heads and neighbor identities are unprotected. If the
scores alone are the product, storing them alone costs less than this codec.

The original scalar max-range experiment was strengthened to calibration-only
clipping optimization. The byte-only rule was expanded to include lower MSE
at essentially equal size. These are disclosed synthetic development decisions;
the final source/rule is frozen before any real-data experiment.

Next evidence is a pinned real scroll-disjoint feature fixture and a frozen
downstream segmentation/rare-signal comparison. See
[the fixture contract and derivation](../../docs/e8-feature-moonshot.md).
