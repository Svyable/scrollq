#!/usr/bin/env bash
# Reproduce the 2026-10-01 real-segment mesh audit.
# Lists every published TIFXYZ mesh for the two Grand Prize targets that have
# public segments (PHerc1447, PHerc0800) in the open S3 bucket, downloads the
# meshes to out/s3/ (untracked), and runs scroliq-mesh on each against the
# exact eligible CT volume root named in the mesh directory ("-on-<volume id>").
set -euo pipefail
cd "$(dirname "$0")/../.."
BUCKET=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
OUT=artifacts/2026-10-01-real-mesh-audit
mkdir -p out/s3 "$OUT/reports"
: > "$OUT/keys.txt"
for scroll in PHerc1447 PHerc0800; do
  token=""
  while :; do
    url="$BUCKET/?list-type=2&prefix=$scroll/segments/"
    [ -n "$token" ] && url="$url&continuation-token=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$token")"
    page=$(curl -sS -m 60 "$url")
    echo "$page" | grep -o '<Key>[^<]*</Key>' | sed 's/<[^>]*>//g' \
      | grep -E '/mesh/[^/]+\.tifxyz/(meta\.json|[xyz]\.tif)$' >> "$OUT/keys.txt" || true
    token=$(echo "$page" | grep -o '<NextContinuationToken>[^<]*' | sed 's/<NextContinuationToken>//' || true)
    [ -z "$token" ] && break
  done
done
sort -o "$OUT/keys.txt" "$OUT/keys.txt"
while read -r key; do
  mkdir -p "out/s3/$(dirname "$key")"
  [ -s "out/s3/$key" ] || curl -sS -m 120 -o "out/s3/$key" "$BUCKET/$key"
done < "$OUT/keys.txt"
for mesh in $(sed 's#/[^/]*$##' "$OUT/keys.txt" | sort -u); do
  scroll=${mesh%%/*}
  segment=$(echo "$mesh" | cut -d/ -f3)
  vid=$(basename "$mesh" | grep -o 'on-[0-9]*' | cut -c4-)
  root=$(grep -o "community-uploads/forrest/volcomp/$scroll/volumes/$vid[^ ]*" volumes.txt | head -1)
  scroliq-mesh --tifxyz "out/s3/$mesh" --volume-root "$root" \
    --out "$OUT/reports/$scroll.$segment.json" > /dev/null
done
python3 "$OUT/summarize.py"
