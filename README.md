# ScrolIQ

**Find the bottleneck. Fix the bottleneck. Read the scroll.**

ScrolIQ is an open, reproducible diagnostic layer for the [Vesuvius Challenge](https://scrollprize.org/) virtual-unwrapping pipeline. The existing `scrollq` package measures **real level-0 CT voxels** and keeps its current commands for compatibility, but the project is expanding beyond a single volume-quality ranking toward evidence-backed diagnostics for the Challenge's published [2026 Open Problems](https://scrollprize.org/2026_open_problems): scan degradation, surface topology, mesh connectivity, fibers, winding annotations, spiral fitting, label quality, ink reliability, and data-scale reproducibility.

**[Live scan-quality survey](https://svyable.github.io/scrollq/)** · **[Open-problems alignment](docs/open-problems-alignment.md)** · **[September 2026 Progress Prize write-up](https://svyable.github.io/scrollq/september-2026.html)** · **[Reproducible campaign artifacts](artifacts/2026-09-30-scrollq/)**

> The existing 0–100 ScrollQ score is a **scan-health triage signal, not a readability or Grand Prize readiness score**. ScrolIQ treats unmeasured downstream stages as unknown rather than inferring them from CT quality.

## Diagnostic passport

The first ScrolIQ interface organizes the evidence for one volume around the Challenge's actual pipeline bottlenecks:

```bash
scroliq-passport \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --coverage artifacts/2026-09-30-scrollq/coverage.json \
  --winding-audit out/PHerc0813.winding-audit.json \
  --root PHerc0813 \
  --out out/PHerc0813.passport.json
```

Today the passport can directly populate data-access/decode provenance, sampled scan-health evidence, label/segment coverage, and a volume-bound winding-input audit. Surface, mesh, fiber, winding geometry, spiral, label-localization, and ink-reliability fields stay explicitly `unknown` or `partial` until direct diagnostics are supplied. That is the contract: **measure the limiting stage; never manufacture confidence for missing evidence.**

The implementation roadmap is mapped directly to the Challenge's open problems in [`docs/open-problems-alignment.md`](docs/open-problems-alignment.md).


## Spatial scan diagnostics

The Challenge notes that scan quality is local: usable and severely degraded regions can coexist inside one volume. `scroliq-scan-map` therefore preserves spatial provenance instead of collapsing every observation into the legacy volume score.

```bash
scroliq-scan-map \
  --root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr \
  --grid 3 \
  --chunks-per-shard 1 \
  --out out/PHerc0813.scan-map.json
```

The report records sampled shard coordinates, level-0 voxel bounding boxes, decoded-chunk metrics, metric distributions, and explicit states for missing shards, sparse/background shards, read failures, and decode failures. It deliberately emits **no aggregate readability or readiness score**.

A matching map can be attached to a passport:

```bash
scroliq-passport \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --root PHerc0813 \
  --scan-map out/PHerc0813.scan-map.json \
  --out out/PHerc0813.passport.json
```

The passport rejects a spatial artifact whose volume root does not exactly match the selected volume.


## Winding annotation audit

`scroliq-winding` audits the conventional VC3D / spiral-fitting point-collection inputs before they are trusted as geometry evidence:

```bash
scroliq-winding \
  --dataset /path/to/spiral-dataset \
  --volume-root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr \
  --z-range 10500,11500 \
  --z-bins 10 \
  --out out/PHerc0813.winding-audit.json
```

It checks `abs_winding.json`, `relative_windings.json`, and `same_windings.json` against the PointCollections v1 shape used by VC3D and the spiral fitter. The report records exact SHA-256 provenance, collection and point counts, XYZ coordinate sanity, role-consistent `wind_a` semantics, winding spans, and machine-readable findings. Missing roles are reported as partial evidence rather than silently treated as failure; `--require-role` can make a role mandatory for a particular experiment.

When the artifact will be attached to a passport, `--volume-root` binds it to the exact CT root; the passport rejects unbound or mismatched winding artifacts. When a fit/evaluation z-window is supplied, ScrolIQ also reports **annotation-center axial coverage**: one median-z center per collection, the largest gap between collection centers, and empty equal-width z bands. Counting collections rather than raw points prevents a densely sampled line from looking like broad coverage. Empty bins are prioritization cues for where another verified constraint may have leverage; they do **not** make the audit fail or prove that a nonempty bin is geometrically constrained.

This is intentionally a **constraint-input audit, not a geometry verdict**. It does not yet establish CT support, patch attachment, relative-winding graph consistency, loop holonomy, or held-out spiral-fit accuracy. Those are the next Winding IQ / Spiral IQ layers.

## Why this exists

The Vesuvius pipeline has an allocation problem as well as an algorithm problem. Expert segmentation time, labeling effort, and GPU budgets are limited, while scan quality varies substantially across volumes.

ScrollQ makes that hidden variable visible.

Instead of treating every volume as equally promising, it answers three practical questions:

1. **Is the underlying volume structurally trustworthy?**
2. **How healthy are the sampled voxels?**
3. **Where could the next labeling or training hour have the most leverage?**

The result is a public, auditable ranking that can be challenged, re-weighted, or reproduced rather than a black-box recommendation.

## September 2026 evidence snapshot

The repository includes the exact outputs behind the September 30, 2026 campaign in [`artifacts/2026-09-30-scrollq-n24-dense/`](artifacts/2026-09-30-scrollq-n24-dense/) (24 samples/volume from a 5×5×5=125 candidate grid; supersedes the 12-sample `artifacts/2026-09-30-scrollq-n12/` and the 4-sample `artifacts/2026-09-30-scrollq/`).

| Result | Evidence |
|---|---|
| **64 / 64** listed volcomp scroll volumes scored | [`volumes.json`](artifacts/2026-09-30-scrollq-n24-dense/volumes.json) |
| Ranking is **representative**, honest about heterogeneity | Disjoint resample ([`stability-n24-dense.json`](artifacts/2026-09-30-resampling-stability/stability-n24-dense.json)): **Spearman ρ = 0.79**, mean **|Δscore| = 4.2**, top-10 overlap **7 / 10** — below our ρ ≥ 0.85 gate, because volumes are genuinely heterogeneous (swings up to 44 points between runs). We publish it because a representative ranking (mean 22.9 chunks decoded/volume) with honest uncertainty beats the earlier 3×3×3 ranking whose ρ = 0.99 we proved was inflated by shard re-reading. |
| Acquisition dropout scan found no verified dead slices in the campaign | **0 hits across 64 volumes** |
| Label coverage was highly concentrated in the open-data snapshot | **70 / 70** discovered ink-detection roots were on PHercParis4; the top quality-ranked scrolls had none |
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
  "requested": 12,
  "decoded": 12,
  "complete": true,
  "rotate": 0,
  "spread": 3,
  "shard_candidates": 27,
  "missing_shards": 0,
  "shard_read_failures": 0
}
```

Missing shards and transport/read failures are tracked separately, and partial sampling is explicitly marked incomplete.

The `spread` parameter controls the per-dimension shard-candidate count (`spread³` candidates; default 3 → 27). A denser spread (e.g., 5 → 125) finds more present shards on sparse volumes — PHerc0813 goes from 2 to 12 decoded chunks — but costs more candidate probes. Denser is not automatically better: our diagnostic showed that when different shards are actually read, heterogeneous volumes produce noisier scores, so choose the spread that matches how much of the volume you need to cover.

## The data-quality suite

ScrollQ is the prioritization half of a two-part data-quality suite:

- **[zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit)** — integrity: *don’t train on lies*
- **ScrollQ** — quality prioritization: *train on the best first*

`scrollq-health` combines both into one volume-level report:

- **TRAIN** — integrity passes and quality is usable
- **CAUTION** — integrity warns, quality is low, or quality cannot be scored
- **DO NOT TRAIN** — high-severity integrity findings

This creates a practical gate before expensive downstream work begins.

Both verdict paths are proven against live data
(`artifacts/2026-09-30-health-verdicts/`): **TRAIN** on the healthy PHerc0813
dl volume (integrity PASS, quality 76.2); **DO NOT TRAIN** on the defective
PHerc0814 S3 pyramid (6 high-severity integrity findings — quality honestly
unscorable, verdict from the audit alone).

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
  --samples 12 \
  --workers 8 \
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
13) and **PHerc1447** (15 existing segments). PHerc0800 remains useful as a
geometry testbed because it has six segments, but it is dominated by PHerc1447
on both current qualifier axes. This is campaign triage only, not an
ink-presence or Grand Prize success prediction.

An optional sensitivity pass can add externally measured **surface-prediction
CT support** without changing the primary ScrollQ score or frontier:

```bash
scrollq-grand-prize \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --surface-support artifacts/2026-09-30-grand-prize-qualifier/surface_support_external.json \
  --out out/grand-prize-targets-with-support.json
```

The imported evidence is pinned to the source file SHA for every scroll and
fails closed unless the recorded CT URL contains the exact prize volume ID.
That guard intentionally excludes the published PHerc1203 support survey
because it used the same scroll's 2.403 µm scan rather than the eligible
9.362 µm volume. PHerc0125 and PHerc1218 are also excluded from this
sensitivity pass because their salvaged survey records do not retain a CT URL.

Among the ten targets with exact-volume imported support evidence, the
three-axis frontier is **PHerc0191, PHerc0211, PHerc0268, PHerc0800,
PHerc0813, and PHerc1447**. The larger frontier is a useful warning: this
external geometry proxy creates real trade-offs and should drive focused
held-out geometry tests, not an opaque weighted winner score.

## 2027 Grand Prize provenance gate

`scroliq-provenance` turns submission eligibility evidence into a machine-checkable graph instead of a last-minute manual checklist. Schema v2 pins the exact eligible CT volume and zarr-pyramid-audit run, then links each surface → numbered tifxyz mesh → render → checkpoint → training datasets/regions → stochastic seeds → public training/inference experiment runs → public held-out validation against known ground truth.

```bash
scroliq-provenance \
  --manifest submission/provenance.json \
  --root-dir submission \
  --format github \
  --out submission/provenance.validation.json
```

The gate fails closed on wrong-volume lineage, training/prediction overlap, non-public or incorrectly licensed training data, prohibited higher-resolution same-scroll training sources, missing stochastic seeds or experiment runs, missing public held-out validation, same-volume training/validation overlap, broken mesh/render column traceability, package SHA mismatches, missing 1 cm scale-bar declarations, and incomplete banner coverage. It also records a canonical graph SHA-256, emits a complete provenance chain for every submitted render, and records held-out exclusion proofs. It deliberately does not set a performance threshold or claim papyrological legibility.

See [the provenance-manifest specification](docs/grand-prize-provenance.md) and [example manifest](examples/grand-prize-provenance.example.json).

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