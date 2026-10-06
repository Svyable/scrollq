# Beltrami-coefficient prolongation flattening, CGAL re-check and Challenge-page re-check — 2026-10-06

**Status:** one method held at WATCH with its benchmark defined now and a license
trigger that differs from the briefing's; one atlas-cutting hole in the existing
flattening gate found and closed; two re-checks with unchanged decisions. No scoring
behaviour, frozen artifact or Grand Prize execution order changes.

**What was read here and what was relayed.** Read here: a web-search snippet of the
Eurographics digital-library entry, and the **authors' repository** (`README.md`, file
names, the bundled third-party license notices; no algorithm source). Everything else
about the paper (the 252-mesh benchmark, the 10-32x / 10-50x speedups, 37 minutes vs
more than 10 hours, five meshes needing foldover repair, exact-predicate verification,
CC BY 4.0) and about CGAL and the Challenge pages is from the 2026-10-06 maintainer
briefing and was not re-read.

## 1. Fargion and Weber, Beltrami-coefficient prolongation (BCP)

**Decision: WATCH the method. DISMISS the authors' code as a dependency or source.**
Fargion and Weber, *Fast Injective Mesh Parameterization via Beltrami Coefficient
Prolongation*, Computer Graphics Forum 45(2), 2026,
DOI [10.1111/cgf.70341](https://doi.org/10.1111/cgf.70341).

### The briefing's license premise is wrong, and the answer is worse

The briefing "could not verify an official reusable implementation with an explicit
software license" and set the trigger "once reusable code is licensed". An official
implementation does exist: `github.com/GuyFa/BCP`, checked at
`2f3808d6ea0156b0c3dca77abb2a9fadf8315b03` (2026-04-22, "Update README.md"). It is
not reusable:

- **Terms.** The README says: "The use of this application is limited to academic use
  only!" and "provided as-is and without any guarantees." There is no `LICENSE`,
  `COPYING` or `NOTICE` file anywhere in the tree. Public source is not permission to
  reuse it.
- **Encumbered dependencies**, from the README's prerequisite list: MATLAB R2022b and
  PARDISO 8.2 (both commercially licensed), CGAL 5.6, plus a Windows-only build that
  the authors say was never tested elsewhere.
- **Bundled third-party code.** `GIF/GIF/Utils/` ships Shewchuk's *Triangle*, whose own
  notice allows redistribution only "under the condition that ... no compensation is
  received". The README says `CompMajor` is "partially based on" `Roipo/CompMajor`, one
  of its headers (`PardisoSolver.h`) carries a 2015 "All rights reserved" notice from a
  third party, and three `libigl` submodules are listed. The submodule terms were not
  read. Even a relicense by the authors would not clear these.
- **Domain.** The README states the input is "a list of 3D disk-like meshes", which
  confirms the disk-topology limitation in the briefing.

This is consistent with the authors' earlier GIF (2022) and LMF (2025) releases, which
the [flattening benchmark](../flattening-benchmark.md) already records as academic-only.
The paper's own CC BY 4.0 does not change any of this; it covers the article.

### What the trigger is now

"Licensed code appears" will not happen on its own. WATCH becomes an experiment on
either of:

1. **A written permissive relicense** from the authors with every bundled third-party
   piece replaced or separately cleared. This is an outward-facing request that only the
   maintainer can make.
2. **An independent clean-room implementation** in this MIT repository from the paper
   alone, which is what issue #114 already plans. Whoever writes it should not read the
   repository's source. Only its README, file names and license text were read in
   preparing this note, so that line is not crossed here. Patent status of the method
   was not checked.

Until one of those holds, nothing changes in the pipeline.

### A hole in the existing gate, found while defining the benchmark

"Fixed cuts" in the briefing exposed that the comparator did not fix them. It scores
distortion per triangle, so a candidate that lays every triangle out as its own
isometric island has p95 stretch 1.0, zero flips and identical 3-D geometry. On a
12 x 12 quarter-cylinder control the old gate returned **PROMOTE** for it (p95 1.225 ->
1.000). Cutting always lowers distortion, so any parameterizer, including a perfectly
honest one, can "win" by cutting more.

Closed in commit `69c7e07`: a required gate `candidate_no_new_uv_seams` (the candidate's
UV seam edges must be a subset of the sealed baseline's; fewer cuts is allowed). The
baseline seam set comes from the already-sealed baseline bytes, so the spec schema is
unchanged and `scroliq-flatten-plan` inherits it. No sealed spec and no candidate
result existed, so no published number depended on the old behaviour. The Tier-0
round-trip control re-emits identical UVs and is unaffected. Reverting only the gate
makes the new shattered-atlas test fail.

Consequence for a disk-only method: a mesh with more than one boundary loop, such as the
17-loop PHerc1447 Tier-0 fixture, can only be run if the baseline was produced on the same
cut mesh, so the cut is sealed with the baseline bytes. Otherwise it is recorded
`out_of_domain`, never silently dropped.

### The benchmark, defined now

The frozen metric panel, its implementation status row by row, and the decision rules
are in [flattening-benchmark.md](../flattening-benchmark.md#frozen-metric-panel-for-the-first-sealed-ab).
Three points specific to this briefing:

- **Throughput needs a bigger mesh than Tier-0.** The relayed speedups are for meshes
  above 500K triangles. The Tier-0 fixtures top out at 172,218 triangles, so they can
  test correctness and nothing about speed. The existing corpus audit
  ([`2026-10-01-corpus-mesh-audit`](../../artifacts/2026-10-01-corpus-mesh-audit/README.md))
  has 42 of 200 audited OBJ meshes above 500K triangles. Of those, 19 have one component
  and one boundary loop, and all 19 have Euler characteristic 1 (true disks): 11 between
  0.5M and 1.5M triangles and 8 above 1.5M, the largest 3,323,828 (PHerc0139 w030).
  Those are the pool a sealed throughput run should draw from, chosen before either
  parameterization is inspected.
- **Runtime is descriptive in issue #114, and the briefing's criterion promotes on it.**
  "Materially lower or equivalent distortion at substantially lower runtime" would give
  HOLD under the current rule, because an equivalent-distortion candidate misses the 1%
  p95 improvement. The proposal is a separately named verdict, `PROMOTE_THROUGHPUT`, so
  a faster map is never reported as a better one. It needs a maintainer decision and is
  not implemented.
- **No throughput threshold is proposed.** No papyrus run exists to calibrate one, and
  the paper's speedups are a hypothesis, not a threshold. The value must be sealed
  before the candidate runs, together with a measured repeat-noise floor for the
  baseline.

### Self-evaluation (from the briefing, with the license row corrected)

| Axis | Assessment |
|---|---|
| Direct Grand Prize applicability | Very high for flattening throughput and distortion |
| Effect on upstream sheet identity | Zero |
| Evidence on papyrus | None; generic large-mesh evidence only |
| License status | **Fails**: official code is academic-only with encumbered dependencies |
| Reproducibility | Low until a clean-room implementation exists |
| Integration difficulty | Medium-high (disk topology, cut handling, exact predicates) |
| Training / prediction leakage | Zero |
| Spurious-ink risk | Low if geometry metrics decide, nontrivial if flatteners are picked by how text looks |
| Proof gate it strengthens | Flattening injectivity and isometric distortion; throughput side of complete-scroll requirement |

## 2. CGAL `Mesh_smoothing_3` (re-check)

**Decision: unchanged.** DISMISS as a dependency; method stays WATCH for a clean-room
surface experiment, per
[the earlier 2026-10-06 note](2026-10-06-recto-baseline-and-cgal-watch.md). The briefing
reaches the same dependency decision on the same grounds: the package optimizes
tetrahedral volume meshes, so applying it means manufacturing a volume-mesh problem
around the sheet with no evidence that it helps sheet identity or flattening.

Newly relayed, not verified here: the package is on CGAL `main` and scheduled for CGAL
6.3; it is explicitly GPL with a GPLv3 standalone reference implementation and a separate
commercial route. The point worth keeping is the licensing one: GPL obligations must not
leak into a differently licensed ScrolIQ distribution by an accidental import. No CGAL
code is imported, linked or adapted.

## 3. Official Challenge pages (re-check)

Relayed, not re-read. The October prize page still names the spiral fitter as the
whole-scroll state of the art and invites better approaches, requires community formats
(OME-Zarr/Zarr, TIFXYZ, triangle meshes), and lists the next Progress Prize deadline as
October 31, 2026. The homepage still names densely packed and torn adjacent sheets as the
central virtual-unwrapping problem. No newer official checkpoint or VC3D release was found
that supersedes the Vesuvius-native integrations already recorded. **No change.**

## What changed in the repo

- `src/scrollq/flattening_compare.py`, `tests/test_flattening_compare.py`: the seam gate
  (commit `69c7e07`).
- [flattening-benchmark.md](../flattening-benchmark.md): promotion contract renumbered
  for the new gate, the frozen metric panel, corrected speedup wording, updated license
  decision.
- This note, the research index rows, and the deferred list.
