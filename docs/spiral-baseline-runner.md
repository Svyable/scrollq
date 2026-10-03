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


## Official checkpoint -> TIFXYZ receipt

A successful fit receipt is not the end of the bounded reproduction. Run the
pinned Villa checkpoint flattener through the receipt wrapper:

```bash
scroliq-spiral-export \
  --run-dir /runs/pherc0826-bounded-01 \
  --dataset /data/ds0826 \
  --villa-root /src/villa \
  --output /runs/pherc0826-bounded-01.tifxyz \
  --evidence-dir /runs/pherc0826-bounded-01-export
```

This command does **not** implement an exporter. It re-verifies the successful
fit receipt and exact clean Villa checkout, then executes that checkout's
`spiral-fitting/flatten_spiral_checkpoint.py`.

The wrapper explicitly passes `--voxel-size-um 9.362`. This is important:
Villa's generic flattener defaults to 9.6 um, while the frozen PHerc0826 recipe
is 9.362 um. A recipe drift to the generic default fails closed.

The export receipt binds:

- exact Grand Prize volume `20250821151701`;
- final checkpoint bytes and successful fit receipt;
- frozen recipe/preflight and fitted umbilicus bytes;
- Villa commit, Spiral tree, fitter, official flattener, Lasagna service and
  `flatten_fast_nofilter.json` hashes;
- exact official export command, device, chunk size and 9.362 um scale;
- stdout/stderr, host/GPU identity and wall time;
- every output file hash plus a deterministic TIFXYZ tree hash;
- a machine-readable `scroliq-mesh`/TIFXYZ audit.

Exit code zero from Villa is insufficient. The receipt is failed when the
output is missing, malformed, symlinked, or fails the TIFXYZ audit.

This closes execution/provenance for Phase 2 of #126. It does not establish
correct winding identity, full recto coverage, nonlocal self-intersection
freedom, or readable ink; those remain downstream geometry and submission
gates.
