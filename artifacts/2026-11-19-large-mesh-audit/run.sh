#!/usr/bin/env bash
# Audit the 60 meshes the 2026-10-01 corpus audit could not (out of memory),
# one at a time, with the row-block scroliq-mesh. Then prove equivalence with
# the unblocked code on a real-mesh sample and summarize.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=artifacts/2026-11-19-large-mesh-audit
cut -f1 artifacts/2026-10-01-corpus-mesh-audit/failed.tsv > "$OUT/meshes.txt"
: > "$OUT/failed.tsv"
: > "$OUT/runs.tsv"
xargs -a "$OUT/meshes.txt" -P 1 -n 1 bash "$OUT/audit_one.sh"
python3 "$OUT/select_sample.py" > "$OUT/equivalence_sample.txt"
python3 "$OUT/verify_equivalence.py"
python3 "$OUT/summarize.py"
