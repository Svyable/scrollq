# ScrollQ — train on the best first

**Data-quality triage for Vesuvius scroll volumes.**

ScrollQ samples the actual full-resolution voxels in each volume, scores data
health with a transparent heuristic, and turns the result into an interactive
leaderboard for deciding where segmentation, labeling, and GPU time are most
worth spending first.

**[Open the live ScrollQ dashboard →](https://svyable.github.io/scrollq/)**

> ScrollQ measures **volume data quality**, not papyrus readability. It does
> not detect ink and it does not claim which scroll will be read first.

## What you get

The dashboard is the fastest way to use ScrollQ. It currently combines the
quality scores with open-data coverage so you can inspect both **how healthy a
volume looks** and **how much work has already been done on it**.

- **Sortable leaderboard** — rank volumes by total score or individual score
  components.
- **Live analytics** — mean, median, top-quartile cutoff, unique-scroll count,
  tier mix, and segment coverage update with the current filtered view.
- **Fast filtering** — search by scroll/volume, filter by S/A/B/C tier, show
  zero-label volumes, volumes with segments, or the 🎯 **label next** set.
- **Expandable evidence** — open any row to see the volume root, voxel metrics,
  decoded-chunk count, penalties, and the explanation behind the score.
- **CSV export** — export the current sorted/filtered view for notebooks,
  prioritization sheets, or downstream analysis.
- **Keyboard-friendly controls** — `/` focuses search, `Esc` resets the view,
  and rows can be expanded with Enter/Space.

### Current public corpus snapshot

As of the September 30, 2026 run, the published dashboard contains:

| | |
|---|---:|
| Scored volumes | **64** |
| Distinct scrolls represented | **39** |
| Score range | **27.4–77.4** |
| Top-quartile volumes with zero published ink labels | **16** |
| Strict dead-slice detections | **0** |
| Deterministic resample rank correlation | **ρ = 0.876** |
| Top-10 overlap under resampling | **8 / 10** |

The full **score distribution** is shown at the bottom of the dashboard so the
leaderboard stays primary while the population context remains easy to audit.

## How ScrollQ scores a volume

For each volume, ScrollQ samples full-resolution level 0 and decodes real
volcomp chunks through
[zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit), which
vendors the MIT-licensed libvolcomp decoder.

By default, the scorer requests **4 × 128³ chunks per volume**, spreading shard
candidates per dimension so sampling does not collapse onto an edge line on
non-cubic grids.

Per decoded chunk, ScrollQ measures:

| metric | what it tells you |
|---|---|
| `nonzero_frac` | fraction of voxels carrying signal rather than fill |
| `grad_energy` | local texture / edge energy |
| `dyn_range` | p99 − p1 intensity spread |
| `sat_frac` | fraction clipped at 255 |
| `dead_slices` | strict interior all-zero planes between populated neighbors |

Those measurements are aggregated into a documented heuristic:

| component | contribution |
|---|---:|
| Signal presence | up to **+40** |
| Texture / gradient energy | up to **+30** |
| Dynamic range | up to **+20** |
| Saturation | up to **−25** |
| Dead slices | **−15 each**, capped at **−30** |

The weights are intentionally visible in
[`src/scrollq/score.py`](src/scrollq/score.py). Re-weight them if your use
case calls for it; the important part is that the ranking is reproducible and
its assumptions are inspectable.

## Why the 🎯 “label next” flag exists

ScrollQ can join volume scores to discovered open-data label and surface-volume
coverage.

A volume is flagged **🎯 label next** when it is in the current corpus's
top-quality quartile **and** its scroll has zero published ink-detection labels
in the coverage input.

That is not a claim that the scroll contains more readable text. It is a
practical way to surface high-quality data that appears underrepresented in
the existing label set.

## Reproducibility

The published numbers are backed by dated artifacts in
[`artifacts/`](artifacts/), including the scored volume records and coverage
join used to build the public site.

The repository also contains a deterministic alternate-sample mechanism
(`--rotate` internally) used to test ranking stability. The current published
resample gives **Spearman ρ = 0.876**, mean absolute score change **3.07**, and
**8/10** overlap in the top ten.

Important sampling rules are documented in [`AGENTS.md`](AGENTS.md), including
why:

- shard candidates are spread **per dimension**;
- missing masked-background chunks are not treated as empty data;
- the dead-slice detector requires populated neighbors on both sides; and
- ranking stability, rather than one exact sample, is the quality check.

## Install

Python **3.11+**:

```bash
pip install git+https://github.com/Svyable/scrollq.git
```

For a reproducible development install:

```bash
git clone https://github.com/Svyable/scrollq.git
cd scrollq
python -m pip install -r requirements-ci.txt
python -m pip install -e .
python -m pytest -q
```

## Score volumes

`volumes.txt` contains one `dl.ash2txt.org` volume root per line.

```bash
scrollq-score \
  --volumes volumes.txt \
  --samples 4 \
  --workers 4 \
  --out-dir out/
```

The main machine-readable result is `out/volumes.json`.

## Build the dashboard

Without coverage metadata:

```bash
scrollq-leaderboard \
  --in out/volumes.json \
  --out docs/index.html
```

With label/segment coverage from a zarr-pyramid-audit discovery artifact:

```bash
scrollq-coverage \
  --s3-roots discover_zarr.roots.jsonl \
  --volumes out/volumes.json \
  --out out/coverage.json

scrollq-leaderboard \
  --in out/volumes.json \
  --coverage out/coverage.json \
  --out docs/index.html
```

The generated page is self-contained: no external charting or JavaScript
framework is required.

## Inspect one volume

`scrollq-health` combines ScrollQ's quality score with the companion integrity
audit:

```bash
scrollq-health \
  --root community-uploads/forrest/volcomp/PHerc0009B/volumes/....zarr
```

It produces one combined operational verdict:

**TRAIN / CAUTION / DO NOT TRAIN**

This pairs two different questions:

| tool | question |
|---|---|
| [zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit) | **Is the pyramid structurally trustworthy?** |
| **ScrollQ** | **How healthy does the usable voxel data look?** |

Together: **don't train on lies; train on the best first.**

## Honest scope

ScrollQ is a **triage signal**.

It does **not** detect ink, read text, assess papyrus geometry, measure
flattening quality, or predict which scroll will yield the most legible
characters. A high score means the sampled voxels are healthy under the
published heuristic.

That distinction matters: ScrollQ is intended to improve **resource allocation
and dataset hygiene**, not replace segmentation, ink detection, or held-out
validation.

## Repository map

```text
src/scrollq/
  score.py         scoring + deterministic sampling
  metrics.py       per-chunk voxel metrics
  coverage.py      joins scores to labels / segment coverage
  leaderboard.py   generates the interactive dashboard
  health.py        quality + zarr-pyramid-audit health report
artifacts/          dated evidence behind published results
docs/               GitHub Pages dashboard and writeup
tests/              deterministic test suite
volumes.txt         public volume roots used by the campaign
```

## License

MIT.

Built for the Vesuvius Challenge by Sven + Muse (AI assistant).
