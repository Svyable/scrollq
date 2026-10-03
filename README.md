# ScrolIQ

**Find the bottleneck. Fix the bottleneck. Read the scroll.**

ScrolIQ is an open, reproducible diagnostic layer for the [Vesuvius Challenge](https://scrollprize.org/) virtual-unwrapping pipeline. The existing `scrollq` package measures **real level-0 CT voxels** and keeps its current commands for compatibility, but the project is expanding beyond a single volume-quality ranking toward evidence-backed diagnostics for the Challenge's published [2026 Open Problems](https://scrollprize.org/2026_open_problems): scan degradation, surface topology, mesh connectivity, fibers, winding annotations, spiral fitting, label quality, ink reliability, and data-scale reproducibility.

**[Live scan-quality survey](https://svyable.github.io/scrollq/)** · **[2027 Grand Prize readiness](https://svyable.github.io/scrollq/grand-prize-readiness.html)** · **[Open-problems alignment](docs/open-problems-alignment.md)** · **[September 2026 Progress Prize write-up](https://svyable.github.io/scrollq/september-2026.html)** · **[October 2026 update](https://svyable.github.io/scrollq/october-2026-update.html)** · **[October 2026 goals](https://svyable.github.io/scrollq/october-2026.html)** · **[Reproducible campaign artifacts](artifacts/2026-09-30-scrollq/)**

> The existing 0–100 ScrolIQ score is a **scan-health triage signal, not a readability or Grand Prize readiness score**. ScrolIQ treats unmeasured downstream stages as unknown rather than inferring them from CT quality.

## What ScrolIQ adds

ScrolIQ does **not** replace the community's geometry, winding, scan-quality, data-integrity, or ink-validation tools. Its strongest claim is the layer between them: **make their evidence composable and submission-grade**. Every result should be bound to the exact CT / mesh / model / evaluation region it measures; cross-volume or stale evidence is excluded; leakage and missing evidence fail closed; and a failed control remains a published failure instead of silently becoming confidence.

That distinction matters because the public ecosystem already contains strong prior art such as [TIFXYZ Doctor](https://github.com/aviad12g/tifxyz-doctor), [tifxyz-repair](https://github.com/Nieuwlaar/tifxyz-repair), [windcheck](https://github.com/joe-carr-data/windcheck), [spiralcheck](https://github.com/Nicodol/spiralcheck), [scroll-data-audit](https://github.com/Bullo27/scroll-data-audit), and [gp13-ink-detectability](https://github.com/flummoxjr/gp13-ink-detectability). ScrolIQ's differentiation is the **provenance/falsification contract across those stages**, plus derived campaigns that measure where the contract holds and where it fails.

The next milestone is therefore intentionally narrow: **one exact 2027 Grand Prize volume, one held-out surface/fit/ink improvement, one evidence passport that makes the result independently checkable.** See the [Grand Prize proof campaign](docs/grand-prize-proof-campaign.md).


## Diagnostic passport

**Held-out geometry evaluation:** `scroliq-geometry-validate` compares a frozen
point set with fit predictions, checks declared fit-input exclusion, and keeps
missing predictions in the denominator. See the [O3 evaluator guide](docs/heldout-geometry-evaluation.md).
Native spiral-fit export and real-fit validation remain outstanding.

The first ScrolIQ interface organizes the evidence for one volume around the Challenge's actual pipeline bottlenecks:

```bash
scroliq-passport \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --coverage artifacts/2026-09-30-scrollq/coverage.json \
  --winding-audit out/PHerc0813.winding-audit.json \
  --mesh-audit out/PHerc0813.mesh-audit.json \
  --fiber-audit out/PHerc0813.fiber-audit.json \
  --ink-audit out/PHerc0813.ink-audit.json \
  --root PHerc0813 \
  --out out/PHerc0813.passport.json
```

Today the passport can directly populate data-access/decode provenance, sampled scan-health evidence, label/segment coverage, volume-bound winding inputs, native TIFXYZ mesh evidence, volume-bound Fiber IQ, and ink-validation provenance. Surface support, physical fiber/sheet identity, winding geometry, spiral-fit accuracy, label localization, and biological ink identity stay explicitly `unknown` or `partial` until direct diagnostics are supplied. That is the contract: **measure the limiting stage; never manufacture confidence for missing evidence.**

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

### Umbilicus ray-order review queue

When the dataset contains the spiral fitter's `umbilicus.json` (or `--umbilicus PATH` is given), `scroliq-winding` also checks annotated winding numbers against the scroll axis **before any GPU fit is run**. Along a ray leaving the umbilicus, a sheet two or more windings further out should be crossed after the inner one. For every pair of annotated points in the same frame — all absolute-winding points share one frame; each relative-winding collection is its own frame — that lies in the same angular sector (`--ray-sector-degrees`, default 10) and z band (`--ray-z-tolerance`, default 64 voxels) with a winding difference of at least `--ray-min-winding-gap` (default and minimum 2), the higher-numbered point must not be closer to the axis. The two-winding minimum makes the test independent of where the winding number increments (the fitter's theta=0 branch cut), which can shift any comparison by at most one.

The report's `ray_order` section records the umbilicus and input SHA-256s, every parameter, comparable-pair and inversion counts per frame, the largest radial inversions, and a **review queue** ranking points by how many comparable neighbours they disagree with — an isolated mis-numbered annotation surfaces as one point at the head of the queue, with VC3D XYZ coordinates. Inversions are warnings and passport review actions, never errors: a strongly folded region can legitimately make a ray cross windings out of order. A malformed or explicitly named but missing umbilicus fails closed.

**First real run — PHercParis4 `spiral-input`** ([`artifacts/2026-10-01-paris4-winding-ray-order/`](artifacts/2026-10-01-paris4-winding-ray-order/), workflow `paris4-winding-ray-order.yml`; input SHA-256s in the reports). Of 2,232 annotated absolute/relative points, 2,166 (97%) have at least one comparable neighbour. **2 of 13,700** comparable pairs are inverted, both by under 0.1 voxel (0.071 and 0.041) between points about 60 voxels apart along the sheet — below hand-placement precision, so this dataset shows no meaningful ray-order violation. The near-total agreement also checks the coordinate conventions: a wrong axis or swapped XYZ order would invert roughly half the pairs.

**Can it catch errors on that geometry? Injection control.** [`bin/ray_order_control.py`](bin/ray_order_control.py) mis-numbers one real point at a time by ±s (200 points per shift, seed 0; the 4 already-flagged points excluded) and reruns the check on otherwise unmodified data:

| shift | detected | corrupted point ranked first | median rank |
|---|---:|---:|---:|
| ±2 | 0 / 191 testable (9 untestable) | — | — |
| ±3 | 179 / 200 (89.5%) | 19% | 4 |
| ±5 | 171 / 200 (85.5%) | 88% | 1 |

The ±2 row is a **limit of the design, not a tuning miss**: with the minimum compared gap of 2, a shifted point can only invert against a neighbour whose true winding lies strictly between its old and new label, which needs |s| ≥ 3 (`tests/test_ray_order_control.py` pins this). At ±3 the corrupted point and its one inverted partner are often indistinguishable, hence the lower rank-1 share. Absolute points are only 5 of each 200-point sample, too few for a role-specific figure. The ranking was not tuned on this control.

What it does not establish: patch attachment, CT support, relative-winding graph holonomy across collections, ±1/±2 errors, or held-out spiral-fit accuracy. Those remain the next Winding IQ / Spiral IQ layers.

## Fiber IQ: native VC3D + trace continuity audit

`scroliq-fiber` now reads the community's native VC3D `vc3d_fiber` JSON
versions 1, 3, and 4 as well as the original ordered CSV
`trace_id,x,y,z` interchange format. Native JSON is schema-checked against
the current persisted control-point/span contract, SHA-256 pinned, and
summarized by interpolation goal/mode, native-trace versus fallback spans,
meeting-error ratios, failure codes, and v4 span tags.

The rendered line geometry is independently checked for *gaps* (a step longer
than `--gap-factor`, default 4, times that trace's median step) and *sharp
turns* (a direction change above `--turn-degrees`, default 60). Native JSON
also checks whether persisted control points stay near the rendered line and
progress through it in the same order. The distance test is normalized by that
fiber's own median rendered step (`--control-line-factor`, default 4), avoiding
an absolute voxel-scale assumption.

```bash
# Native VC3D fiber
scroliq-fiber fiber.json --volume-root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr --out fiber-audit.json

# Existing CSV interchange
scroliq-fiber traces.csv --out traces-audit.json

# Optional CI/unwrapping gate for review findings
scroliq-fiber fiber.json --volume-root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr --fail-on-findings --out fiber-audit.json
```

Fallback interpolation is evidence, not automatically a defect: it is reported
separately and does not by itself create a geometry finding. Parse/schema
errors fail closed; geometry findings remain advisory unless
`--fail-on-findings` is requested. See
[`docs/fiber-audit.md`](docs/fiber-audit.md).

The implementation has regression coverage for v1/v3/v4, schema drift,
provenance, fallback accounting, geometry findings and CLI gating, plus a
[frozen public-data campaign](artifacts/2026-10-01-public-fiber-audit/) over
eight PHercParis4 VC3D fibers (53,828 rendered points, 369 spans). The pinned
run found 11 gap candidates and 26 sharp-turn candidates, with zero
control-line offsets or order inversions; 354/369 spans used native tracing and
15/369 used fallback interpolation. These are review signals, not proof of a
sheet switch. The public dataset directory is not asserted to name one exact CT
volume, so that campaign is deliberately **not** passport evidence. Reports
produced with an exact `--volume-root` can be carried by
`scroliq-passport --fiber-audit ...` as partial Fiber IQ evidence while still
refusing to infer physical fiber or sheet identity.

## Mesh IQ: native TIFXYZ audit

`scroliq-mesh` audits one native Vesuvius TIFXYZ surface without rewriting it:

```bash
scroliq-mesh \
  --tifxyz /path/to/surface.tifxyz \
  --volume-root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr \
  --selfcross-report out/PHerc0813.selfcross.json \
  --review-points out/PHerc0813.review-points.json \
  --out out/PHerc0813.mesh-audit.json

# Optional CI gate: review findings become a non-zero exit.
scroliq-mesh --tifxyz /path/to/surface.tifxyz --out out/PHerc0813.mesh-audit.json --fail-on-findings
```

The audit follows the upstream TIFXYZ contract: `x.tif`, `y.tif`, `z.tif`, `meta.json`, reciprocal `scale`, the `Z <= 0` validity convention, and integer-multiple `mask.tif` semantics. It records exact file hashes and checks malformed/empty grids, disconnected valid-vertex components, enclosed invalid-grid components, stale metadata bounding boxes, scale-versus-measured spacing, abrupt local edge jumps, severe neighboring-normal reversals, symmetric quad-area distortion, and per-triangle Jacobian singular values for local isometry. **Isometry is normalized by the observed median 3D step in each parameter direction by default; `meta.scale` is not assumed to be a physical edge-length contract.** When a physical spacing contract is known, pass both `--expected-spacing-x` and `--expected-spacing-y`; this makes absolute anisotropic stretch/compression detectable instead of normalizing it away.



The calibration is independently regression-tested against TIFXYZ Doctor's pinned public real-data benchmark. On the exact same **1,818,055 SHA-256-verified bytes**, the frozen 2026-10-02 campaign agrees **10/10 on enclosed-hole presence** and **10/10 on single-component presence**, including **7/7** hole-presence agreement on the PHerc0800 + PHerc1447 Grand Prize overlap. The first run exposed the old `meta.scale` isometry false positive; after the fix, all 10 Doctor-below-threshold cases have no Mesh IQ isometry finding, and the Villa-control p95 stretch values nearly coincide. See [the same-byte cross-validation artifact](artifacts/2026-10-02-doctor-same-byte/). Benchmark roles are provenance labels, not geometry ground truth.

### Binding external mesh evidence without laundering provenance

`scroliq-evidence-bind` composes third-party mesh evidence with a ScrolIQ
TIFXYZ audit only after checking identity:

```bash
scroliq-evidence-bind \
  --mesh-audit mesh-audit.json \
  --windcheck-index windcheck-index.json \
  --segment <segment-id> \
  --scroll <scroll-id> \
  --volume-id <exact-volume-id> \
  --windcheck-commit <pinned-commit> \
  --out external-mesh-dossier.json
```

The binding class is explicit. Full x/y/z + mask SHA-256 agreement without an
external `meta.json` hash is **coordinate-exact**, not semantic-exact.
Cross-volume evidence, content-hash mismatches, and unsupported external
schemas are excluded. If Windcheck's census was run on a repaired base, the
dossier may bind the published original through `original_hashes`, but the
derived-base census is not imported as a measurement of that original.

The frozen [PHerc0139 cross-tool dossier](artifacts/2026-10-02-cross-tool-mesh-dossier/)
demonstrates the useful case: ScrolIQ and Windcheck independently bind the same
published coordinate bytes for segment `20260306000001-w051_2026030600`.
Mesh IQ reports 15 edge jumps and 173 severe neighbouring-normal reversals;
Windcheck's same-original census reports 3,333 transverse contacts. The
passport accepts this as content-bound external evidence while still asking for
the official VC3D self-cross validator before downstream use.

For local review, `--review-points` emits native VC3D PointCollections with the strongest edge-jump and neighbouring-normal-reversal sites ranked in the audit JSON. The frozen [PHerc0139 review-queue campaign](artifacts/2026-10-02-pherc0139-review-queue/) produces 35 directly loadable points (15/15 edge jumps plus the top 20/173 normal reversals) on the same public surface used by the binding-aware Windcheck dossier. These coordinates are inspection targets, not defect verdicts.

For nonlocal self-intersections, ScrolIQ does not duplicate VC3D's geometry kernel. Generate a deterministic upstream report with `vc_tifxyz_selfcross <surface.tifxyz> -o report.json --collection sites.json` and pass it with `--selfcross-report`. ScrolIQ validates the report against the exact local surface path and grid, blocks on transverse contacts, preserves coplanar/grazing contacts as non-crossings, and keeps a nominally clean census partial when upstream skipped long-edge quads under `maxedge`. The optional `sites.json` remains directly loadable in VC3D for inspection.

By default, review findings remain advisory (`partial`, exit 0); `--fail-on-findings` keeps that evidence status but exits 2 whenever findings are present, allowing an explicit CI/pipeline geometry gate.\n\nA passing audit is deliberately **partial Mesh IQ**, not a proof that the traced sheet is correct. With a fully clean validated self-cross census it establishes freedom from the specific non-adjacent transverse contacts tested by VC3D under the recorded parameters; it still does not establish CT support or correct sheet/winding identity.

### Triangle meshes (Wavefront OBJ)

`scroliq-obj` applies the same audit to a triangle mesh, such as the `*_original.obj` files published next to each segment in the open bucket:

```bash
scroliq-obj --obj /path/to/segment_original.obj --out out/segment.obj-audit.json

# Optional CI gate: review findings become a non-zero exit.
scroliq-obj --obj /path/to/segment_original.obj --out out/segment.obj-audit.json --fail-on-findings
```

It accepts `v`, `vt` and `f` records (`v`, `v/vt`, `v/vt/vn`, `v//vn`, negative indices; polygons are fan-triangulated). With no grid, adjacency comes from shared edges, so the report covers edge-connected components, interior boundary loops (holes), edge jumps against the median edge length, and neighbouring-normal reversals. It also covers defects only a free-form mesh can have: non-manifold edges, inconsistent face winding (kept separate from real folds), and zero-area faces. When faces carry texture coordinates, it measures per-triangle UV-to-3D Jacobian singular values (UVs rescaled by one global factor) and counts folded-over UV triangles; without UVs, isometry stays `unknown`. An OBJ with no faces fails rather than passing. By default, review findings remain advisory (`partial`, exit 0) so exploratory audits are non-disruptive; `--fail-on-findings` preserves the JSON status but exits 2 when any finding is present, making the same diagnostic usable as an explicit CI/pipeline quality gate.

## Ink IQ: leakage and falsification-evidence audit

`scroliq-ink-audit` validates an experiment manifest before ink output is treated as evidence:

```bash
scroliq-ink-audit \
  --manifest experiment/ink-evidence.json \
  --volume-root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr \
  --normal-offsets=-3,0,3 \
  --out out/PHerc0813.ink-audit.json
```

The manifest declares exact checkpoint identity and SHA-256, seeds, half-open ZYX training/evaluation boxes, held-out split names, per-evaluation run provenance, and falsification controls. The audit fails on declared train/evaluation spatial overlap or malformed provenance, and stays partial when controls such as normal offsets, adjacent winding, geometry perturbation, or an independent checkpoint are missing.

This is an **evidence-quality audit, not an ink classifier**. A pass means the declared experiment is spatially separated and the requested controls are present; it does not prove that a prediction is ink or that it generalizes across scrolls.

### Held-out ink measurement

`scroliq-ink-validate` complements that manifest audit with deterministic measurements over explicit 2D NPY/TIFF predictions, known binary labels, and a held-out mask. It reports confusion counts, balanced accuracy, false-positive rate, F1/IoU, probability separation, exact input hashes, and same-mask deltas for named falsification controls. The resulting JSON can be hash-pinned as a `held_out_validations[]` artifact in the Grand Prize provenance manifest.

The command fails closed when the mask is empty or single-class, inputs are malformed, the split is not declared held out, training overlap is not declared absent, or no falsification control is supplied. Those checks make the output an auditable evidence artifact; they do not prove that a URL is public, independently establish the declared train/validation split, set a performance threshold, or claim readability. See the [held-out ink protocol](docs/ink-validation.md).

## How ScrolIQ compares with existing tools

ScrolIQ reads the community's tool outputs and checks them against the exact data they claim to describe; where a tool already does a job, ScrolIQ consumes its report instead of reimplementing it.

| Job | Existing tool or practice | What ScrolIQ adds |
|---|---|---|
| Non-local self-intersection of a TIFXYZ surface | VC3D `vc_tifxyz_selfcross` | Validates the report against the exact surface and grid; adds local checks (components, holes, edge jumps, folds, Jacobian isometry) |
| CT support of a surface | Villa `vesuvius.surface_preflight` | Binds the report to the exact volume root and surface; a report from another scan of the same scroll fails |
| Finding broken segments | Opening segments one at a time in a viewer | One command over every published mesh in TIFXYZ and OBJ, with a dated flag list ([corpus audit](artifacts/2026-10-01-corpus-mesh-audit/README.md): 77 of 307 segments flagged) |
| Zarr store integrity | Noticing errors downstream | `scrollq-health` runs zarr-pyramid-audit before any quality verdict |
| Choosing the next volume to label or train on | We found no published per-volume scan comparison | Scan-health survey of all 64 volcomp volumes with sampling provenance and a weight-free Grand Prize frontier |

[Usage by format](docs/usage-by-format.md) maps each community format to the command that reads it.

## Why this exists

The Vesuvius pipeline has an allocation problem as well as an algorithm problem. Expert segmentation time, labeling effort, and GPU budgets are limited, while scan quality varies substantially across volumes.

ScrolIQ makes that hidden variable visible.

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
| Ranking is **representative**, honest about heterogeneity | Truly-disjoint resample ([`stability-truly-disjoint.json`](artifacts/2026-10-01-truly-disjoint/stability-truly-disjoint.json)): **Spearman ρ = 0.63**, mean **|Δscore| = 8.0**, top-10 overlap **4 / 10** — below our ρ ≥ 0.85 gate, because volumes are genuinely heterogeneous (swings up to 44 points between runs). Two-phase exclusion protocol guarantees 64/64 zero chunk overlap. We publish it because a representative ranking (mean 22.9 chunks decoded/volume) with honest uncertainty beats the earlier 3×3×3 ranking whose ρ = 0.99 we proved was inflated by shard re-reading. |
| Pre-registered stability v2 (balanced, interleaved sample) | **FAIL**: Spearman ρ = **0.750** on 48 eligible volumes (gate 0.85), so the leaderboard shows **rank bands**. The design removed the sampling shift (+5.46 → +0.25) and Pearson r is 0.911, but close volumes still swap ranks. September scores differ from the v2 pooled score by **6.9** points on average — [`2026-10-stability-v2/`](artifacts/2026-10-stability-v2/) |
| Acquisition dropout scan found no verified dead slices in the campaign | **0 hits across 64 volumes** |
| Label coverage was highly concentrated in the open-data snapshot | **70 / 70** discovered ink-detection roots were on PHercParis4; the top quality-ranked scrolls had none |
| High-quality, unlabeled targets were made actionable | **14** top-quartile volumes were flagged **“label next”** |
| First Letters targets are a band, not a winner | All **22** scans qualified; only **PHerc0800** is on the frontier in both disjoint resample runs (subset ρ = **0.7211**) — [`first-letters-qualifier-n24-dense/`](artifacts/2026-09-30-first-letters-qualifier-n24-dense/) |
| Exact-scan surface-prediction CT support reproduces an independent survey | **15 / 18** external values inside the native 95% interval, mean \|Δ\| **0.043**; first exact-scan numbers for 4 scans; a same-scroll higher-resolution survey overstated PHerc1203 by ~0.24 — [`first-letters-support/`](artifacts/2026-09-30-first-letters-support/) |
| Open-bucket chunk integrity | **1** mismatched level in 65 volumes (PHerc0343P L0: 555 / 8,543 objects); **0** in the 23 prize volumes (4,228,772 objects) — [`bucket-chunk-audit/`](artifacts/2026-10-01-bucket-chunk-audit/) |
| Scan metrics vs documented protocol quality (pre-registered) | **Negative**: `otsu_eta` reverses in 3/4 registered pairs, `edge_sharpness` in 2/4 — do not compare scores across scans of one scroll — [`protocol-pairs/`](artifacts/2026-10-01-protocol-pairs/) |
| Hand-entered prize manifests match official sources | Grand Prize **13 / 13**, First Letters **22 / 22** — [`prize-targets/`](artifacts/2026-10-01-prize-targets/), `tests/test_prize_manifest.py` |
| Published PHercParis4 winding annotations are radially consistent | **2 / 13,700** comparable pairs inverted around the umbilicus, both sub-voxel; injection control catches **179 / 200** ±3 and **171 / 200** ±5 single-point mis-numberings (±2 undetectable by design) — [`paris4-winding-ray-order/`](artifacts/2026-10-01-paris4-winding-ray-order/) |
| Fiber IQ runs on public VC3D fibers | **8** SHA-256-pinned PHercParis4 fibers (53,828 points): **11** gap and **26** sharp-turn review candidates, **0** control-line offsets / order inversions; subset, not passport evidence — [`public-fiber-audit/`](artifacts/2026-10-01-public-fiber-audit/) |
| `scrollq-health` fails closed on missing integrity evidence | A non-existent root is **DO NOT TRAIN** (integrity UNKNOWN); the three published live verdicts are unchanged — [`health-verdicts-fail-closed/`](artifacts/2026-10-01-health-verdicts-fail-closed/) |

The point is not that one heuristic ranking is final. The point is that **data quality and label coverage can be measured together**, turning an implicit resource-allocation decision into an inspectable one.

## How ScrolIQ works

For each volume, ScrolIQ samples up to four **128³** chunks from the full-resolution level and decodes them through the real volcomp decoder provided by [zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit), which vendors MIT-licensed `libvolcomp`.

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

New score results identify this exact formula as `scan-health-v1`. Its strict
dead-slice detector is unchanged, but the aggregation has an important sampling
property: continuous metrics are averaged while detected dead slices are
summed. The network-free [controlled sensitivity analysis](artifacts/2026-10-01-dead-slice-sensitivity/README.md)
shows that the dead-slice penalty therefore depends on decoded sample budget.
It records the limitation without changing the frozen score or leaderboard;
any replacement policy needs a separately pre-registered stability analysis.

## Sampling provenance is part of the result

A quality score should not quietly look authoritative when the requested data could not be read. ScrolIQ therefore emits sampling provenance alongside every score:

```json
{
  "requested": 12,
  "decoded": 12,
  "complete": true,
  "rotate": 0,
  "spread": 3,
  "shard_candidates": 27,
  "missing_shards": 0,
  "shard_read_failures": 0,
  "shard_index_invalid": 0,
  "chunk_read_failures": 0,
  "chunk_decode_failures": 0
}
```

Missing shards and transport/read failures are tracked separately, and partial sampling is explicitly marked incomplete. Failures below the shard level are counted too: a structurally invalid shard index (`shard_index_invalid`), a failed chunk range read (`chunk_read_failures`), and a chunk the decoder rejected or whose shape cannot be interpreted (`chunk_decode_failures`). `complete: true` only means the sampling budget was met, so check these counters before treating a score as failure-free. Artifacts produced before these counters existed simply lack the keys; they were not re-run and their scores are unaffected.

The `spread` parameter controls the per-dimension shard-candidate count (`spread³` candidates; default 3 → 27). A denser spread (e.g., 5 → 125) finds more present shards on sparse volumes — PHerc0813 goes from 2 to 12 decoded chunks — but costs more candidate probes. Denser is not automatically better: our diagnostic showed that when different shards are actually read, heterogeneous volumes produce noisier scores, so choose the spread that matches how much of the volume you need to cover.

**Candidate order matters as much as spread.** Sampling takes shard candidates in order until it has enough chunks, and the default order (used by every published campaign, and kept so those scores reproduce) is x-major: the first `spread²` candidates share one x plane. A 24-chunk sample can therefore describe one or two slabs of a scroll. `score_volume(..., order="balanced")` orders the same lattice so every prefix spreads through the volume, and `part=(2, 0)` / `part=(2, 1)` split it into two interleaved, shard-disjoint halves whose chunks are disjoint by construction. Both options are recorded in `sampling` when used. The pre-registered October stability test ([`docs/stability-v2-protocol.md`](docs/stability-v2-protocol.md)) uses them; its motivating numbers, computed from published data only, are in [`artifacts/2026-10-01-stability-v2-prereg/`](artifacts/2026-10-01-stability-v2-prereg/).

## The data-quality suite

ScrolIQ is the prioritization half of a two-part data-quality suite:

- **[zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit)** — integrity: *don’t train on lies*
- **ScrolIQ** — quality prioritization: *train on the best first*

`scrollq-health` combines both into one volume-level report:

- **TRAIN** — integrity passes, quality is finite and at least 40/100, and sampling provenance confirms that every requested chunk was decoded
- **CAUTION** — integrity warns, quality is low or invalid, sampling is incomplete/unverified, or quality cannot be scored
- **DO NOT TRAIN** — integrity FAIL (a high-severity finding, or an audit that crashed) **or integrity UNKNOWN** (an unreadable level, an absent root, nothing auditable)

Integrity comes from the companion's versioned report (`zpa.report.audit_root`, which never raises) and follows its `RECOMMENDED_CONSUMER_VERDICT`: missing evidence fails closed and is never read as a clean result. Every finding is kept with its code and evidence state. Until 2026-10-01, `scrollq-health` counted only high/medium findings, so UNKNOWN evidence or an audit exception left integrity at PASS — the divergence the companion's [`docs/INTEGRATION.md`](https://github.com/Svyable/zarr-pyramid-audit/blob/main/docs/INTEGRATION.md#scroliq-integration-surface) recorded.

The quality check requires `sampling.complete` to be true and both
`sampling.requested` and `sampling.decoded` to match the requested sample
budget. A partial score remains attached to the report for inspection; it
cannot authorize TRAIN. Scoring exceptions produce an unscorable quality
record while preserving the integrity verdict. These decision paths are
covered by `python -m pytest tests/test_health.py -q`.

Success must be the boolean `true`; malformed scorer output is unscorable.
Both `--samples` and `--spread` require positive integers, checked before
network access. The CLI displays decoded/requested chunks and completion,
and tolerates missing optional component details.

This creates a practical gate before expensive downstream work begins.

The earlier integrity verdict paths were exercised against live data
(`artifacts/2026-10-01-health-verdicts-fail-closed/`, workflow
`health-verdicts.yml`): **TRAIN** on the healthy PHerc0813 dl volume
(integrity PASS, quality 76.2); **DO NOT TRAIN** on the defective PHerc0814 S3
pyramid (6 high-severity `LEVEL_NO_CHUNKS` — quality honestly unscorable,
verdict from the audit alone); **CAUTION** on a v2 dev mesh (quality
unscorable); and **DO NOT TRAIN** on a negative-control root that does not
exist (integrity UNKNOWN, `ROOT_ABSENT`). The three published verdicts are
unchanged from `artifacts/2026-09-30-health-verdicts/`.

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

The same full commit is recorded in the package metadata, so fresh editable
and wheel installs cannot silently follow a newer companion default branch.

## Label-coverage analysis

ScrolIQ can join quality scores with discovered ink-detection and surface-volume roots from the open-data audit:

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
prize-eligible volume IDs to ScrolIQ scores and compares candidates on a
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
weight-free frontier contains **PHerc0813** (highest ScrolIQ quality among the
13) and **PHerc1447** (15 existing segments). PHerc0800 remains useful as a
geometry testbed because it has six segments, but it is dominated by PHerc1447
on both current qualifier axes. This is campaign triage only, not an
ink-presence or Grand Prize success prediction.

An optional sensitivity pass can add externally measured **surface-prediction
CT support** without changing the primary ScrolIQ score or frontier:

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

### Derived manifests (drift check)

The built-in manifests above and below were copied by hand from the data
browser. `scroliq-manifest` derives the same structure from two pinned
machine-readable sources, the Challenge's own `prizeEligibility.json` (villa
`56d7c3a`) and the open bucket's `metadata.min.json`, so voxel size, energy,
released predictions, public segments and higher-resolution same-scroll scans can
be checked rather than re-copied, and `--compare-builtin` reports any drift:

```bash
scroliq-manifest --eligibility artifacts/2026-10-01-prize-targets/prizeEligibility.json \
  --index artifacts/2026-10-01-bucket-index/metadata.min.json.gz \
  --prize grand-prize-2027 --as-of 2026-10-01 --out out/gp-manifest.json --compare-builtin
```

Result (`artifacts/2026-10-01-prize-targets/`): **the hand-copied Grand Prize
manifest matches the official sources on all 13 targets** (a regression test).
The same check covers the First Letters manifest below. Scores carry about ±5
points of noise, so frontier labels are triage, not rankings.

## 2027 Grand Prize recto-coverage ledger

`scroliq-recto-coverage` turns the full-recto requirement into an explicit accounting gate. A frozen reference inventory declares the total recto surface area and decomposes it into the main sheet plus attached, detached, or disconnected outer patches. Every in-scope component must be unrolled and linked to submitted mesh IDs; the only permitted exclusion is a `disconnected-outer-patch`, and the sum of excluded area must remain **strictly below 10%** of the declared total surface.

```bash
scroliq-recto-coverage \
  --manifest submission/recto-coverage.json \
  --volume-root community-uploads/forrest/volcomp/PHerc0813/volumes/<volume>.zarr \
  --out submission/recto-coverage.audit.json
```

The audit also catches reference/component area imbalance and mesh IDs reused across multiple components, which would otherwise allow accidental double-counting. A pass means **100% of the declared in-scope reference inventory is accounted for**. It deliberately does not claim that the reference inventory itself discovered every papyrus fragment; that upstream completeness proof remains separate evidence.

See [the example coverage manifest](examples/grand-prize-recto-coverage.example.json).

## 2027 Grand Prize provenance gate

`scroliq-provenance` turns submission eligibility evidence into a machine-checkable graph instead of a last-minute manual checklist. Schema v5 pins the exact eligible CT volume to a hash-pinned ZPA 1.3 report and its audited metadata source attestation, requires every model to declare its source/model voxel size, axes, resampling policy, window and public preprocessing profile, validates the nested full-recto coverage ledger, and then links each declared coverage component → numbered tifxyz mesh → render → checkpoint → training datasets/regions → stochastic seeds → public training/inference experiment runs → public held-out validation against known ground truth. The v4 deterministic ink-evidence binding remains required.

```bash
scroliq-provenance \
  --manifest submission/provenance.json \
  --root-dir submission \
  --format github \
  --out submission/provenance.validation.json
```

The gate fails closed on wrong-volume lineage, missing/tampered/invalid ZPA evidence, non-PASS source integrity, source-attestation mismatches, model/source voxel or axis mismatches, undeclared resampling/preprocessing, a failing/mismatched recto ledger, coverage mesh IDs that differ from the submitted mesh set, training/prediction overlap, non-public or incorrectly licensed training data, prohibited higher-resolution same-scroll training sources, missing stochastic seeds or experiment runs, missing public held-out validation, same-volume training/validation overlap, broken mesh/render column traceability, package SHA mismatches, missing 1 cm scale-bar declarations, and incomplete banner coverage. It also records a canonical graph SHA-256, emits a complete provenance chain for every submitted render, and records held-out exclusion proofs. It deliberately does not set a performance threshold or claim papyrological legibility.

See [the provenance-manifest specification](docs/grand-prize-provenance.md) and [example manifest](examples/grand-prize-provenance.example.json).
For unpacked VC3D surfaces, `scroliq-hash column_01.tifxyz` computes the canonical tree SHA-256 used by the provenance gate, so the complete directory-format mesh is cryptographically bound without repacking it.

## First Letters target qualification

The same qualifier covers the 22 First Letters scans with `--prize
first-letters`. Each prize manifest declares its own required bootstrap
assets: First Letters requires only a surface prediction on the exact
eligible scan (all 22 have one). Lasagna predictions are recorded but not
required, because only 13 of the 22 have one.

```bash
scrollq-grand-prize --prize first-letters \
  --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --out out/first-letters-targets.json

# the same qualification on each disjoint-resample run
scrollq-grand-prize --prize first-letters \
  --volumes artifacts/2026-09-30-resampling-stability/stability-n24-dense-prov.json \
  --run run1 --out out/first-letters-targets-run1.json
```

On the published n24-dense scores the frontier is **PHerc0800, PHerc0813**;
on the disjoint resample it is **PHerc0800, PHerc1545**. Only PHerc0800 is
on the frontier in both runs, and it is there because of its six existing
segments, not its scan quality. Among these 22 scans the two runs agree only
at Spearman ρ ≈ 0.72, so the quality leader is a band (PHerc0813, PHerc1203,
PHerc0358, PHerc1545, PHerc0846B), not a single scroll. Evidence:
`artifacts/2026-09-30-first-letters-qualifier-n24-dense/`.

### Exact-scan surface-prediction CT support

`scroliq-support` measures how much of a released surface prediction lies on
real CT material, on the exact eligible scan, with a bootstrap 95% interval.
A *phantom* is a prediction voxel above 127 where the masked CT is exactly 0;
support is 1 − phantoms / positives (the external `ct_support` definition).
Prediction and CT must share one voxel grid, so a prediction made on another
scan of the same scroll fails closed.

```bash
scroliq-support --prize first-letters --samples 256 \
  --out artifacts/2026-09-30-first-letters-support/support_native.json
python bin/import_ct_support.py first-letters \
  artifacts/2026-09-30-first-letters-support/support_external.json
```

`bin/import_ct_support.py` replaces the hand-normalized import with one pinned
to an external commit; it reproduces the earlier Grand Prize import exactly
on all 12 shared scrolls. On the 18 scrolls where both sources are exact-scan
evidence, 15 external values fall inside the native 95% interval (mean
|difference| 0.043, max 0.111). The native run also gives the first
exact-scan numbers for PHerc0846A, PHerc1203, PHerc1218 and PHerc0125;
for PHerc1203 the higher-resolution scan's survey (0.698) overstated
eligible-scan support (0.454) by about 0.24. Adding support as a third axis,
**PHerc0175B, PHerc0306B, PHerc0490A and PHerc0800** are on the frontier in
both resample runs. Evidence: `artifacts/2026-09-30-first-letters-support/`. This is a geometry-prior
sanity metric, not ink or readability evidence.

## Do the scan metrics recover the documented protocol ordering?

The Challenge's open-problems page names scan-quality metrics as what would help
with compressed regions, and documents that finer, phase-optimized protocols
are less affected by haze. Several scrolls were rescanned under a second protocol
and the rescan ships a `transform.json` registering it to the first. `scroliq-pairs`
samples the same physical regions from both scans on one ~9 µm grid and asks
whether two intensity-scale-invariant metrics (`otsu_eta`, `edge_sharpness`) rate
the documented-better protocol higher. The hypothesis, constants and decision
rule were committed in [`docs/protocol-pairs-protocol.md`](docs/protocol-pairs-protocol.md)
before any real-data metric was computed; the verdict is computed by `decide()`.

**Result: both primary metrics are discordant** (`otsu_eta` 3/4 pairs reverse,
`edge_sharpness` 2/4, the latter exactly at the threshold) on four registered
pairs from the open bucket. All reversals are in the 1.129 µm vs 2.4 µm pairs,
`otsu_eta` effects are small (about 1–2 % of its level; `edge_sharpness` 7–25 % in the two
pairs where it reverses), and all are 5–25× above the resampling null, and a control for aligned-vs-rotated lattice interpolation
showed the suspected artifact does not explain them. The legacy 0–100 score shows
no consistent response to protocol quality either, so **do not compare ScrollQ
scores across different scans of the same scroll**. This is a negative result on
four pairs; the DLS 7.91 µm vs ESRF 2.4 µm pairs (including PHercParis4) could not
be run because their host is unreachable from the environment used. Full tables,
the deviation log (including that two of four deviations were decided after the
first two pairs' numbers were visible), and limits:
[`artifacts/2026-10-01-protocol-pairs/`](artifacts/2026-10-01-protocol-pairs/).

## Open-bucket data access and integrity

The scorer reads the dl.ash2txt.org volcomp (Zarr v3, sharded) store. The
Challenge's own streaming path, and what VC3D uses, is the open S3 bucket's
OME-Zarr **v2** layout: uncompressed `uint8`, 128³ chunks, one object per chunk.
`src/scrollq/omezarr.py` reads that layout with only `numpy` and `requests`; it
raises instead of decoding anything it does not understand and counts absent
(masked) chunks separately from decoded ones.

`scroliq-chunk-audit` checks, without downloading chunks, that every stored
chunk object has the size its `.zarray` declares. Over the whole bucket (65
volumes, 390 levels, 942,696 sampled objects) it observed **one declared-vs-stored mismatch**: PHerc0343P
8.64 µm level 0 stores 555 of 8,543 chunk objects (6.5 %) at 8× or 64× the declared
size. An exhaustive pass over all 23 prize-eligible volumes (4,228,772 objects)
found none. Details, limits and a maintainer-ready (unfiled) issue draft are in
[`artifacts/2026-10-01-bucket-chunk-audit/`](artifacts/2026-10-01-bucket-chunk-audit/).

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
