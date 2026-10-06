# Ink-blind flattening benchmark

ScrolIQ treats flattening as a geometric proof problem, not as a way to make
text look better. A candidate parameterization must beat the current baseline
**before any ink render, OCR output, or legibility judgment is allowed into the
selection loop**.

This benchmark was added to evaluate high-upside parameterization methods such
as Guy Fargion and Ofir Weber, *Fast Injective Mesh Parameterization via
Beltrami Coefficient Prolongation*, Computer Graphics Forum 45(2), 2026,
DOI [10.1111/cgf.70341](https://doi.org/10.1111/cgf.70341).

The paper is open access under CC BY 4.0. That does **not** establish a
permissive software license for any implementation. ScrolIQ therefore records
the exact candidate implementation reference and fails the promotion gate
unless its software license is explicitly permissive. An independent
implementation written in this repository would inherit ScrolIQ's MIT license.

## Why this is a separate gate

The Grand Prize requires low-distortion 2-D parameterizations in the submitted
TIFXYZ meshes. It also places a high evidentiary burden on apparent text.
Optimizing flattening while looking at ink would create an avoidable
selection channel: a geometrically worse map could be preferred because it
makes a letterform look more convincing.

The comparison therefore consumes only Wavefront OBJ geometry and UVs.
It does not read CT, ink probabilities, images, OCR, or text.

## Sealed command path

For exploratory use, `scroliq-flatten-compare` remains the generic comparator.
Grand Prize evidence must use `scroliq-flatten-plan` so the baseline bytes,
candidate implementation identity/license, and all decision thresholds are
frozen **before** candidate evaluation.

First seal the plan:

```bash
scroliq-flatten-plan seal \
  --baseline-obj out/column_01.vc3d.obj \
  --experiment-id column_01-beltrami-v1 \
  --candidate-method beltrami-coefficient-prolongation \
  --source-ref doi:10.1111/cgf.70341 \
  --implementation-ref git:<pinned-permissive-commit> \
  --implementation-license MIT \
  --corpus-role ordinary-curved-column \
  --source-mesh-ref <immutable-source-ref> \
  --min-p95-improvement-fraction 0.01 \
  --out prereg/column_01.flatten-spec.json
```

Commit or otherwise publish that spec before running or inspecting the candidate.
Then evaluate with no metadata/threshold override surface:

```bash
scroliq-flatten-plan evaluate \
  --spec prereg/column_01.flatten-spec.json \
  --baseline-obj out/column_01.vc3d.obj \
  --candidate-obj out/column_01.beltrami.obj \
  --out out/column_01.flatten-compare.json \
  --require-promote
```

The result records the spec SHA-256 and rejects a baseline whose bytes or
UV-independent ordered 3-D geometry differ from the sealed spec. Thresholds and
candidate implementation metadata are read only from the spec.

## Promotion contract

A candidate receives `PROMOTE` only when all of these conditions hold:

1. **Exact 3-D geometry identity.** Ordered vertices and triangulated faces
   hash identically after parsing. This prevents a "better flattening" from
   silently changing the reconstructed papyrus surface.
2. **Permissive implementation license.** The declared software license must
   be on ScrolIQ's conservative permissive allowlist.
3. **Complete UV coverage.** Every triangle must be textured.
4. **Zero UV foldovers.** No triangle may reverse orientation relative to the
   majority UV orientation.
5. **Zero degenerate UV triangles.**
6. **No new UV cuts.** Every UV seam edge of the candidate (a 3-D edge whose
   incident faces disagree on an endpoint's UV coordinates) must already be a
   seam of the sealed baseline; fewer cuts is allowed. Cutting always lowers
   per-triangle distortion (one isometric island per triangle has stretch 1.0),
   so without this gate a candidate could win by fragmenting the atlas. The cut
   set is therefore frozen with the baseline bytes. Added 2026-10-06; see
   [the note](research/2026-10-06-beltrami-prolongation-watch.md).
7. **p95 local isometry non-regression.** Candidate p95 symmetric stretch may
   not exceed the baseline by the predeclared ratio (default 1.0).
8. **Median local isometry non-regression.** Candidate median symmetric stretch
   may not exceed the baseline by the predeclared ratio (default 1.0).
9. **Material p95 improvement.** The default promotion threshold is at least
   1% lower p95 symmetric stretch.

Passing all safety gates without the predeclared material improvement produces
`HOLD`, not `PROMOTE`. Any failed required gate produces `REJECT`.

The isometry calculation is the existing `scroliq-obj` metric: singular values
of each UV-to-3D triangle Jacobian after one global UV scale aligns total area.
This is intentionally reused rather than introducing a second distortion
definition for the candidate method.

## Tier-0 implementation fixtures

Before a candidate implementation is allowed onto the sealed Tier-1 corpus,
run it against the pinned non-promoting real-papyrus fixtures in
[`artifacts/2026-10-03-flattening-tier0/`](../artifacts/2026-10-03-flattening-tier0/README.md).
The set freezes exact public OBJ hashes for an ordinary PHerc0139 surface, a
PHerc1447 hole/tear stress case, and a PHercMANBp high-distortion case. The
verifier replays the existing OBJ audit and preserves the Challenge data's
CC BY-NC 4.0 boundary.

A successful Tier-0 result is engineering evidence only. It **cannot PROMOTE**
a flattening backend; production promotion still requires the sealed
column-sized Tier-1 A/B experiment from issue #114.

## Beltrami-prolongation experiment

The 2026 method is attractive because it solves a heavily simplified mesh in a
full optimization space, prolongs Beltrami coefficients rather than UV
coordinates, and then reconstructs the fine parameterization with a modified
harmonic solve. The authors report injective maps with low distortion and
speedups of up to 50x (as summarized from the abstract by a search result; the
per-size figures, roughly 10-32x above 1.5M triangles and 10-50x above 500K, are
relayed from the 2026-10-06 briefing and were not re-read).

ScrolIQ does **not** treat those published results as papyrus evidence.
Promotion requires a sealed A/B benchmark on representative scroll column
meshes.

The first experiment should:

- freeze the 3-D column meshes before either parameterization is inspected;
- run the existing VC3D/current flattening baseline;
- seal one `scroliq-flatten-plan` spec per corpus mesh and commit those specs;
- run one pinned, permissively licensed Beltrami-prolongation implementation;
- evaluate only through `scroliq-flatten-plan evaluate`;
- keep ink inaccessible until the winner and report hash are frozen;
- publish every `PROMOTE`, `HOLD`, and `REJECT` result rather than keeping
  only favorable meshes.

The spec tool cannot prove chronology by itself. Git history (or another
immutable publication record) is the temporal proof that the sealed spec
predated candidate evaluation; the tool proves that the later evaluation used
the exact frozen baseline and rule set.

If a candidate is promoted here, it still has to be converted through the
normal VC3D/TIFXYZ path and pass the existing Mesh IQ, CT support/preflight,
self-intersection, provenance, physical-scale, and submission-image gates.
This comparator does not establish those facts.

## Frozen metric panel for the first sealed A/B

Defined 2026-10-06, before any candidate implementation exists, so that no
metric is chosen after a result is seen. The **status** column is the honest
state of the code: only rows marked *enforced* change a verdict today.
Everything marked *not implemented* is a definition to be built and sealed
before a real run, not a claim that it is already checked.

| # | Measure | Definition | Role | Status |
|---|---|---|---|---|
| 1 | Geometry identity | Ordered 3-D vertices and triangulated faces hash identically | gate | enforced |
| 2 | UV coverage | Every triangle textured | gate | enforced |
| 3 | No new UV cuts | Candidate seam edges are a subset of the sealed baseline's | gate | enforced (2026-10-06) |
| 4 | Local orientation | Zero triangles opposite the majority UV orientation, tested with exact arithmetic on the **serialized** UV text values, because a map that is injective in memory can fold once written at finite precision | gate | float screen enforced (area tolerance 1e-18 on parsed doubles); exact predicate not implemented |
| 5 | Global injectivity | No two UV boundary edges cross or touch, exact. For a disk chart, locally consistent orientation plus a simple boundary implies injectivity; charts with holes also need non-crossing hole loops. Without this, row 4 is a local claim only | gate | not implemented |
| 6 | Degenerate triangles | Zero | gate | enforced (float tolerance) |
| 7 | Symmetric stretch | Per triangle `max(sigma_max, 1/sigma_min)` of the UV-to-3-D Jacobian after one area-matching global scale; p95 and median non-regression, p95 improvement for PROMOTE | gate | enforced |
| 8 | Symmetric Dirichlet | Per triangle `sigma1^2 + sigma1^-2 + sigma2^2 + sigma2^-2` (4 at isometry), same global scale; area-weighted mean and p50/p95/p99/max for both maps. Row 7 is a max-type measure, so it does not show the energy the paper's direct baseline optimizes (relayed) | reported | not implemented |
| 9 | Physical-unit length and area distortion | Per-edge length ratio and per-triangle area ratio with UVs scaled by a sealed micrometres-per-UV-unit taken from hashed volume metadata (the pattern `scroliq-vc3d-run-guard` uses), reported as log2 quantiles. The area-matching scale in row 7 hides a uniform shrink or stretch; this row records the atlas's absolute physical area for both maps and requires them to agree within a sealed tolerance | reported; gate only if sealed | not implemented |
| 10 | Boundary behaviour | Boundary-edge length-ratio quantiles (candidate over baseline), and the declared boundary mode (free, fixed or prescribed). Harmonic-type maps can concentrate distortion at the boundary | reported | not implemented |
| 11 | Fiber-trajectory preservation | Ink-blind fiber streamlines traced on the 3-D mesh **before** either flattening is inspected; drift of their UV-image tangent from the frozen reference direction, and zero streamline-pair crossings in UV. Builds on `scroliq-fiber` / `scroliq-fiber-frame` and the material-coordinate distortion overlay in the [research index](research/README.md) | reported; gate only if the fiber field is sealed with the spec | not implemented; no frozen fiber field exists for any candidate mesh |
| 12 | Runtime and peak RAM | End-to-end wall time and peak resident memory from the same input OBJ to the written OBJ, including simplification, coarse solve, prolongation, final solve, verification and any foldover repair; at least 3 repeats on one host with hardware, thread count and library versions recorded; the baseline is measured on that host, never quoted | descriptive (issue #114); gate only through the proposed throughput arm | not implemented |
| 13 | Baseline repeat noise | At least 3 repeats of the **baseline** flatten on the unchanged mesh; the range of its p95 stretch is the noise floor, and the sealed improvement threshold must exceed it. Same logic as [`scroliq-render-noise`](render-noise.md), applied to geometry. The repeat outputs are kept | prerequisite to sealing | not implemented |
| 14 | Blind ink render | Only after the winning report hash is frozen; descriptive; can neither select nor demote a candidate | none | out of the decision path |

### Decision arms

- **PROMOTE (existing).** Rows 1-6 pass, row 7 does not regress within the sealed ratios,
  and p95 stretch improves by at least the sealed fraction (default 1%). A quality gain.
- **HOLD.** Safe but no material gain. Includes a candidate with equivalent distortion
  that is only faster, under the rule as it stands today.
- **REJECT.** Any gate fails, or the spec does not bind the baseline.
- **PROMOTE_THROUGHPUT (proposed, not implemented).** Rows 1-6 pass, row 7 non-regresses
  within sealed ratios (a margin above 1.0 may be sealed, but never below the measured
  row-13 noise), and the sealed `min_speedup` and peak-RAM ratio are met on row 12. It
  is a separate verdict so a faster map is never reported as a better one, and adopting
  it only replaces the baseline for throughput. **No default `min_speedup` is proposed**:
  no papyrus run exists to calibrate one and the paper's relayed speedups are a
  hypothesis, not a threshold. This changes issue #114's "runtime is descriptive"
  stance, so it needs a maintainer decision before it is built.

### Corpus and domain rules

- A disk-only method (the relayed BCP limitation; the authors' README also assumes
  "3D disk-like meshes") runs only on disk-topology meshes. A mesh with several
  boundary loops is `out_of_domain` unless the baseline was produced on the same cut
  mesh, in which case the cut is frozen by row 3. It is never dropped from the
  published results.
- Correctness runs may use the Tier-0 fixtures. **A throughput claim cannot:** the
  largest Tier-0 mesh has 172,218 triangles, below the 500K-triangle regime where the
  relayed speedups apply. The sealed throughput pool is the corpus-audit meshes above
  500K triangles with one component, one boundary loop and Euler characteristic 1: 19
  of the 200 audited OBJ meshes (11 from 0.5M to 1.5M triangles, 8 above 1.5M, largest
  3,323,828), from [`artifacts/2026-10-01-corpus-mesh-audit/`](../artifacts/2026-10-01-corpus-mesh-audit/README.md).
  Choose and seal the mesh before either parameterization is inspected.
- The first run is one frozen mesh, then the #114 set. Publish every PROMOTE, HOLD,
  REJECT, `out_of_domain` and failed run.

### Order of operations

1. Freeze the mesh, the cut (inside the baseline bytes), the metric definitions above
   and the thresholds, and measure the baseline noise floor (row 13).
2. Seal with `scroliq-flatten-plan seal` and commit before running the candidate.
3. Run baseline and candidate with the row-12 protocol.
4. Evaluate; freeze the report hash.
5. Only then compare ink renders, descriptively. Better-looking text is never a
   promotion criterion, and a layout that merely warps the surface so text looks
   better is exactly the selection channel this order forbids.

## What this deliberately does not prove

A `PROMOTE` verdict does **not** establish correct winding identity, CT
support, complete recto coverage, physical 1-cm scale, absence of nonlocal
self-intersections, or readable ink. It establishes only that, for one frozen
3-D triangle mesh, the candidate UV map is injective under the local foldover
test and improves the predeclared distortion metric without changing geometry.

That narrow claim is intentional: flattening can improve the submission only
after the surface itself is already physically defensible.


## Current implementation-license decision

**Re-checked 2026-10-06.** The 2026 paper is the scientific method reference. Its
official implementation exists at `github.com/GuyFa/BCP` (checked at commit
`2f3808d6ea0156b0c3dca77abb2a9fadf8315b03`) and is **not** usable: the README restricts
it to academic use, the tree has no license file, it requires MATLAB and PARDISO, and it
bundles Shewchuk's *Triangle* (no commercial redistribution). The authors' earlier GIF
(2022) and LMF (2025) implementations carry the same academic-use limit. None of these
may be vendored into, or made a dependency of, the Grand Prize pipeline, and a
relicense of the top-level repository would not clear the bundled third-party code.

The paths forward are a written permissive relicense from the authors with the bundled
pieces replaced, or an independent MIT implementation written from the paper without
reading that repository's source. Issue #114 tracks the second. Details:
[research note](research/2026-10-06-beltrami-prolongation-watch.md).
