# vesuvius-automesh: rejection-first harvest QC and prediction CT support

**Status:** research decision, 2026-10-05. This note adds two tools that run
only on synthetic data so far (`scroliq-prediction-support`,
`scroliq-harvest-qc`). It changes no scoring behaviour, frozen artifact,
training path or Grand Prize execution order.

## Source and what it claims

`vesuvius-automesh` (MIT) is listed in the official Vesuvius Challenge
community-project catalogue. Its own reports say:

- It harvests Scroll 3 surface on CPU without manual annotation. It
  seed-sweeps VC3D's `vc_grow_seg_from_seed`, renders candidates into 25 mm
  windows, applies texture/physical-surface gates, and then a separate
  topology-consistency re-gate. Only re-gate survivors count.
- Documented failures that passed the texture gates: a cross-roll trace with
  fiber-like texture strong enough to pass all four texture gates, which
  failed surface lock. Other failures: traces that drift into air, skim
  papyrus without locking to a face, or run off a page edge.
- Some grown windows overlap earlier human traces. The authors claim
  agreement only for the closest few. For the rest they explicitly decline,
  because cross-scan registration uncertainty could explain the offsets.
- The public Scroll 3 m7 surface prediction has a large fraction of positive
  voxels on masked CT == 0. These form a halo/end-cap structure that the VC3D
  tracer can follow. A broader catalogue audit reports that the same effect
  appears across all 13 Grand Prize scrolls, and that it is confined to a
  one-chunk margin around supported CT.

**None of these figures is reproduced in this repository.** Cite them as the
project's reports. ScrollQ's own exact-scan phantom measurements are in
`artifacts/2026-09-30-first-letters-support/` (`scroliq-support`).

## Decisions

| Idea | Decision | Implemented as | Next evidence |
|---|---|---|---|
| CT support as a per-voxel provenance property of every surface-prediction voxel; nothing on CT == 0 seeds geometry | **INCLUDE** (input-validity invariant) | `scroliq-prediction-support` ([doc](../prediction-support.md)): supported / ct-zero counts, distance to support, supported / halo / beyond / unresolved chunk classes, blend-margin enrichment, seed gate, source filter, built-in positive control | First dated real-volume run on one Grand Prize scan. Check that the chunk-class split reproduces the reported one-chunk confinement |
| Rejection-first harvest QC benchmarked against ScrollQ gates | **EXPERIMENT FURTHER** | `scroliq-harvest-qc` ([doc](../harvest-qc-benchmark.md)): frozen manifest, seed/evaluation separation, spec-bound decisions with `influenced_tracing: false`, frozen PROMOTE rule | Freeze a corpus of known-good regions plus wrong-wrap, cross-roll and drift controls. Collect ScrollQ and automesh decisions. Promote only a metric that closes a blind spot with zero false rejects |
| automesh texture/coherence gate as a hard universal gate | **WATCH** | LOSO rule in `scroliq-harvest-qc`: decisions on calibration scrolls never count toward PROMOTE | Thresholds derived without the evaluated scroll must stay stable across acquisition and resolution |
| Vendoring automesh code | **DEFER** | none | Only if a metric earns PROMOTE. Code is MIT; data, predictions and VC3D binaries keep their own provenance |
| CGAL smoothing (October update) | **no change** (already dismissed for integration) | none | none |
| 2026 topology-first / AI-meshing literature | **no change** | none | A papyrus-specific test stronger than the queued experiments |
| Generative/autoregressive meshing (e.g. XSpecMesh) | **DISMISS** for the prize path | none | none. Generating plausible meshes is the opposite of anchoring every sheet to measured CT |

## Leakage notes

- Prediction support: no leakage. It reads only the prediction and the
  masked CT on one grid.
- Harvest QC: medium leakage risk unless seed regions and evaluation regions
  are separated. The manifest refuses any evaluated surface that intersects a
  declared seed or calibration region of the same volume. It also refuses any
  evaluator whose decisions influenced tracing.
- Texture-reference dependency: handled by leave-one-scroll-out exclusion, not
  by trusting the threshold.
