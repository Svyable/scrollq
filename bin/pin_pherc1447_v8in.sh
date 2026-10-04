#!/usr/bin/env bash
set -euo pipefail

out_dir="${1:-out/pherc1447-v8in-pins}"
mkdir -p "$out_dir"

scroliq-hf-pin \
  --repo YoussefMoNader/ink-8um-v8in \
  --repo-type model \
  --revision main \
  --require-file README.md \
  --out "$out_dir/v8in-base.hf-pin.json"

scroliq-hf-pin \
  --repo YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062 \
  --repo-type model \
  --revision main \
  --require-file README.md \
  --out "$out_dir/v8in-pherc1447-loo-w062.hf-pin.json"

scroliq-hf-pin \
  --repo YoussefMoNader/ink-8um-v8-patchpack \
  --repo-type dataset \
  --revision main \
  --require-file README.md \
  --out "$out_dir/v8-patchpack.hf-pin.json"

scroliq-hf-pin \
  --repo YoussefMoNader/ink-8um-pherc1447-surfaces \
  --repo-type dataset \
  --revision main \
  --require-file README.md \
  --out "$out_dir/pherc1447-surfaces.hf-pin.json"

printf 'Pinned four external repositories under %s\n' "$out_dir"
printf 'Inspect inventories, then add --require-file/--require-sha256 for exact campaign artifacts before scoring.\n'
