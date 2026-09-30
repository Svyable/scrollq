# ScrollQ

**Train on the best first.**

ScrollQ is an open, reproducible data-quality triage system for the [Vesuvius Challenge](https://scrollprize.org/) scroll volumes. It decodes **real level-0 voxels** from volcomp-sharded Zarr data, measures signal and acquisition quality, and assigns each volume a transparent **0–100 quality score** so scarce segmentation, labeling, and GPU effort can be directed toward the healthiest data first.

**[Live leaderboard](https://svyable.github.io/scrollq/)** · **[September 2026 Progress Prize write-up](https://svyable.github.io/scrollq/september-2026.html)** · **[Reproducible campaign artifacts](artifacts/2026-09-30-scrollq/)**

> ScrollQ is a **triage signal, not a readability claim**. It does not detect ink and it does not predict which scroll will be read first.

## Why this exists

The Vesuvius pipeline has an allocation problem as well as an algorithm problem. Expert segmentation time, labeling effort, and GPU budgets are limited, while scan quality varies substantially across volumes.

ScrollQ makes that hidden variable visible.

Instead of treating every volume as equally promising, it answers three practical questions:

1. **Is the underlying volume structurally trustworthy?**
2. **How healthy are the sampled voxels?**
3. **Where could the next labeling or training hour have the most leverage?**

The result is a public, auditable ranking that can be challenged, re-weighted, or reproduced rather than a black-box recommendation.

## September 2026 evidence snapshot

The repository includes the exact outputs behind the September 30, 2026 campaign in [`artifacts/2026-09-30-scrollq/`](artifacts/2026-09-30-scrollq/).

| Result | Evidence |
|---|---|
| **64 / 64** listed volcomp scroll volumes scored | [`volumes.json`](artifacts/2026-09-30-scrollq/volumes.json) |
| Ranking remained stable under an independent deterministic resample | **Spearman ρ = 0.876**, mean **|Δscore| = 3.07**, top-10 overlap **8 / 10** |
| Acquisition dropout scan found no verified dead slices in the campaign | **0 hits across 64 volumes** |
| Label coverage was highly concentrated in the open-data snapshot | **70 / 70** discovered ink-detection roots were on PHercParis4; the top 12 quality-ranked scrolls had none |
| High-quality, unlabeled targets were made actionable | **16** top-quartile volumes were flagged **“label next”** |

The point is not that one heuristic ranking is final. The point is that **data quality and label coverage can be measured together**, turning an implicit resource-allocation decision into an inspectable one.

## How ScrollQ works

For each volume, ScrollQ samples up to four **128³** chunks from the full-resolution level and decodes them through the real volcomp decoder provided by [zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit), which vendors MIT-licensed `libvolcomp`.

Sampling is deterministic and spread across the three-dimensional shard grid. Masked background is skipped rather than misclassified as bad data, and every result records whether the requested sampling budget was actually achieved.

```text
Vesuvius Zarr volume
        │
        ▼
 shard/index inspection
        │
        ▼
 deterministic L0 chunk sampling
        │
        ▼
 real volcomp decode
        │
        ▼
 voxel-quality metrics
        │
        ├── signal presence
        ├── texture / gradient energy
        ├── dynamic range
        ├── saturation
        └── dead-slice detection
        │
        ▼
 transparent 0–100 score
        │
        ├── leaderboard
        ├── label-coverage join
        └── unified TRAIN / CAUTION / DO NOT TRAIN health report
```

### Metrics

| Metric | What it measures |
|---|---|
| `nonzero_frac` | Fraction of voxels carrying signal rather than fill |
| `grad_energy` | Mean neighbor difference; a texture / edge-energy proxy |
| `dyn_range` | p99 − p1 intensity spread |
| `sat_frac` | Fraction of voxels clipped at 255 |
| `dead_slices` | Zero z-planes surrounded by populated neighbors in dense chunks |

### Score

The current documented heuristic is:

- **40 points** — signal presence
- **30 points** — texture energy
- **20 points** — dynamic range
- minus a saturation penalty
- minus **15 points per verified dead slice**, capped at 30

The calibration and weights are deliberately visible in [`src/scrollq/score.py`](src/scrollq/score.py). They are a judgment call, not ground truth. Re-weight them if you disagree.

## Sampling provenance is part of the result

A quality score should not quietly look authoritative when the requested data could not be read. ScrollQ therefore emits sampling provenance alongside every score:

```json
{
  "requested": 4,
  "decoded": 4,
  "complete": true,
  "rotate": 0,
  "shard_candidates": 27,
  "missing_shards": 0,
  "shard_read_failures": 0
}
```

Missing shards and transport/read failures are tracked separately, and partial sampling is explicitly marked incomplete.

## The data-quality suite

ScrollQ is the prioritization half of a two-part data-quality suite:

- **[zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit)** — integrity: *don’t train on lies*
- **ScrollQ** — quality prioritization: *train on the best first*

`scrollq-health` combines both into one volume-level report:

- **TRAIN** — integrity passes and quality is usable
- **CAUTION** — integrity warns, quality is low, or quality cannot be scored
- **DO NOT TRAIN** — high-severity integrity findings

This creates a practical gate before expensive downstream work begins.

## Quick start

Requires **Python 3.11+**.

```bash
git clone https://github.com/Svyable/scrollq.git
cd scrollq

python -m venv .venv
source .venv/bin/activate

pip install -e .
```

Score the repository’s 64-volume list and build a local leaderboard:

```bash
scrollq-score \
  --volumes volumes.txt \
  --samples 4 \
  --workers 4 \
  --out-dir out/

scrollq-leaderboard \
  --in out/volumes.json \
  --out out/index.html
```

Run one unified integrity + quality report:

```bash
scrollq-health \
  --root community-uploads/forrest/volcomp/PHerc0009B/volumes/....zarr
```

For the tested development setup, install the CI requirements first. They pin the companion decoder/audit dependency to a verified immutable commit:

```bash
pip install -r requirements-ci.txt
pip install -e .
python -m pytest tests/ -q
```

## Label-coverage analysis

ScrollQ can join quality scores with discovered ink-detection and surface-volume roots from the open-data audit:

```bash
scrollq-coverage \
  --s3-roots discover_zarr.roots.jsonl \
  --volumes out/volumes.json \
  --out out/coverage.json

scrollq-leaderboard \
  --in out/volumes.json \
  --coverage out/coverage.json \
  --out out/index.html
```

Volumes in the top quality quartile with no discovered ink labels are flagged **“label next.”** This is intentionally a prioritization cue, not a claim that ink is present.


## 2027 Grand Prize target qualification

`scrollq-grand-prize` narrows the 13 current Grand Prize volumes without
pretending that scan quality predicts readability. It joins the exact
prize-eligible volume IDs to ScrollQ scores and compares candidates on a
**Pareto frontier** over two auditable axes: scan-quality score and the number
of existing public segments. Released surface and lasagna predictions are
treated as bootstrap requirements rather than arbitrary weighted bonuses.

```bash
scrollq-grand-prize \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --out out/grand-prize-targets.json
```

The built-in target manifest is dated **2026-09-30** and links each row back
to its Scroll Prize data-browser page. The matcher uses only the exact
prize-listed volume ID. This is especially important for PHerc1203: its
higher-resolution 2.403 µm scan is recorded as excluded rather than silently
substituted for the eligible 9.362 µm volume.

With the September 30 campaign scores and current public segment counts, the
weight-free frontier contains **PHerc0813** (highest ScrollQ quality among the
seven) and **PHerc1447** (15 existing segments). PHerc0800 remains useful as a
geometry testbed because it has six segments, but it is dominated by PHerc1447
on both current qualifier axes. This is campaign triage only, not an
ink-presence or Grand Prize success prediction.

## Evaluation path

A fast way to inspect the project end to end:

1. Open the **[live leaderboard](https://svyable.github.io/scrollq/)**.
2. Read the **[September Progress Prize write-up](https://svyable.github.io/scrollq/september-2026.html)**.
3. Inspect the frozen **[campaign artifacts](artifacts/2026-09-30-scrollq/)** behind the published numbers.
4. Review the scoring implementation in [`src/scrollq/score.py`](src/scrollq/score.py).
5. Run `scrollq-health` on any supported volume to reproduce the combined integrity/quality verdict.

## Design principles

- **Real voxels, real decoder.** No metadata-only proxy for the quality score.
- **Transparent heuristics.** Every component and weight is exposed.
- **Honest failures.** Partial sampling, missing shards, and read failures are reported.
- **Reproducible evidence.** Published numbers trace to versioned artifacts.
- **Action over vanity metrics.** The output is designed to change what gets labeled, segmented, or trained next.
- **No readability overclaim.** Data health is not ink detection.

## License and authorship

MIT licensed.

Built in September 2026 for the **Vesuvius Challenge September Progress Prize** by **Sven + Muse (AI assistant)**.