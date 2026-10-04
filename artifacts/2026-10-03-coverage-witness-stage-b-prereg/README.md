# Coverage-witness Stage B preregistration

**Status: frozen before any Stage-B witness response is read.**

Stage A established that the independently published `surface-m7` source has
substantial real-papyrus support around six preselected PHerc0139 w035 regions.
It also exposed the problem that matters next: the same source contains
separated adjacent-sheet candidates.

Stage B therefore stops treating "surface exists" as "this is the intended
sheet."

## Improvement under test

For each frozen artificial omission:

1. remove the entire hidden TIFXYZ rectangle from the algorithm input;
2. reconstruct only an **expected corridor** by discrete harmonic continuation
   of visible collar geometry in material-grid coordinates;
3. compute continuation normals without consulting the hidden reference;
4. scan the independent `surface-m7` prediction plus exact CT along ±32 voxels
   of each continuation normal;
5. decompose the response into contiguous supported runs;
6. select a target run only inside the frozen ±8-voxel corridor;
7. separately record 12–32 voxel runs as **competing-sheet evidence**;
8. only after candidate generation is complete, reveal the hidden w035
   reference for scoring.

The six already-frozen wrong-wrap coordinates are explicit controls. They must
not be silently accepted as target coverage, and the 41×41 arm must recover
competing evidence near at least four of those six controls.

## Why harmonic continuation

It is deliberately modest. The collar supplies a geometric expectation for the
same sheet without pretending that the interpolation itself proves papyrus
exists. Only the independent prediction/CT pair can supply a witness.

The interpolation is therefore a **sheet-identity corridor**, not a coverage
claim.

## Leakage firewall

The implementation must include a metamorphic test: replacing the hidden
reference interior with arbitrary alternative coordinates while leaving the
visible collar unchanged must leave the continuation and candidate output
unchanged.

If hidden geometry affects candidate generation, the experiment is invalid.

## Frozen decision

The exact source, centers, deletion sizes, ray bands, run definition,
tolerances, and pass thresholds live in `spec.json`.

A negative result is publishable. Thresholds and centers must not be rewritten
after observation.

A positive result still does not justify a whole-scroll completeness claim. It
would justify packaging the method as a reusable experimental diagnostic and
then replicating it with a second independent witness family.
