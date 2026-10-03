#!/usr/bin/env bash
# Run upstream vesuvius.surface_preflight (structure-only) on the same 21
# published TIFXYZ meshes that ../2026-10-01-real-mesh-audit/ audited with
# scroliq-mesh, then join the two results in comparison.json.
#
# Needs numpy, tifffile and imagecodecs (the published x/y/z.tif files are
# LZW-compressed). Meshes are downloaded to out/s3/ (untracked); the pinned
# upstream module is downloaded to out/upstream/ and hash-checked before use.
set -euo pipefail
cd "$(dirname "$0")/../.."
BUCKET=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
OUT=artifacts/2026-10-01-preflight-comparison
MESH=artifacts/2026-10-01-real-mesh-audit
VILLA_COMMIT=078e9eb3410f93f965951334bebca107cbe8dffb
PREFLIGHT_SHA256=862e4f1f78659730bbab43345716e52c3dc8c5c743c97718bd55b6ba2d3bce46
mkdir -p out/upstream "$OUT/preflight"
PF="out/upstream/surface_preflight.$VILLA_COMMIT.py"
[ -s "$PF" ] || curl -sS -m 60 -o "$PF" \
  "https://raw.githubusercontent.com/ScrollPrize/villa/$VILLA_COMMIT/vesuvius/src/vesuvius/surface_preflight.py"
python - "$PF" "$PREFLIGHT_SHA256" <<'EOF'
import hashlib, sys
digest = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
if digest != sys.argv[2]:
    sys.exit(f"upstream module hash mismatch: {digest}")
EOF
while read -r key; do
  mkdir -p "out/s3/$(dirname "$key")"
  [ -s "out/s3/$key" ] || curl -sS -m 120 -o "out/s3/$key" "$BUCKET/$key"
done < "$MESH/keys.txt"
for mesh in $(sed 's#/[^/]*$##' "$MESH/keys.txt" | sort -u); do
  scroll=${mesh%%/*}
  segment=$(echo "$mesh" | cut -d/ -f3)
  # No --volume: the CT bounds and signal-support gates are not run.
  # Exit 2 means a gate failed; the report is still written, so keep going.
  python "$PF" --surface "out/s3/$mesh" \
    --output "$OUT/preflight/$scroll.$segment.json" > /dev/null || true
done
python "$OUT/compare.py"
