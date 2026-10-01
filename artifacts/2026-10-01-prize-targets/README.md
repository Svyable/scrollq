# Prize target manifests derived from pinned official sources (2026-10-01)

Two questions, answered from machine-readable sources instead of hand-copied
metadata:

1. Does the hand-copied 2027 Grand Prize manifest in
   `src/scrollq/grand_prize.py` still match the Challenge's own data?
2. What does the same qualification look like for the **22 First Letters**
   volumes ($50,000 per scroll, up to 10 scrolls)?

## Pinned inputs

| File | Source | SHA-256 |
|---|---|---|
| `prizeEligibility.json` | `ScrollPrize/villa` @ `56d7c3aeea4bbccf5f56b195ce2a44ea2cf601dd`, `scrollprize.org/src/data/prizeEligibility.json` | `d549d8e8…30a7` |
| `../2026-10-01-bucket-index/metadata.min.json.gz` | the open bucket's `metadata.min.json` fetched 2026-10-01 (see that folder's README) | `127be6e7…065c` (gzip bytes); decoded content `15848845…1b22` |
| `../2026-09-30-scrollq-n24-dense/volumes.json` | existing campaign scores | `9834414714…decd7` |

## Reproduce

```bash
D=artifacts/2026-10-01-prize-targets
I=artifacts/2026-10-01-bucket-index/metadata.min.json.gz
SRC="ScrollPrize/villa@56d7c3aeea4bbccf5f56b195ce2a44ea2cf601dd:scrollprize.org/src/data/prizeEligibility.json"

scroliq-manifest --eligibility $D/prizeEligibility.json --eligibility-source "$SRC" \
  --index $I --prize grand-prize-2027 --as-of 2026-10-01 \
  --out $D/grand-prize-manifest.json --compare-builtin      # exit 0 = no drift

scroliq-manifest --eligibility $D/prizeEligibility.json --eligibility-source "$SRC" \
  --index $I --prize first-letters-2027 --as-of 2026-10-01 \
  --out $D/first-letters-manifest.json

scrollq-grand-prize --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --targets $D/first-letters-manifest.json --out $D/first-letters-targets.json
```

## Findings

**Grand Prize manifest: no drift.** All 13 hand-copied targets agree with the
derived manifest on volume id, voxel size, energy, public segment count, the
released surface and lasagna prediction ids, and the prohibited
higher-resolution scan list (only PHerc1203 has one). This is now a regression
test (`test_builtin_grand_prize_manifest_matches_pinned_official_sources`).

**First Letters: 22 targets, all with a released surface prediction.**

- 12 of the 22 are also Grand Prize volumes; 10 are First-Letters-only
  (PHerc0175A, 0175B, 0306B, 0343, 0483A, 0483B, 0490A, 0490B, 0846A, 0846B).
- Only 13 of 22 have a released lasagna prediction; nine First-Letters-only
  volumes lack one (all but PHerc0343). The Grand Prize qualifier requires both
  predictions (spiral fitting); the First Letters qualifier requires only the
  surface prediction, because the official workflow starts from a segment grown
  on the recto surface prediction. This is a per-prize `required_assets` list,
  not a weighting.
- Only PHerc0800 has public segments (6).
- Two targets have a higher-resolution scan of the same scroll in the bucket:
  PHerc1203 (also a Grand Prize target, where it is a stated prohibition) and
  **PHerc0846A** (2.403 µm, `20260319102732`). The prizes page as pinned does
  not state a prohibition for First Letters; confirm with the organizers before
  using data derived from that scan. No tool in this repository flagged PHerc0846A
  before this derivation.

**How to read the First Letters table.** The scan-health score is a narrow
triage signal with roughly ±5 points of sampling noise
(`artifacts/2026-09-30-resampling-stability/`). The weight-free frontier is
PHerc0813 (76.2) and PHerc0800 (56.9, the only target with segments). Labels
such as "dominated-on-current-evidence" rest on score differences smaller than
that noise: PHerc0813 (76.2), PHerc1203 (74.7) and PHerc0846B (72.0) are one
band. Nothing here predicts readability or ink presence.
