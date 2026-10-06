# Winding reconciliation under planted corruption — synthetic calibration

**Date:** 2026-10-06. **Tool:** `scroliq-winding-sync campaign`.
**Status:** synthetic calibration only. No human-verified winding graph has
been run yet. These numbers describe the reconcilers on exact synthetic
observations; they say nothing about any real scroll or any constraint
generator.

## What was run

Two trusted graphs of 400 nodes with exact observations `d = w_i − w_j` of
known windings (`scroliq-winding-sync synthetic --nodes 400 --seed 0`):

| Graph | Edges / node | Edges | Independent cycles | Bridges | BFS tree edges |
|---|---|---|---|---|---|
| `graph-sparse.json` | 1.40 | 560 | 161 | 93 | 399 |
| `graph-dense.json` | 2.985 | 1194 | 795 | 0 | 399 |

Each spec (`spec-*.json`) binds its graph by SHA-256. Both specs were
committed (`426f916`) before any campaign ran. They plant signed ±1 and ±2
errors at rates 0.01, 0.05, 0.10 and 0.20 into four edge classes:
`uniform`, `bridge`, `bfs_tree` and `bfs_tree_high` (tree edges whose subtree
holds ≥ 10% of the nodes). Each cell has 20 replicates, seed 20261006. Each
corrupted graph is reconciled by BFS propagation, L1 integer synchronization
and rounded least squares, and scored by gauge-aligned node accuracy against
the untouched solution.

Frozen rule: PROMOTE iff both BFS and L1 reproduce the uncorrupted solution
exactly, the mean L1 − BFS node-accuracy gain over primary cells
(uniform / bfs_tree / bfs_tree_high, rate ≥ 0.05) is ≥ 0.05, and no cell has
L1 worse than BFS by more than 0.01.

```bash
scroliq-winding-sync campaign --spec spec-sparse.json --graph graph-sparse.json --out result-sparse.json
scroliq-winding-sync campaign --spec spec-dense.json  --graph graph-dense.json  --out result-dense.json
```

Both results re-run byte-identically.

## Results

| Graph | Verdict | Mean primary gain | Worst cell (L1 − BFS) | Replicates with L1 < BFS |
|---|---|---|---|---|
| dense | **PROMOTE** | 0.6178 | +0.326 | 0 / 480 |
| sparse | **NO_MATERIAL_GAIN** | 0.0423 | −0.0093 | 174 / 640 (0 of them on bridges) |

On the dense graph, L1 keeps node accuracy at 1.000 for planted errors on
BFS-tree edges at rates up to 0.05, and at ≥ 0.864 at rate 0.20. BFS falls to
0.19–0.34 at rates ≥ 0.05.

On the sparse graph:

- Bridge errors are unrecoverable by any reconciler. L1 and BFS tie exactly
  in all 8 bridge cells, as they must, because a bridge carries no redundant
  evidence.
- Elsewhere L1 gains a little on average but loses to BFS in about a third
  of replicates. With few independent cycles, a single ±1 error on a short
  cycle has the same L1 cost wherever it is placed. The LP then picks one of
  several optimal vertices, which can be the wrong one.

## What this means

L1 synchronization is worth integrating where the trusted graph has real
redundancy. It is not a substitute for redundancy. The real-data run has to
report the graph's cyclomatic number and bridge count next to the verdict.
On a bridge-heavy annotation graph, the right action is more independent
annotations, not a different solver.
