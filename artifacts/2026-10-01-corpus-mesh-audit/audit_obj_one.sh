#!/usr/bin/env bash
# Download one *_original.obj, audit it with scroliq-obj, delete the download.
set -uo pipefail
key=$1
BUCKET=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
OUT=artifacts/2026-10-01-corpus-mesh-audit
scroll=${key%%/*}
segment=$(echo "$key" | cut -d/ -f3)
report="$OUT/obj-reports/$scroll.$segment.json"
[ -s "$report" ] && exit 0
tmp="out/corpus-obj/$scroll.$segment.obj"
mkdir -p out/corpus-obj
curl -sS --retry 4 -m 900 -o "$tmp" "$BUCKET/$key" \
  || { printf '%s\tdownload\n' "$key" >> "$OUT/obj-failed.tsv"; rm -f "$tmp"; exit 0; }
scroliq-obj --obj "$tmp" --out "$report" > /dev/null 2> "$tmp.err"
rc=$?
[ -s "$report" ] || printf '%s\taudit exit %s: %s\n' "$key" "$rc" "$(tail -1 "$tmp.err")" >> "$OUT/obj-failed.tsv"
rm -f "$tmp" "$tmp.err"
