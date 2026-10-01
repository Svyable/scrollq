#!/usr/bin/env bash
# Reproduce the 2026-10-01 corpus-wide mesh audit:
#  1. every primary TIFXYZ mesh (<scroll>/segments/<segment>/mesh/<name>.tifxyz/)
#     in the open S3 bucket, audited with scroliq-mesh (~68 GB streamed through
#     out/corpus-s3/, deleted after each audit);
#  2. every published <segment>/mesh/intermediate/*_original.obj, audited with
#     scroliq-obj.
# The volume root is passed only where volumes.txt lists the exact volume ID
# named in the mesh directory ("-on-<volume id>"); otherwise it is omitted.
# Meshes whose audit is killed (exit 137, out of memory) in the parallel pass
# are retried one at a time; failed-pass1.tsv keeps the first pass's log and
# failed.tsv the meshes that still could not be audited.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=artifacts/2026-10-01-corpus-mesh-audit
python3 "$OUT/list_meshes.py" > "$OUT/mesh_dirs.txt"
: > "$OUT/failed.tsv"
xargs -a "$OUT/mesh_dirs.txt" -P "${JOBS:-3}" -n 1 bash "$OUT/audit_one.sh"
cp "$OUT/failed.tsv" "$OUT/failed-pass1.tsv"
: > "$OUT/failed.tsv"
cut -f1 "$OUT/failed-pass1.tsv" | xargs -r -P 1 -n 1 bash "$OUT/audit_one.sh"
python3 "$OUT/obj_keys.py" > "$OUT/obj_keys.txt"
: > "$OUT/obj-failed.tsv"
xargs -a "$OUT/obj_keys.txt" -P 1 -n 1 bash "$OUT/audit_obj_one.sh"
python3 "$OUT/summarize.py"
