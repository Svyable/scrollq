# Bad-patch growth preflight

`scroliq-growth-preflight` is a deterministic static preflight for growth trees
produced by Will Stevens' `scrollreading` pipeline before mode `c` runs the bad
patch finder.

It exists because two distinct failures can look like "mode c is slow":

1. **Combinatorial fan-out.** On tangled PHerc. 1447 growths, the original
   chain odometer continued enumerating every suffix after a prefix was already
   known to be dead. Giovanni Pellerano's output-preserving acceleration in
   [WillStevens/scrollreading#4](https://github.com/WillStevens/scrollreading/pull/4)
   changes the odometer to advance at the dead prefix and replaces the greedy
   cover's repeatedly rebuilt `std::map` with a vector. The accompanying study
   reports roughly 200x and 130x quiet-machine speedups on two large trees,
   while downstream files remained byte-identical across fifteen growth trees.
2. **Stale growth state.** Reusing a growth output folder can leave ids in
   `rel.csv` that do not correspond to the patch geometry of the current run.
   [WillStevens/scrollreading#2](https://github.com/WillStevens/scrollreading/issues/2)
   documents both the crash and the more serious silent-corruption case. A
   consumer-side guard can prevent the crash, but it cannot prove the surviving
   alignments belong to one clean growth.

For Grand Prize work, ScrolIQ therefore treats missing geometry as an
**integrity blocker**, not merely as a chain to skip.

## Usage

```bash
scroliq-growth-preflight path/to/growth/rel.csv \
  --patch-dir path/to/growth/patches \
  --out preflight.json
```

The patch-directory check mirrors the upstream loader's patch-number parsing.
The relationship graph is then augmented with reverse edges exactly as
`AugmentAlignmentMap` does.

The report includes:

- relationship rows and augmented relationship rows;
- relationship ids with no matching patch geometry;
- patch files with no relationship;
- mean / p95 / maximum augmented degree;
- exact topology-only walk-state counts for chain lengths 2 through 5;
- a bounded runtime-risk label and the thresholds that produced it;
- upstream evidence links and an explicit claim boundary.

To make a CI job reject large unpruned search spaces as well as stale geometry:

```bash
scroliq-growth-preflight growth/rel.csv --patch-dir growth/patches \
  --fail-on-runtime high --out growth-preflight.json
```

Exit status is 2 for malformed input or missing patch geometry, 1 for a selected
runtime-risk threshold, and 0 otherwise.

## What the count means

The walk-state count is deliberately cheap: it is computed in O(E × chain
length) over the augmented graph, so even a large `rel.csv` does not require
enumerating the walks themselves. It counts graph walks that an unpruned
odometer may have to traverse before geometry- and bad-patch-dependent pruning.

It is **not a runtime prediction** and it is not expected to reproduce every
number in Pellerano's benchmark. His strongest pruning happens after bad and
repeated prefixes are known inside the stage. ScrolIQ's preflight is a static
warning that can run *before* spending hours on that stage.

## Reproducibility rule for acceleration

A faster bad-patch implementation is only useful to the prize pipeline if it
preserves the delivered surface. Any local optimization should therefore be
accepted with the same style of evidence used in Pellerano's study:

- run baseline and candidate on independent fresh copies of the same growth;
- preserve deterministic ordering when parallelizing;
- compare every downstream file byte-for-byte, not only headline meshes;
- record runtime measurements separately from correctness evidence;
- keep crash guards distinct from correctness fixes;
- retain the negative result if an apparently harmless determinism change moves
  output.

The source study is published at
[evilaliv3/vesuvius-challenge-pipeline](https://github.com/evilaliv3/vesuvius-challenge-pipeline/tree/main/results/aeb2e975-badpatchfinder-acceleration).
