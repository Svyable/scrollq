# Pre-registration: do scan metrics recover the documented protocol ordering?

**Status:** frozen before any metric was computed on real data.
Everything under "Pre-registered constants" and "Decision rule" is implemented
in [`src/scrollq/protocol_pairs.py`](../src/scrollq/protocol_pairs.py)
(`preregistered_constants()` and `decide()`); the verdict is computed by that
code, not by hand. The commit that adds this file is the timestamp.

## Why this experiment

The Vesuvius Challenge's open-problems page names *scan-quality metrics* as
what would help with compressed regions
(`scrollprize.org/docs/37_2026_open_problems.md`, bottleneck table, line 662,
villa commit `56d7c3aeea4bbccf5f56b195ce2a44ea2cf601dd`). ScrolIQ's current
0–100 score is **not** such a metric and does not claim to be
(`docs/open-problems-alignment.md`: it "does not yet identify papyrus-layer
separability, compression, or decohesion"). Before any local metric is promoted
into the diagnostic passport it should clear a falsifiable test.

The same page documents an *ordering* of scan protocols we can test against:

- "smaller voxels … are less affected by the beam decohesion (haze)" (line 183);
- "We have evidence that working on 1.1 µm data yields cleaner results than
  2.4 µm data" (line 518);
- the ~2.4 µm / 22 cm / ~78 keV recipe "works well", while the earlier
  ~9 µm / 1.2 m / ~110 keV regime is "not as good as the first" (line 177);
- a figure caption: "with a more optimized protocol, individual windings
  become far easier to separate" (line 147).

Several scrolls were scanned under more than one protocol, and each rescan
ships a `transform.json` registering it to the earlier scan. Sampling the
same physical region from both scans gives a paired test.

## What this does and does not show

It tests **concordance with the team's documented protocol ordering** at a
matched physical scale. A metric that cannot rank the documented-better
protocol higher is not a usable haze/separability metric. A metric that can is
only *not yet disqualified*: this is a necessary check, **not** evidence of
readability, ink presence, surface quality, or Grand Prize readiness. The
ordering is the project's own statement, not an independent measurement, and
the protocols also differ in energy and propagation distance.

## Hypothesis

**H1.** At a common physical grid spacing, for registered regions of the same
scroll, the documented-better (smaller-voxel) protocol scores **higher** than
the coarser protocol on each primary metric.

Direction of every paired difference: `d = metric(fine) − metric(coarse)`;
H1 predicts `d > 0`. The fine scan is the one with the smaller voxel size.

## Metrics (fixed)

Computed on a `64³` float cube of 0–255 intensities.

- **`otsu_eta`** (primary): Otsu between-class variance divided by total
  variance over a 256-bin histogram, in [0, 1]. Two well-separated phases
  (dark gaps, bright papyrus) give values near 1; haze that fills the gaps
  pulls the histogram together and lowers it. Intensity-scale invariant.
- **`edge_sharpness`** (primary): 90th percentile of the gradient magnitude
  (central differences) divided by (p99 − p1) of the cube. Blur lowers it
  independent of brightness.
- **Exploratory only, never part of the verdict:** the existing ScrollQ
  components `grad_energy`, `dyn_range`, and the 0–100 `legacy_score` computed
  from them. These are not intensity-scale invariant; they are reported to
  show whether the legacy score responds to protocol quality at all.

## Matched-scale sampling (fixed)

1. For each scan choose the pyramid level whose voxel size is nearest
   **9.0 µm**; it must be within **15 %** or the pair is refused.
2. Sample both scans on **one** axis-aligned grid in the fixed scan's frame,
   with spacing equal to the **coarser** of the two chosen levels' voxel sizes
   (so neither scan is sampled finer than its data), via trilinear
   interpolation. The moving scan's points are mapped through the registration
   (direction and axis order are inferred from landmark residuals and rejected
   if ambiguous; see `src/scrollq/registration.py`).
3. Region centers are drawn uniformly from the fixed volume with a
   deterministic seed (`sha256(seed:sample:moving_id)`); **24** regions are
   requested, at most `8 × 24` candidates are tried.
4. A candidate is **rejected** (and counted, never hidden) if any sample falls
   outside either volume, if fewer than **98 %** of either cube's voxels are
   inside the scan mask, or if either cube is flat (p99 − p1 < 20). These
   rules use only mask occupancy and contrast range, never the primary
   metrics.

## Pair inclusion (fixed, metric-independent)

A registered pair is **included** iff all hold:

- the registration's fixed scan resolves unambiguously to a volume (embedded
  volume id, unique `scanRadix` match, or unique voxel-size/energy match);
- the two voxel sizes differ by a factor ≥ **1.8**;
- the mean landmark residual is ≤ **50 µm** (residual in destination-frame
  voxels × that frame's voxel size);
- at least **12** regions are accepted when run.

Pairs that fail only the residual rule may be run as a clearly separated
*sensitivity* analysis (`--sensitivity`); they never count toward the verdict.

### Discovery (run before any metric)

`scroliq-pairs --list` against the bucket index
(`index_sha256 15848845907fe640e63c16d0de200715fe74ed4f256623c94ef603cc84831b22`)
produced [`artifacts/2026-10-01-protocol-pairs/discovery.json`](../artifacts/2026-10-01-protocol-pairs/discovery.json)
with no metric computed. Pairs passing the inclusion rule:

| Pair (moving → fixed) | Voxel sizes | Landmark residual | Fixed scan hosted at |
|---|---|---|---|
| PHerc0139 `20260413113053` → `20260102150214` | 1.129 → 2.399 µm | 1.0 vox | open S3 bucket |
| PHerc0814 `20260521123630` → `20260309142202` | 1.129 → 2.399 µm | 0.9 vox | open S3 bucket |
| PHercMANBp `20260427100434` → `20251216152116` | 1.129 → 2.399 µm | 3.1 vox | open S3 bucket |
| PHerc0343P `20250521134555` → `20260304131111` | 8.64 → 2.215 µm | 0.9 vox | open S3 bucket |
| PHerc1667 `20251217075048` → `20231117161658` | 2.399 → 7.91 µm | 5.6 vox | `data.aws.ash2txt.org` |
| PHercParis4 `20260411134726` → `20230205180739` | 2.4 → 7.91 µm | 1.9 vox | `data.aws.ash2txt.org` |

The last two (including the DLS 7.91 µm vs ESRF 2.4 µm comparison the Open
Problems page illustrates) are **not reachable from the environment this was
run in**; if their fixed scans cannot be opened they are reported as
`run failed` and excluded. They will count automatically when run from an
environment that can reach that host. Excluded at discovery: PHerc0332
(residual 91 µm), PHerc1667 1.129 µm (103 µm), PHercParis4 45.5 µm (429 µm),
PHerc0009B and PHercParis4 1.129 µm (fixed scan ambiguous between two
candidates), and scans registered to volumes that are not in the bucket.

## Controls (fixed)

- **Pipeline null.** For every accepted region the same pipeline is re-run on
  the *same* volume with the grid shifted by half a step. Any difference is
  resampling noise, not protocol. A pair only counts as concordant if its
  median |null| is below **25 %** of its median |d|.
- **Can-fail check.** Unit tests build two synthetic registered scans of one
  analytic field, run the full pipeline, and require the paired difference to
  flip sign when the *finer* scan is made the hazy one
  (`tests/test_protocol_pairs.py`). A second test mutates the registration
  mapping and requires the sampled cubes to decorrelate.

## Decision rule (primary metrics only, evaluated independently)

For each included pair and metric, with `frac_positive` the share of accepted
regions with `d > 0`:

- **concordant pair:** median `d > 0`, `frac_positive ≥ 0.75`, and the null
  criterion above;
- **discordant pair:** median `d < 0` and `frac_positive ≤ 0.25`;
- otherwise **mixed**.

Metric verdict over included pairs `n`:

- `n < 3` → **inconclusive** (too few pairs);
- ≥ **80 %** of pairs concordant → **concordant**;
- ≥ **50 %** of pairs discordant → **discordant**;
- otherwise → **inconclusive**.

With four runnable pairs, "concordant" therefore requires all four.
Regions inside a pair are spatially correlated; the replication unit for the
verdict is the **pair**, and per-pair sign tests and bootstrap intervals are
descriptive only.

## Known limitations (stated up front)

- Four independent scroll pairs is a small sample; a clean result would still
  be modest evidence.
- The 1.129 µm and 2.4 µm scans differ in energy (59 vs 78 keV) and
  propagation distance as well as voxel size; the test cannot attribute an
  effect to any single factor.
- Matched grid spacing does not match noise: the finer scan, downsampled,
  averages more photons per output voxel.
- The pyramid's downsampling filter is not documented in the bucket metadata.
- Registration is landmark-based; residuals up to 50 µm are tolerated against
  cubes ~0.6 mm wide.
- A "concordant" verdict says the metric orders protocols as the team
  describes. It does not say the metric predicts segmentation success, ink
  detectability, or readability.

## Deviation policy

Any change to a constant, rule, or code path that affects results after the
first real-data metric run is recorded in the artifact README as a deviation
with its reason, and the original run is kept alongside it. Bug fixes that do
not change definitions (e.g. a crash) are noted but not counted as deviations.

## Reproduce

```bash
scroliq-pairs --list --out out/discovery.json
scroliq-pairs --out out/protocol-pairs.json            # decision runs
scroliq-pairs --sensitivity --out out/protocol-pairs-sensitivity.json
```
