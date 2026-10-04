# PHerc1447 v8-in release pins and byte inventory (2026-10-04)

Step 1 of the frozen protocol in [`docs/pherc1447-v8in-protocol.md`](../../docs/pherc1447-v8in-protocol.md),
for issue #172: resolve the four Hugging Face repositories to immutable commits and hash
the exact bytes of every scoring input. **No ScrolIQ score is read or published here, and
no author-reported metric is promoted.**

Produced by `.github/workflows/pherc1447-v8in-pins.yml` (create-only; the run is the
commit `Freeze PHerc1447 v8-in release pins and byte inventory`). All Hugging Face traffic happened
inside the Actions runner.

## What was frozen

| repository | type | resolved commit | status | files | bytes | Hub-verified SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| `YoussefMoNader/ink-8um-v8in` | model | `d89166b41a3f5fad7749b3d7c0fdd1bd3695d844` | hashed | 35 | 527,564,042 | 2/35 |
| `YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062` | model | `2bf9f421862cda0ed41dcae6e8274c12e295d03a` | hashed | 34 | 334,007,101 | 1/34 |
| `YoussefMoNader/ink-8um-pherc1447-surfaces` | dataset | `7e4d918712a8d8642a6fdeee45b80217c1e98317` | hashed | 107 | 1,887,585,182 | 101/107 |
| `YoussefMoNader/ink-8um-v8-patchpack` | dataset | `d67b1c1548ef93df9e00e804870f89127817f4c5` | skipped_by_policy | 18 | — | — |

The surfaces dataset was pinned at the exact revision the AUC reproduction (#212) scored; the
other three were requested at `main` and resolved to the commits above. After this freeze no
campaign step may use a moving reference.

Across the three downloaded repositories: **176 files, 2,749,156,325 bytes**
hashed, each size-checked against its pin. Where the Hub exposes a Git-LFS SHA-256 the streamed
digest was required to equal it (column above); the remaining 72 files are non-LFS blobs (the largest is 103,185 bytes)
for which the digest in `byte-inventory.json` is ScrolIQ's own. Per-repository
`inventory_sha256` values bind each repository's `(path, size, sha256)` listing.

## Observations (from `byte-inventory.json` and `cross-checks.json`)

- The surfaces inventory reproduces, byte for byte, the eight SHA-256 values the AUC reproduction
  checks (asserted by the workflow). `surfaces_reproduce_pr212_hashes` = `true`.
- The checkpoint SHA-256 declared by that reproduction, `3b94548d7f9ba9f99bc4b0ad8cafcec6d42585c06304e1bd11e47b5d0f88c4cd`,
  **is** the bytes of `model.safetensors` in the base-model repository
  (`base_checkpoint_found_in_ink_8um_v8in` = `true`). It was previously asserted; it is now verified.
- The base and LOO-w062 checkpoints are **different bytes** (`3b94548d7f9ba9f99bc4b0ad8cafcec6d42585c06304e1bd11e47b5d0f88c4cd` vs `4b28e153e0a631679c79b6c9b8e3e159108d75aeddc6fdea648708ffec5026b5`,
  both Hub-verified, both 333,532,180 bytes), so the LOO checkpoint is not the base model re-uploaded.
- The base-model repository also ships `training/r3d50_KM_200ep.safetensors`
  (193,553,596 bytes), a second checkpoint whose
  provenance the model card must account for.
- The surfaces dataset carries the model-input layers for all three windings
  (w058: 24, w060: 24, w062: 24 `layers/*.tif` files) and
  predictions, but **no w062 labels**, so w062 cannot be pixel-scored (unchanged from #212).
- The training corpus is pinned but **not downloaded** (`skipped_by_policy`): it is not a scoring
  input and its largest file, `train_images.npy`, alone is 49,939,021,952 bytes.

## Reproduce

```bash
python scripts/hf_byte_inventory.py \
  --pin artifacts/2026-10-04-pherc1447-v8in-pins/v8in.hf-pin.json \
  --pin artifacts/2026-10-04-pherc1447-v8in-pins/v8in-pherc1447-loo-w062.hf-pin.json \
  --pin artifacts/2026-10-04-pherc1447-v8in-pins/v8-patchpack.hf-pin.json \
  --pin artifacts/2026-10-04-pherc1447-v8in-pins/pherc1447-surfaces.hf-pin.json \
  --skip-download YoussefMoNader/ink-8um-v8-patchpack \
  --max-repo-bytes 4294967296 --out out/byte-inventory.json
```

The output is deterministic and timestamp-free, so it must equal `byte-inventory.json` unless a
Hub repository was rewritten.

## Claim boundary

A pin proves which Hub tree was observed and that the bytes match it. It does not prove the
artifacts are scientifically valid, correctly licensed, free of training/evaluation leakage, or
produced by the declared experiment, and it says nothing about readability.

## Still open for #172

Not done here, and not claimed: normalized model cards and the `scroliq-model-release` report
(they need training-data identities, licenses, seeds and public run URLs from the Hub READMEs);
the zero-shot base-model inference on w058/w060/w062; the layer-order and surface-offset
falsification controls; region/split manifests for `scroliq-eval`; and a dated campaign
directory of validator reports. The pinned `layers/*.tif` mean the inference inputs for the
first and third items exist as immutable bytes; running them is a compute question, not a data one.
