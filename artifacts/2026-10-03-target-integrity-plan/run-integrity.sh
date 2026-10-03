#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-out/target-integrity}"
if [[ -e "$OUT" ]] && [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "refusing non-empty output directory: $OUT" >&2
  exit 2
fi
mkdir -p "$OUT"

export AWS_ENDPOINT_URL_S3="${AWS_ENDPOINT_URL_S3:-https://s3.us-east-1.amazonaws.com}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
BASE="s3://vesuvius-challenge-open-data/"

zpa-gate --base "$BASE" \
  --root PHerc0800/volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr \
  --expected-voxel-size-um 8.64 --fail-on high --workers 1 --max-rps 4 \
  --out "$OUT/PHerc0800.zpa-gate.json"

zpa-gate --base "$BASE" \
  --root PHerc0813/volumes/20250821151723-9.362um-1.2m-113keV-masked.zarr \
  --expected-voxel-size-um 9.362 --fail-on high --workers 1 --max-rps 4 \
  --out "$OUT/PHerc0813.zpa-gate.json"

zpa-gate --base "$BASE" \
  --root PHerc1447/volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr \
  --expected-voxel-size-um 8.64 --fail-on high --workers 1 --max-rps 4 \
  --out "$OUT/PHerc1447.zpa-gate.json"
