#!/usr/bin/env bash
# Download one TIFXYZ mesh directory to out/corpus-s3/, audit it, delete the
# download. A mesh whose audit cannot run is recorded in failed.tsv, not dropped.
set -uo pipefail
mesh=${1%/}
BUCKET=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
OUT=artifacts/2026-10-01-corpus-mesh-audit
scroll=${mesh%%/*}
segment=$(echo "$mesh" | cut -d/ -f3)
name=$(basename "$mesh" .tifxyz)
report="$OUT/reports/$scroll.$segment.$name.json"
[ -s "$report" ] && exit 0
vid=$(echo "$name" | grep -o 'on-[0-9]*' | cut -c4-)
root=$(grep -o "community-uploads/forrest/volcomp/$scroll/volumes/$vid[^ ]*" volumes.txt | head -1 || true)
dir="out/corpus-s3/$mesh"
mkdir -p "$dir"
for f in meta.json x.tif y.tif z.tif; do
  curl -sS --retry 4 -m 900 -o "$dir/$f" "$BUCKET/$mesh/$f" \
    || { printf '%s\tdownload %s\n' "$mesh" "$f" >> "$OUT/failed.tsv"; rm -rf "$dir"; exit 0; }
done
args=(--tifxyz "$dir" --out "$report")
[ -n "$root" ] && args+=(--volume-root "$root")
scroliq-mesh "${args[@]}" > /dev/null 2> "$dir.err" \
  || printf '%s\taudit exit %s: %s\n' "$mesh" "$?" "$(tail -1 "$dir.err")" >> "$OUT/failed.tsv"
rm -rf "$dir" "$dir.err"
