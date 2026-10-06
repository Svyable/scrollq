# Winding reconciliation and external constraint calibration

Two separate questions decide whether a winding-constraint graph can anchor
whole-scroll identity:

1. **Reconciliation.** Given noisy pairwise observations `d_ij ≈ w_i − w_j`,
   which integer windings best explain them? This is `scroliq-winding-sync`.
2. **Measurement.** Are the observations themselves right? This is
   `scroliq-constraint-gauge`.

A good answer to (1) never implies a good answer to (2). A reconciler
faithfully reproduces whatever its inputs say, and a generator can be
internally consistent and still wrong.

## `scroliq-winding-sync`

The graph is a JSON list of edges `{edge_id, i, j, d, weight?}` with integer
`d = w_i − w_j`. Fields whose names start an `ink` word are refused, so ink
cannot reach the reconciler.

| Method | What it does |
|---|---|
| `bfs` | Reference BFS spanning-tree propagation. Root is the smallest node id; tree edges are taken in edge-id order; redundant edges are ignored. A reference implementation, not upstream code |
| `l1` | Minimises `Σ weight · |w_i − w_j − d|` with one gauge-fixed root per component. The system is totally unimodular, so a vertex LP optimum is integral. HiGHS dual simplex returns a vertex, and the result is *checked* for integrality; a non-integral optimum fails closed rather than being rounded |
| `l2_rounded` | Least squares, then rounding; a baseline only |

`campaign` is the frozen experiment: plant ±k errors into a trusted graph
bound by hash and score the reconcilers on node identity. See the rule and
the first synthetic calibration in
[`artifacts/2026-10-06-winding-sync-synthetic/`](../artifacts/2026-10-06-winding-sync-synthetic/README.md).
That calibration gives PROMOTE on a redundant graph and NO_MATERIAL_GAIN on a
bridge-heavy one. On the bridge-heavy graph, L1 loses to BFS in about a third
of replicates because single errors on short cycles leave L1 with tied optima.

```bash
scroliq-winding-sync self-test
scroliq-winding-sync graph-hash --graph trusted-graph.json   # bind in the spec
scroliq-winding-sync campaign --spec spec.json --graph trusted-graph.json --out result.json
scroliq-winding-sync solve --graph graph.json --method l1 --out windings.json
```

**Next evidence:** a human-verified winding graph already consumed by
Villa/ScrollQ, frozen in a dated artifact with its cyclomatic number and
bridge count reported. Its clean solution must be cycle-consistent; if not,
the campaign reports `UNVERIFIED` rather than inventing a truth.

## `scroliq-constraint-gauge`

The rule is that internal consistency is not external correctness. Any
producer is scored the same way: human annotation, a ScrollQ generator,
`winding-sync`'s detector, a Villa generator, or a reconciled solution.

1. `freeze` commits a sealed truth file of verified pairs
   `{a, b, truth_delta}` by hash. Only the hash, the pair count and the
   thresholds are published.
2. Each producer submits pairwise `constraints` (with optional `confidence`)
   or a node `windings` map, bound to the spec hash. Any `internal_metrics`
   are copied into the report as `internal_metrics_not_evidence`.
3. `score` reveals the truth (hash-checked) and reports coverage, exact and
   within-one agreement, mean, median and signed residual, and confidence
   calibration per frozen bin. For constraint submissions it also reports the
   producer's own L1 internal consistency next to its external agreement.

| Status | Meaning |
|---|---|
| `admissible` | scored ≥ `min_scored`, coverage ≥ `min_coverage`, exact ≥ `min_exact` |
| `not_admissible` | scored, but below a floor |
| `unverified` | no submitted constraint touches a truth pair |

Declared confidence `earns_weight` only if every bin holds ≥ `min_per_bin`
scored constraints, exact agreement never falls as confidence rises, and the
top bin beats the bottom bin by ≥ `calibration_margin`. Otherwise it is
`not_calibrated` or `unverified`, and confidence must be ignored.

The built-in control includes a "smoothed" producer that halves the winding
range. Its internal consistency is 1.0 and its external exact agreement is
0.037, and it is ruled `not_admissible`.

```bash
scroliq-constraint-gauge self-test
scroliq-constraint-gauge freeze --truth sealed-truth.json --benchmark-id ID --frozen-at YYYY-MM-DD --out spec.json
scroliq-constraint-gauge score --spec spec.json --truth sealed-truth.json \
  --producer human.json --producer winding-sync-auto.json --producer l1-solution.json --out report.json
```

Timing caveat: the gauge checks that a submission names the frozen spec and
that the revealed truth matches its hash. It cannot prove a producer never
saw the truth file; keep the truth file out of reach until scoring.
