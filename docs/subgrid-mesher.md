# Subgrid Marching Tetrahedra candidate

`scroliq-subgrid-run` is a deliberately narrow adapter for testing Subgrid
Marching Tetrahedra as an **ink-blind geometry candidate**. It does not replace
VC3D/Spiral and it does not generate edge crossings.

The adapter consumes a frozen explicit `.npz` tetrahedral edge-intersection
artifact and runs the default **primal** Subgrid extractor from an exact clean
upstream checkout.

Reviewed upstream pin:

- repository: `https://github.com/hbaktash/subgrid-marching`
- commit: `bc4a04946025d9c27eab620555bf93c611cf0d73`
- license: MIT
- paper: Baktash, Gillespie & Crane, *Subgrid Marching Tetrahedra*, ACM TOG 45(4), 2026, DOI 10.1145/3811358

ScrollQ does not vendor the upstream implementation. This keeps licensing and
method identity explicit and avoids silently maintaining a fork.

## Why explicit edge intersections

The candidate must receive exactly the same frozen geometric evidence used by
the preregistered experiment. Supplying a mesh and allowing each method to
resample/reintersect it would confound the comparison: differences could come
from intersection queries rather than the meshing construction.

The upstream explicit `.npz` format contains the tetrahedral mesh and its
precomputed edge intersections. ScrollQ hashes that file before launch.

The adapter intentionally does not expose `--greedy`, numerical
`--mergeEPS`, `--noMerge`, or other algorithm-changing flags. The initial
experiment tests one fixed method, not a hyperparameter search.

## Build upstream

Use a clean checkout at the pinned commit and a headless build:

```bash
git clone --recursive https://github.com/hbaktash/subgrid-marching.git
cd subgrid-marching
git checkout bc4a04946025d9c27eab620555bf93c611cf0d73
git submodule update --init --recursive
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DSUBGRID_POLYSCOPE_VIEWER=OFF
cmake --build build -j
```

The checkout must remain clean. The built executable is outside Git provenance,
so ScrollQ records its own SHA-256 in every receipt.

## Run one frozen candidate

```bash
scroliq-subgrid-run \
  --checkout ../subgrid-marching \
  --input-npz frozen/roi-017-edge-intersections.npz \
  --output-obj out/roi-017-subgrid.obj \
  --stdout-log out/roi-017-subgrid.stdout.log \
  --stderr-log out/roi-017-subgrid.stderr.log \
  --out out/roi-017-subgrid.receipt.json
```

The adapter refuses pre-existing outputs and logs. After execution it requires:

- process exit code zero;
- a newly created OBJ;
- a non-failing `scroliq-obj` parse/audit;
- at least one vertex and triangle;
- finite positive surface area.

It records upstream commit/tree/license, executable hash, exact input hash,
output hash, logs, full OBJ audit, and any reported `non-even tets` count.
A nonzero `non-even tets` count is diagnostic rather than an automatic
failure because an intentionally open papyrus surface can legitimately create
open tetrahedral curves.

## Prize experiment rule

This receipt only licenses the candidate for comparison. It does **not** make
Subgrid the production mesher.

For a prize-relevant A/B:

1. Freeze ROI selection and edge-intersection bytes before either mesher runs.
2. Generate baseline and Subgrid candidates without viewing ink.
3. Evaluate both against exactly the same held-out geometry, winding/fiber,
   self-intersection, disconnected-patch, and flattening gates.
4. Let existing weight-free/Pareto machinery decide whether one candidate
   dominates; do not choose the result with prettier writing.
5. Only after the geometry decision is frozen may ink be rendered.

The receipt's gate is `SUBGRID_CANDIDATE_EXECUTION_INTEGRITY`; it is not a
geometry-accuracy gate.

## Provenance boundary

The Subgrid code is MIT licensed. Vesuvius tomography, annotations, and any
derived edge-intersection artifact retain their own source-data terms. The
receipt hashes the derived input but does not relicense it.

The method's self-intersection result is a property of the upstream
construction under its assumptions. ScrollQ does not substitute that theorem
for empirical held-out sheet identity, input-crossing correctness, or
integration validation.
