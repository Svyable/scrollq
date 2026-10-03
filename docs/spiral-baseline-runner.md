# Controlled Spiral baseline runner

`scroliq-spiral-run` is the execution boundary for the frozen PHerc0826
bring-up campaign. It does not implement Spiral or fork reconstruction code.
It launches the pinned official `ScrollPrize/villa` `fit_spiral.py` only
after the dataset and checkout pass fail-closed checks.

## Prepare without using GPU time

```bash
scroliq-spiral-run \
  --dataset /data/ds0826 \
  --recipe artifacts/2026-10-03-spiral-baseline-target/pherc0826_baseline_recipe.json \
  --villa-root /src/villa \
  --run-dir /runs/pherc0826-bounded-01 \
  --cache-dir /data/vc3d-spiral-cache \
  --prepare-only
```

Preparation requires a passing `scroliq-spiral-preflight`, a clean villa
checkout at exactly `recipe.software.villa_commit`, the official fitter,
an executable Python, and a new run directory. The clean-tree rule prevents a
locally edited fitter from masquerading as the pinned official revision.

## Run

Use the same command without `--prepare-only`. The launcher sets the canonical
preregistered `FIT_SPIRAL_CONFIG_OVERRIDES`, pins `FIT_SPIRAL_RUN_DIR`, and
streams stdout/stderr while recording both logs.

The run directory receives exact recipe/preflight copies, official villa
outputs, logs, and `spiral-run.receipt.json`. The receipt binds the eligible
volume, recipe/preflight hashes, villa commit and `spiral-fitting` tree SHA,
fitter hash, Python identity, safe environment, GPU identity, UTC timing,
log hashes, final checkpoint hash, and an inventory of official fit outputs.

Exit code zero alone is insufficient: the receipt is failed if
`checkpoint_fitted.ckpt` is missing. Failed runs still retain logs/receipts.

After a successful bounded reproduction, use the pinned villa
`flatten_spiral_checkpoint.py` path for checkpoint-to-TIFXYZ export; do not
replace it with a ScrolIQ-specific exporter.
