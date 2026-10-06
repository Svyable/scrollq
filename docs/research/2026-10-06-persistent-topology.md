# Persistent topology as a sheet-validity witness — 2026-10-06

**Decisions**

| item | proposed | decided |
|---|---|---|
| Persistent-topology planted-fault benchmark | INCLUDE as R&D benchmark | **INCLUDE**, done on synthetic: `scroliq-topology benchmark` ([result](../../artifacts/2026-10-06-persistent-topology-synthetic/README.md)) |
| Localized topological-bridge witness | EXPERIMENT FURTHER, high priority | **EXPERIMENT FURTHER**; implemented as an experimental output. It localizes perfectly on synthetic data but is **not specific** (see below) |
| Topology-stability VC3D / proof layer | INCLUDE only if the benchmark shows independent discrimination | **NOT INCLUDED**: the benchmark did not show it |
| Persistent-homology training loss | DISMISS for now | **DISMISS** for now ([dismissed-and-deferred](dismissed-and-deferred.md)) |
| Hard "papyrus must be a disk" constraint | DISMISS | **DISMISS** outright ([dismissed-and-deferred](dismissed-and-deferred.md)) |

## What already existed

ScrollQ had **static** topology, but nothing across scale:

- `scroliq-segmentation-validate` has component-count and
  largest-component-fraction gates;
- the TIFXYZ audit counts connected and enclosed cell components;
- the OBJ audit reports topology fields.

Nothing tracked how connectivity changes with evidence, and nothing localized
a bridge. The new module is therefore additive.

## The question and the answer

The proposal's narrow question was: does persistent topology detect planted
structural faults that ordinary mesh metrics miss? On the synthetic sheet
stack, **no**. Using the same null rule for every metric (exceed all 19
clean-vs-clean redraws), mesh metrics caught every planted fault:

- the 16- and 40-column wrong-winding bridges, through edge length;
- the deleted strip and the false fill, through holes and valid fraction;
- the island, through component count.

Topology caught the bridges, the deleted strip and 9 of 10 fills. It caught
only 2 of 10 islands, because a 3 × 3 unsupported island stays below the
persistence floor.

What topology does add is **localization from a single patch**. In 10 of 10
seeds, for both bridge arms, the bridge witness's saddle fell inside the planted
transition strip. It never fired on the deleted strip, fill, island,
narrow-neck or orientation edits.

It also fired on **10 of 10 faint bands**: legitimate thin papyrus on the same
sheet, with reduced support. A weakly supported connection between two
strongly supported regions is exactly the signature of a wrong-winding bridge,
and exactly the signature of faint material. Topology cannot separate them.

The orientation-reversal negative control behaved: topology fired 0 of 10.

## Caveats on the comparison

- **The paired design is generous to mesh metrics.** Each edited patch is
  compared with its own clean twin. Real QA has no twin, so a small shift in
  median edge length is not usable evidence there. The bridge witness is the
  only detector in the benchmark that operates on one unpaired patch.
- **The substrate is kind.** Its sheets are parallel, its noise is Gaussian,
  and its support is an analytic function of distance to the sheet.
  Real crushed regions will add genuine narrow, weak connections.
- **Three post-pilot changes are logged in the artifact README:** a null with
  vertex jitter, split metric families, and the gentle-bridge arm. No
  threshold changed.

## Next experiment for the bridge witness

The question the proposal itself raised: is the weak neck *also* a sheet change?

1. For each witness, fit local planes to the two sides near the saddle.
   Measure their offset along the normal, in units of the local pitch.
2. **Unpaired benchmark.** Compare the witness with and without that
   geometric condition against faint bands, narrow necks, folds and real tears,
   with no clean twin. A plain low-support-fraction threshold is the baseline.
3. **Real run (pre-registered before reading).** Trusted PHerc1667 patches with
   planted bridges, plus support sampled from the exact CT. The constants are
   frozen in `persistent_topology.py`, and the PHerc1667 patch list and hashes
   must be pinned first.

Promote the witness only if, unpaired, it separates bridges from faint bands
and necks better than the low-support baseline. A VC3D topology-stability
layer waits on that result.

## Self-evaluation (updated by the result)

| criterion | rating |
|---|---|
| prize impact | medium as independent QA, **if** the geometric condition rescues specificity |
| plausibility | high for localization; **unshown** for discrimination |
| cost | low |
| reproducibility | very high (deterministic, 32 s on one CPU) |
| hallucinated-ink risk | zero |
| VC3D compatibility | high (saddle XYZ is emitted) |
