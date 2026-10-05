# Winding conservation, compressed-sheet splitting and topography bandwidth — 2026-10-05

**Status:** one experiment integrated as evaluation-only machinery
(`scroliq-winding-conservation`, synthetic calibration only); two items held at
WATCH. No scoring behaviour, training path, frozen artifact or Grand Prize
execution order changes.

Every number below that is attributed to an external project or paper was
**reported by that source and has not been reproduced here**. ScrollQ's own
numbers trace to `artifacts/2026-10-05-winding-conservation-synthetic/`.

## 1. Winding-pitch and layer-count conservation as whole-scroll QC

**Decision: INCLUDE as a validation experiment (evaluation-only).** Machinery
and a synthetic planted-defect calibration are in the repo; no real stitched
solution has been measured yet.

### Source and why it matters

`vesuvius-sheet-tools` (MIT code) reports a whole-scroll PHerc1218
instance-separation and stitching run: 686,360 local sheet-instance segments,
mean cross-slab agreement improved from 53.5% to 82.1% by overlap stitching, and
a stitched-label winding pitch of median 173 µm (IQR 147–199 µm) over 24,960
(z, θ) cells. It also reports an independent finer-pyramid "Winding Atlas" value
of 172.8 µm, and a planted seam-error control whose unpaired layer-count
statistic detects seam events merging roughly ≥ 7% of a slab's wraps. Its
derived PHerc1218 dataset and the source volumes are CC BY-NC 4.0.

The transferable idea is a principle, not the splitter: **a reconstructed scroll
must satisfy global conservation laws that were not used to build any single
surface.** Local CT seating can be excellent while a stitch silently loses,
duplicates, merges or swaps a winding, and counting crossings along radial rays
attacks that failure class directly.

### What ScrollQ implemented (independently)

`scroliq-winding-conservation` ([contract](../winding-conservation.md)) bins a
labelled winding solution into 5° × 16-voxel (θ, z) cells around the umbilicus
and checks three invariants per cell, plus a weak support check:

- **layer count** — the label-free crossing count equals the label span, and
  labels step by ±1 along each ray;
- **pitch** — every gap lies within 0.6–1.4 × the ray's own median gap; pitch
  is reported in µm;
- **identity continuity** — across every cell boundary, shared labels move
  together radially, and an interior label never vanishes;
- **support** — a crossing's point density is not below half the cell median.

No code, threshold or data was copied from `vesuvius-sheet-tools`. The splitter
was not adopted, and neither were its thresholds. ScrollQ's thresholds are
frozen in the module. They were not tuned on any real solution, and the
synthetic calibration did not change them.

### Planted-defect calibration

The four requested defects are planted deterministically inside a
(θ, z) footprint on one winding:

| defect | what changes | CT seating |
|---|---|---|
| delete | winding k removed | unchanged elsewhere |
| duplicate | winding k emitted twice (1 voxel apart); outer labels +1 | unchanged |
| merge | k and k+1 become one surface halfway between; outer labels −1 | moved |
| switch | k's surface replaced by k+1's own vertices, label kept | **unchanged** (every vertex is a real sheet vertex) |

The ladder covers 8 angular extents × 6 z extents × 16 placements per defect,
alongside a null in which the same footprints are measured on the unmodified
solution. The synthetic substrate has a 20-voxel pitch at 8.64 µm (172.8 µm),
±15% smooth pitch modulation, 0.75-voxel radial jitter, and a compressed-but-correct
sector (four gaps squeezed to 0.65×) that serves as a hard null. Results and
the smallest reliable extents are in
[the artifact README](../../artifacts/2026-10-05-winding-conservation-synthetic/README.md).

### Promotion gate

Promote from validation experiment to a **global winding-conservation /
stitching-consistency proof gate** only after all of the following:

1. a frozen real stitched solution (whole scroll or large window, with
   umbilicus and branch cut) is measured, with its SHA-256 pinned before the
   measurement is read;
2. the same four defects are planted on that real solution, and the real
   smallest reliable extent is reported next to the synthetic one;
3. every flagged cell on the unmodified real solution is reviewed in VC3D and
   classified as stitching error, fold/tear/crush, or the scroll's own edge.

The gate may not be tightened to "zero flags" while legitimate folds still
fire it.

### Limitations recorded up front

- The synthetic substrate is not data, and it is kinder than real CT: its
  sheets are complete, its jitter is Gaussian, and its labels follow one
  branch cut exactly.
- A defect smaller than about one cell (5° × 16 voxels) leaves the cell's
  per-label median radius almost unchanged. That is the method's resolution
  limit, not a tuning accident.
- Fixed angular cells grow in arc length with radius. At the outer windings
  of a full scroll a 5° cell is long, and steep sheets can exceed the
  half-pitch continuity tolerance. Real false-alarm rates must be measured,
  not assumed from the synthetic null.
- The branch cut must be declared. A wrong cut is loud: it floods the
  continuity flags along the true and declared cuts.

### Self-evaluation

- Grand Prize applicability: **very high**, because the prize requires 100% recto unrolling
- expected reconstruction impact: **medium**, through rejecting and localizing bad stitches
- integration difficulty: **low**
- evidence quality: **medium-high** at the source. Here it is **synthetic only** so far
- reproducibility: **high**, since everything is deterministic and seeded
- compute: **very low** next to fitting
- leakage: **zero**, since it is evaluation-only and never sees ink
- licensing: the code is independently written. The CC BY-NC data is not
  repackaged; a real run stores hashes and source URIs only

## 2. CT-intensity / structure-tensor splitter on compressed sheets

**Decision: WATCH → controlled topology experiment.**

The same project reports that, in a crushed PHerc1218 region, a CLAHE-equalized
CT-intensity and structure-tensor splitter cut the largest fused instance from
15.55% to 3.48% of the mask. Its sheet-thickness proxies were 4.1–5.5 voxels.
For contacts under 4 voxels it also reports that 78% of sampled learned-surface
probability profiles show a single broad peak and only 0.5% are separable.
The authors themselves say the learned prediction cannot resolve the tightest
contacts. They also say it is unknown how much of that population CT intensity
can recover.

This agrees with the compressed-sheet failure ScrollQ already records. It is a
candidate remedy, not an established one.

**Smallest admissible test:** run the splitter **unchanged** on a frozen
compressed-sheet ground-truth pool. Hold the foreground mask constant and score
topology before and after.

**Promotion** requires better sheet separation **and** no increase in false
splits on close-but-correct sheets. Over-splitting manufactures sheets, and
`scroliq-winding-conservation` would see that as layer-count and pitch excess.
The proof gate is *compressed-sheet identity preservation*.

**Blocker:** ScrollQ has no frozen compressed-sheet ground-truth pool yet. A
repository search on 2026-10-05 found none. Freezing one, with thresholds chosen
away from proof regions, comes first. The splitter's central thresholds
(planarity ≥ 0.35, normal alignment ≥ 0.90, merge-border limits) are empirically
calibrated upstream. They stay frozen at upstream values for the test and are
not retuned on ScrollQ regions.

Applicability is high and possible impact is high. Difficulty, evidence quality
and CPU/GPU cost are all medium, and reproducibility is high. Leakage is low if
thresholds stay frozen. Geometry-hallucination risk is **medium**.

## 3. Topography ink evidence has a spatial bandwidth

**Decision: WATCH. Feeds the existing morphology control; no new import.**

The version of record (2026-09-07) of *Ink detection from surface topography of
the Herculaneum papyri* reports results on optical profilometry of opened
PHerc248, PHerc250 and PHerc500P2 fragments:

- topography-only segmentation reaches a median held-out Dice of 0.890 at the
  stated 0.34 µm sampling;
- Dice falls monotonically to 0.467 at 10.88 µm;
- a native-resolution model fed degraded input collapses toward zero at about
  3.4 µm effective sampling or coarser;
- leave-one-papyrus-out mean Dice is 0.691.

**Conflict with what is already pinned here.** The source's statement that its
data "will be released" does not match this repository. ScrollQ already pins a
public profilometry release, `scrollprize/profilometer` at revision
`a806bead…` (CC BY-NC 4.0), in
[morphology-ink-control.md](../morphology-ink-control.md). That release records
**0.688 µm/pixel** native sampling where the manuscript says **0.34 µm**, and the
dataset's own 2026-09-03 notice says the discrepancy is under investigation.

The paper's strongest mechanistic claim is a resolution threshold. If the
release's value is correct, every µm figure above doubles: the collapse point
moves from ~3.4 µm to ~6.9 µm. So the cutoff is **scale-uncertain** until the
maintainers resolve it, and no detectability boundary should be quoted in µm
before then. The morphology control already fails closed on absolute-scale
transfer for this reason.

**Smallest experiment (when unblocked):** an acquisition-resolution
falsification test, independently implemented:

1. freeze ink labels on surfaces where ScrollQ has independently established ink;
2. extract only local CT-derived surface-height and normal-residual features;
3. evaluate their ink association by acquisition resolution;
4. deliberately degrade the same ~2.4 µm CT surface to 4–10 µm.

If signal at native resolution disappears under degradation, the result is an
independent physical ink channel plus a measured detectability boundary. The
proof gate is *resolution-conditioned morphological ink evidence*.

**Licensing:** the paper is CC BY-NC-ND 4.0, so none of its figures, labels,
splits or unreleased implementation may be copied or adapted. The hypothesis
and an independently written experiment are fine. Re-evaluate when the sampling
discrepancy is resolved and the paper's samples, labels, splits and configs
appear with explicit terms.

Applicability is medium-high and impact medium. Evidence quality is high for
opened material but weak for transfer to sealed-scroll CT. Reproducibility is
low-to-medium, leakage risk is low with frozen labels, and hallucinated-ink
risk is low only if the optical result is not extrapolated naively to CT.
