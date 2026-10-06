# Persistent-topology planted-fault benchmark — synthetic (2026-10-06)

**Synthetic only.** The substrate is a deterministic stack of parallel sheets
with a CT-like support field. It is not scroll data. The PHerc1667 run proposed
in the research note has not been done, and no PHerc1667 patch is stored in this
repository.

- Source commit: `dc1127e3ea06fc563f439a836da11989d0b44c80`
- `benchmark.json` SHA-256: `5163371613242e7b20d1ad305644f9e49fc5f6ee730e98c4d21942b851d4b095`
- Method: `scroliq-persistent-topology-v1`

## Reproduce

```bash
scroliq-topology benchmark --seeds 10 --out benchmark.json
```

This takes about 32 seconds on one CPU (see `run.log`). The table below is
`summary` in `benchmark.json`. The per-metric counts below it come from
`rows[*].topology_fired` and `rows[*].ordinary_fired`.

## Design

**Substrate (`substrate.parameters`).**

- A 96 × 96 vertex patch with a 2-voxel step, on sheet 2 of a stack.
- Sheets are 20 voxels apart, with a 4-voxel smooth undulation.
- Support is `exp(-d² / 2·3²)` in distance to the nearest sheet. It is 0 where
  material is missing: a genuine 12 × 20 tear, which the trusted patch leaves
  invalid.
- Gaussian noise σ = 0.05 on support, and 0.25-voxel vertex jitter.

**Edits.** One of each per seed.

| edit | class | what changes |
|---|---|---|
| bridge | fault | columns past a 16-column transition move to the next winding; the transition crosses the gap |
| bridge_gentle | fault | the same with a 40-column transition (slope 0.25) |
| deleted_strip | fault | an interior 4 × 40 strip becomes invalid |
| false_fill | fault | the genuine tear is filled with surface that has no material behind it |
| island | fault | a 3 × 3 valid island inside the tear |
| orientation_reversal | benign | the grid is mirrored; the geometry is the same point set |
| narrow_neck | benign | two notches leave a 4-cell neck of fully supported papyrus |
| faint_band | benign | a 6-column band of real papyrus on the same sheet at 0.25× support |

**Metric families compared.**

- **topology:** Wasserstein-1 and bottleneck distance of the H0 and H1
  diagrams. Features with persistence below 0.1 are not compared.
- **mesh metrics:** valid fraction, components, holes, median and p99 edge
  length.
- **local support:** mean support, and the fraction of vertices with support
  below 0.5.
- **bridge witness:** a new H0 merge whose two sides each cover at least 5% of
  the patch, with persistence of at least 0.3.

**Detection rule.** An edit is detected by a family when any of its metrics
moves further from the clean patch than all 19 clean-vs-clean redraws
(fresh noise and jitter). The level is 1/20 per metric. The union over a
family's metrics is looser than that.

## Result (10 seeds)

| edit | class | topology | mesh metrics | local support | bridge witness | witness saddle inside the edit |
|---|---|---:|---:|---:|---:|---:|
| bridge | fault | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| bridge_gentle | fault | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| deleted_strip | fault | 1.0 | 1.0 | 0.2 | 0.0 | 0.0 |
| false_fill | fault | 0.9 | 1.0 | 1.0 | 0.0 | 0.0 |
| island | fault | 0.2 | 1.0 | 0.8 | 0.0 | 0.0 |
| orientation_reversal | benign | 0.0 | 0.1 | 0.0 | 0.0 | 0.0 |
| narrow_neck | benign | 0.2 | 1.0 | 0.2 | 0.0 | 0.0 |
| faint_band | benign | 1.0 | 0.0 | 1.0 | **1.0** | 1.0 |

Which metric fired, out of 10:

| edit | topology | mesh / local support |
|---|---|---|
| bridge | H0 W1 and bottleneck 10 | edge median 10, edge p99 10, low-support 10, mean 10 |
| bridge_gentle | H0 10, H1 bottleneck 10 | edge median 10, edge p99 2, low-support 10 |
| deleted_strip | H1 bottleneck 10 | holes 10, valid fraction 10 |
| false_fill | H0 W1 9 | holes 10, valid fraction 10, low-support 10 |
| island | H0 2 | components 10, valid fraction 10 |
| faint_band | H0 10, H1 bottleneck 10 | low-support 10, mean 10 |

## Reading

1. **Topology did not detect any fault that ordinary metrics missed.** In
   this paired design, mesh metrics caught every planted fault, including the
   gentle bridge, through median edge length. Topology missed most islands:
   a 3 × 3 unsupported island never rises above the persistence floor.
2. **The bridge witness localizes, but it is not specific.** For both bridge
   arms its saddle lies inside the planted transition strip in 10 of 10 seeds,
   and it never fires on the deleted strip, fill, island, neck or orientation
   edits. It also fires on **every** faint band. A legitimately thin band of
   papyrus splits the patch's support exactly as a wrong-winding bridge does.
   Topology alone cannot separate them; geometry across the saddle (does the
   surface change sheet?) would be needed.
3. **The orientation control behaves.** Topology fired 0/10. One mesh metric
   fired once, which is at the null level.
4. **The paired design favours mesh metrics.** It compares each patch with
   its own clean twin, which real QA never has. The witness is the only
   detector here that works on one unpaired patch. An unpaired comparison is
   the right next test.

## Deviations, logged

The constants and the detection rule were written before any output was read.
Three changes were made after a 3-seed pilot was read. All are reported here
and none changed a threshold.

1. **Vertex jitter added to the null.** Without it, geometry metrics had a
   null spread of exactly zero, so any change "fired". That was a flaw in the
   null, not a tuning.
2. **The ordinary family was split** into mesh metrics and local-support
   metrics, so the bridge result shows what each sees.
3. **The `bridge_gentle` arm was added** to test a smoother, more locally
   plausible bridge.

The pilot output was not kept.
