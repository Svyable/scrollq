#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/out/public-fiber-campaign/summary.json}"
FROZEN="$ROOT/artifacts/2026-10-01-public-fiber-audit/summary.json"

mkdir -p "$(dirname "$OUT")"
python "$ROOT/scripts/public_fiber_campaign.py" --out "$OUT"
python "$ROOT/artifacts/2026-10-01-public-fiber-audit/verify.py" "$OUT" "$FROZEN"
