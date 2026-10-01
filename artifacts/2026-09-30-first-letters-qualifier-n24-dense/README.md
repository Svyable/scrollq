# First Letters target qualifier — 2026-09-30 (n24-dense)

ScrolIQ triage over the 22 First Letters scans listed at
<https://scrollprize.org/prizes#first-letters-prizes> on 2026-09-30.

## Reproduce

```bash
scrollq-grand-prize --prize first-letters \
  --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --out targets.json
for run in run0 run1; do
  scrollq-grand-prize --prize first-letters \
    --volumes artifacts/2026-09-30-resampling-stability/stability-n24-dense-prov.json \
    --run $run --out targets_$run.json
done
python bin/subset_stability.py targets_run0.json targets_run1.json stability.json
```

`targets.json` (published scores) and `targets_run0.json` are identical on
every target row; `targets_run1.json` is the disjoint resample (rotate 13).

## Method

The Grand Prize qualifier's weight-free Pareto frontier over ScrolIQ
scan-quality score × existing public segment count, with one change: each
prize manifest declares its required bootstrap assets. First Letters requires
only a surface prediction on the exact eligible scan, which all 22 have.
Lasagna predictions are recorded but not required: 13 of 22 have one, and
requiring it would silently drop nine eligible scrolls.

Metadata: the 12 scrolls shared with the Grand Prize reuse that manifest;
the ten First-Letters-only scrolls (0175A, 0175B, 0306B, 0343, 0483A, 0483B,
0490A, 0490B, 0846A, 0846B) were read from their Scroll Prize data-browser
pages on 2026-09-30. All ten have zero public segments; only PHerc0343 lists
a lasagna prediction.

## Result (`stability.json`)

| | run0 (published) | run1 (disjoint resample) |
|---|---|---|
| Pareto frontier | PHerc0800, PHerc0813 | PHerc0800, PHerc1545 |

- Frontier in both runs: **PHerc0800** only, because it is the only eligible
  scroll with existing segments (6). Its scan quality is mid-pack
  (56.9 / 56.4).
- Rank agreement across the 22 scans: Spearman **ρ = 0.7211**, mean
  |Δscore| 7.15, max |Δscore| 27.4, top-5 overlap 3/5. This is below the
  project's ρ ≥ 0.85 gate, so the quality leader is a band, not a scroll.
- PHerc1545 moves from 65.6 to 79.7 between runs; PHerc0826 from 37.2 to
  64.6. Treat single-run quality orderings among these 22 as unreliable.

An earlier draft of this qualifier used the superseded 4-sample campaign
and reported PHerc0846A as a close third. On the n24-dense scores
PHerc0846A is mid-pack (64.6 / 61.6); that claim is withdrawn.

## Exact-scan guards

PHerc0846A and PHerc1203 each have a second, 2.403 µm scan. Only the
prize-listed scan is compared; the other is recorded as excluded. The
qualifier never substitutes it.

This is campaign triage, not a readability, ink-presence or First Letters
success prediction.
