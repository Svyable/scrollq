#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-out/pherc0490a-first-letter-hunt}"
mkdir -p "$OUT/cutouts"

scroliq-surface-seeds \
  --pred-url https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0490A/representations/predictions/surfaces/20250521151210-surface-20260413222639-surface-m7-L0-th0.2.zarr \
  --ct-url https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0490A/volumes/20250521151210-8.640um-1.2m-116keV-masked.zarr \
  --expected-volume-id 20250521151210 \
  --z-range 9274,9338 \
  --per-dim 12 \
  --prefilter 0 \
  --top-k 12 \
  --min-chunk-distance 1 \
  --threshold 127 \
  --cutout-dir "$OUT/cutouts" \
  --out "$OUT/seed-survey.json"
