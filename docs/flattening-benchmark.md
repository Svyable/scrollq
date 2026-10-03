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
6. **p95 local isometry non-regression.** Candidate p95 symmetric stretch may
   not exceed the baseline by the predeclared ratio (default 1.0).
7. **Median local isometry non-regression.** Candidate median symmetric stretch
   may not exceed the baseline by the predeclared ratio (default 1.0).
8. **Material p95 improvement.** The default promotion threshold is at least
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
one-to-two-order-of-magnitude speedups on large meshes.

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

## What this deliberately does not prove

A `PROMOTE` verdict does **not** establish correct winding identity, CT
support, complete recto coverage, physical 1-cm scale, absence of nonlocal
self-intersections, or readable ink. It establishes only that, for one frozen
3-D triangle mesh, the candidate UV map is injective under the local foldover
test and improves the predeclared distortion metric without changing geometry.

That narrow claim is intentional: flattening can improve the submission only
after the surface itself is already physically defensible.


## Current implementation-license decision

As of 2026-10-03, the 2026 paper is the scientific method reference but no
explicit permissive software license has been verified for its implementation.
The authors' publicly indexed GIF (2022) and LMF (2025) implementations state
that use is limited to academic use. Those repositories therefore must not be
vendored into or made dependencies of the Grand Prize pipeline. Issue #114
tracks an independent MIT implementation (or a separately verified permissive
implementation) for the sealed papyrus A/B experiment.
