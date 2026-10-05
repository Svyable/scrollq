# Exploratory research index

**Status:** living research notebook. Created 2026-10-03.

This folder consolidates the high-upside ideas explored independently of the
primary Grand Prize dependency-order pipeline. It is intentionally not a second
roadmap. The main execution campaign remains authoritative; research here may
feed it only after evidence clears an explicit promotion gate.

The operating rule is simple:

- **INCLUDE** — evidence is strong enough to justify integration or the change
  closes a concrete reproducibility/evidence gap with low scientific risk.
- **EXPERIMENT FURTHER** — plausible and potentially valuable, but requires a
  frozen experiment on held-out/public data before entering the production
  path.
- **DISMISS** — redundant, leakage-prone, tautological, weakly motivated, or
  too costly relative to expected evidence. Keep the negative decision so the
  same idea is not repeatedly reintroduced under a new name.

Promotion decisions must remain ink-blind for geometry, held-out for model
evaluation, hash-bound where configuration matters, and explicit about negative
results. Nothing in this folder is allowed to block the primary Grand Prize
campaign.

## Current research portfolio

| Idea | Current status | Primary value | Next evidence |
|---|---|---|---|
| Surface-normal ink response / surface-lock profiles | EXPERIMENT FURTHER; v2 adds fixed-support component profiles + VC3D review | Physical falsification of surface-bound ink, including glyph-like component persistence | Held-out component separation across checkpoints and negative controls |
| Causal context ablation | EXPERIMENT FURTHER | Detect predictions that survive destruction of local CT evidence | Held-out central-vs-distant intervention study |
| Morphology/topography corroboration | INCLUDE as source-control framework; target transfer EXPERIMENT FURTHER | Independent physical support for ink | Resolve source scale discrepancy, then validate transfer conservatively |
| Deterministic volumetric-texture ink corroboration | WATCH; clean-room experiment only, no deposited-code reuse or training feedback | Orthogonal training-free volumetric CT texture witness for learned ink / false-positive gates | Independently implement published descriptors; preregister one held-out slab; test supported ink, supervised non-ink, derivation perturbations, and planted strokes |
| Acquisition-physics normalization and conditioning | EXPERIMENT FURTHER | Reduce cross-scan/domain shift without larger semantic context | Leave-one-acquisition-regime-out benchmark |
| Cross-parameterization inference invariance | EXPERIMENT FURTHER | Detect representation-sensitive ink predictions | Real detector + second valid UV parameterization |
| Stride/blend/seam invariance | EXPERIMENT FURTHER | Detect stitching/crop-grid false positives | Held-out nuisance sweep using existing Villa controls |
| Exact inference-configuration binding | INCLUDE, merged in PR #142 | Reproducible model evaluation | Maintain as part of the evaluation contract |
| Scored-result run identity binding | INCLUDE, merged in PR #147 | Prevent stale score files from masquerading as current results | Maintain adapter compliance |
| Independent recto coverage witnesses | EXPERIMENT FURTHER; Stage-A deletion calibration passed | Falsify omitted surface outside a declared inventory | Identity/continuity-aware unconditioned witness test; raw surface existence is insufficient |
| Fiber-texture fingerprints for sheet identity | EXPERIMENT FURTHER | Detect smooth but wrong-winding sheet switches | Adjacent-winding controls on real CT |
| Phase-preserving microtexture seam authentication | EXPERIMENT FURTHER; executable synthetic harness (`scroliq-seam-fingerprint`); real CT unmeasured | Prove a claimed patch overlap is the same physical sheet, and bound its residual displacement | Real-CT adjacent-winding benchmark with an independent-scan arm (see [protocol](../papyrus-seam-fingerprint.md)) |
| Cross-ply fiber-frame continuity | EXPERIMENT FURTHER; executable harness + synthetic splice control | Ink-blind CT-conditioned local material continuity + VC3D review | Real-CT adjacent-winding and legitimate-discontinuity benchmark |
| Structure-aware conformal uncertainty sets for surface predictions | EXPERIMENT FURTHER; queued 2026-10-04, not preregistered | Calibrated "surface localized here" vs abstain; separates boundary error from missed-sheet mass | Published `PHerc0139` surface arrays measured **binary** ([census](../../artifacts/2026-10-04-surface-prediction-value-census/README.md)), so the threshold arm is dropped and the geodesic arm needs a graded source; fix achievable per-stratum n, then preregister the dilation vs instance-level arms on untouched natural ROIs |
| Learned uncertainty head on a frozen backbone (SegWithU-style) | DEFERRED (WATCH) | Failure ranking / selective prediction for sheet switches | A frozen surface backbone with accessible features and isolated labels; none exists in this repo |
| Sealed-truth timing for blind physical controls | INCLUDE as evaluation-only tooling ([`blind-control.md`](../blind-control.md)); no run yet | Records whether truth became visible before the prediction was committed; strengthens the leakage/provenance gate | First blind run on a pinned physical benchmark |
| NIST synthetic carbonized-scroll CT | INCLUDE as evaluation-only benchmark; registered **unpinned** ([artifact](../../artifacts/2026-10-04-nist-model-scroll/README.md)) | Physical end-to-end positive control with text known before scanning | Acquire, record DOI/license evidence/byte inventory, seal truth, then one blind run |
| CSWinUNETR (thin-structure segmentation) | WATCH; no explicit license found, so no vendoring or derivation | Long-range sheet continuity through low-contrast gaps | A license, then an architecture-only A/B on identical cubes/ROIs judged on winding bridges and sheet switches |
| Learned (Siamese) patch matcher for sheet identity | DISMISS for now | Could learn weak identity cues | None until the deterministic correlation test shows physical identity information exists |
| Fiber-coordinate canonicalization as a model architecture | DISMISS for now | Possible orientation normalization | Reconsider only if an ablation inside another experiment supports it |
| CGAL `Mesh_smoothing_3` as an integration | DISMISS for current integration | Tetrahedral-mesh smoothing; inversion-barrier idea only | None; the barrier concept may inform tests |
| Global histogram matching | DISMISS | Superficial domain normalization | None; retain only as a negative control |
| Transport-only UV invariance | DISMISS | Coordinate arithmetic check | None; material-attached false positives persist too |
| Ink-selected flattening | DISMISS | Could maximize visual persistence | None; creates geometry-selection leakage |
| Immediate tile-origin backend | DISMISS pending Stage-A evidence | True crop-phase intervention | Reconsider only if stride/blend sensitivity is material |
| Generic prediction hashing layer for ink | DISMISS as redundant | Artifact provenance | Existing ink validator already binds exact evaluated arrays |
| Producer-success semantic validation (exit status is not evidence) | INCLUDE (2026-10-04) | An exit-0 geometry producer can emit nothing, a physically impossible surface, or a no-op copy | Adopt `evaluate_postconditions` in other runners |
| Recomputed spatial metadata (declared bbox never alone) | INCLUDE (2026-10-04) | Stale bounds silently discard valid geometry in prefilters and separation certificates | Run `scroliq-bbox-census` on the PHercParis4 pack |
| Configured vs effective objective audit | INCLUDE (2026-10-04) | A nonzero loss weight is not a contributing loss | Wire into model-card preflight |
| Label-coverage-conditioned surface evaluation | EXPERIMENT FURTHER (2026-10-04) | Aggregate held-out gain can live only in easy, well-labeled geometry | Real run of the frozen strata spec on committed ROIs |
| Multi-sheet consistency (Lasagna) A/B/C | EXPERIMENT FURTHER, held at WATCH (2026-10-04) | Joint stacked-sheet prior for compressed regions | Task 0 instrumentation plus three fitted-sheet measurements |
| Gaussian-splatting CT reconstruction (FaCT-GS) | DISMISS for the prize pipeline | Faster reconstruction from raw acquisitions | None; ScrolIQ holds reconstructed volumes and it adds a learned stage upstream of weak ink evidence |
| Clinical low-dose CT reconstruction (CSRCT) | DISMISS | Sparse-prior reconstruction | None; simulated-data evidence, restricted article, no permissive implementation found |


## 2026-10-04 / 2026-10-05 overnight research batch

The full deduplicated ledger for the overnight exploration is
[2026-10-04-overnight-research.md](2026-10-04-overnight-research.md). It records
all explored ideas, promotion gates, self-evaluations, absorptions into existing
experiments, and explicit dismissals.

The strongest **INCLUDE-as-evidence** decisions from that batch are:

- rendering commutativity / independent reference-render checks;
- human-input ledger and constraint-leverage accounting;
- synthetic-resolution and exact scanner-frame validation experiments;
- explanation packets for physically compromised/blank regions;
- metamorphic submission testing plus fault-injection CI;
- material-coordinate distortion overlays.

These are research/proof decisions, not claims that their implementations are
already merged. The primary dependency-order campaign remains authoritative.

## Files

- [Ink and false-positive research](ink-and-false-positive-research.md)
- [Geometry, coverage, and sheet-identity research](geometry-and-coverage-research.md)
- [Structure-aware conformal surface uncertainty](structure-aware-conformal-surface-uncertainty.md)
- [Reproducibility and proof-chain research](reproducibility-research.md)
- [Dismissed and deferred ideas](dismissed-and-deferred.md)
- [2026-10-04 / 2026-10-05 overnight exploratory research](2026-10-04-overnight-research.md)

## Existing tracked work

- [Issue #137 — ink coordinate-invariance across independent flattenings](https://github.com/Svyable/scrollq/issues/137)
- [Issue #143 — tile-phase and seam invariance for ink inference](https://github.com/Svyable/scrollq/issues/143)
- [Issue #151 — independent coverage witnesses](https://github.com/Svyable/scrollq/issues/151)
- [PR #142 — exact inference configuration binding](https://github.com/Svyable/scrollq/pull/142)
- [PR #147 — scored-result run identity binding](https://github.com/Svyable/scrollq/pull/147)

Related production/evidence documents remain in the parent `docs/` directory,
including [the Grand Prize proof campaign](../grand-prize-proof-campaign.md),
[morphology ink control](../morphology-ink-control.md),
[model evaluation](../model-evaluation.md),
[fiber audit](../fiber-audit.md), and
[the ink-blind flattening benchmark](../flattening-benchmark.md).

## Shared evaluation rubric

Every new research proposal should be judged against the same questions:

1. **Prize impact:** can it materially improve legibility, reliable coverage,
   validation credibility, automation, VC3D handoff, or reproducibility?
2. **Technical plausibility:** does a physical, geometric, statistical, or
   systems mechanism justify the experiment?
3. **Evidence burden:** what result would actually distinguish the hypothesis
   from a convenient artifact?
4. **Implementation cost:** can the hypothesis be tested without first building
   a new subsystem?
5. **Reproducibility burden:** can inputs, configuration, seeds, outputs, and
   decisions be frozen and independently reproduced?
6. **Hallucination / invalid-evaluation risk:** could the idea manufacture
   attractive text, leak target information, or make a circular claim?
7. **VC3D / pipeline compatibility:** can a successful result flow into the
   existing toolchain without a bespoke format?
8. **Surface area:** if the experiment fails, can the code be discarded cleanly?

The default is not to accumulate research machinery. A failed gate is a useful
result.
