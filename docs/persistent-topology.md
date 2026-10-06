# Persistent topology of surface patches

`scroliq-topology` asks how a patch's connectivity depends on the evidence
supporting it. It takes a TIFXYZ grid and a per-vertex support field (CT
intensity or surface probability sampled at each vertex, computed elsewhere and
named with `--support-source`). It then tracks the superlevel sets
`S_τ = {valid vertices with support ≥ τ}` as `τ` rises.

Research decision and context:
[2026-10-06 research note](research/2026-10-06-persistent-topology.md).
Synthetic benchmark:
[`artifacts/2026-10-06-persistent-topology-synthetic/`](../artifacts/2026-10-06-persistent-topology-synthetic/README.md).

## What is computed

- **H0:** connected pieces of `S_τ`, 4-connected on the grid, by the elder
  rule. A piece is born at its highest support and dies at the saddle where it
  joins an older piece.
- **H1:** holes of `S_τ`, computed through the complementary 8-connected
  sublevel filtration with an outside ring. Invalid cells are always in the
  complement, so a genuine tear is a hole that never closes (`death = null`).
- **Diagram distances:** Wasserstein-1 and bottleneck, with an L∞ ground
  metric and diagonal matching. Features with persistence below 0.1 support
  units are not compared.
- **Bridge witnesses (experimental):** an H0 merge where each side covers at
  least 5% of the valid vertices and the younger side's birth minus the saddle
  support is at least 0.3. Each witness names its saddle vertex (grid row and
  column, and XYZ) and both sides' sizes.
- **Ordinary metrics,** for comparison:
  - valid fraction, components, holes;
  - median and p99 edge length;
  - mean support, and the fraction of vertices below support 0.5.

Persistence uses a union-find written in this module, and the distances use
scipy. No new dependency was added.

## Commands

```bash
scroliq-topology measure --surface patch.tifxyz --support support.npy \
  --support-source "<how support was sampled, + commit>" --out out/topology.json
scroliq-topology benchmark --seeds 10 --out out/benchmark.json
```

`measure` binds the surface's decoded-geometry digest and the support file's
SHA-256. Its status is `unverified` when no valid vertex has finite support.
Outputs are create-only.

## What it does not show

Topology here is a **comparative witness, never a prior**. A valid papyrus
patch may legitimately have several pieces and holes, and nothing in this
module penalizes that.

A bridge witness is a review cue. On the synthetic benchmark, a legitimately
faint band of papyrus triggers it exactly as a wrong-winding bridge does. Telling
them apart needs independent geometric evidence that the surface changes
sheet across the saddle.

It does not establish sheet identity, CT-support quality, ink or readability.
