#!/usr/bin/env bash
# Download one TIFXYZ mesh to out/large-s3/ (untracked), audit it with the
# row-block scroliq-mesh, record exit code / peak RSS (MB) / seconds in
# runs.tsv, and delete the download. A mesh that cannot be audited is logged
# in failed.tsv with its reason, never dropped.
set -uo pipefail
mesh=${1%/}
BUCKET=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
OUT=artifacts/2026-11-19-large-mesh-audit
scroll=${mesh%%/*}
segment=$(echo "$mesh" | cut -d/ -f3)
name=$(basename "$mesh" .tifxyz)
report="$OUT/reports/$scroll.$segment.$name.json"
[ -s "$report" ] && exit 0
vid=$(echo "$name" | grep -o 'on-[0-9]*' | cut -c4-)
root=$(grep -o "community-uploads/forrest/volcomp/$scroll/volumes/$vid[^ ]*" volumes.txt | head -1 || true)
dir="out/large-s3/$mesh"
mkdir -p "$dir"
for f in meta.json x.tif y.tif z.tif; do
  curl -sS --retry 4 -m 1800 -o "$dir/$f" "$BUCKET/$mesh/$f" \
    || { printf '%s\tdownload %s\n' "$mesh" "$f" >> "$OUT/failed.tsv"; rm -rf "$dir"; exit 0; }
done
args=(--tifxyz "$dir" --out "$report")
[ -n "$root" ] && args+=(--volume-root "$root")
stats=$(python3 "$OUT/peak.py" scroliq-mesh "${args[@]}" 2> "$dir.err" | tail -1)
printf '%s\t%s\n' "$mesh" "$stats" >> "$OUT/runs.tsv"
[ -s "$report" ] || printf '%s\taudit exit %s: %s\n' "$mesh" "${stats%%$'\t'*}" "$(tail -1 "$dir.err")" >> "$OUT/failed.tsv"
rm -rf "$dir" "$dir.err"
