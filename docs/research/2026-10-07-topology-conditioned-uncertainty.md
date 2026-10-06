# Topology-conditioned uncertainty (TUNE++) — 2026-10-07

| item | proposed | decided |
|---|---|---|
| TUNE++ code or retraining | WATCH | **WATCH, do not vendor**: no explicit license in the indexed repository; its README says the released topology module is a distance-transform approximation, not the paper's persistent homology |
| Post-hoc topology-conditioned uncertainty audit on frozen predictions | EXPERIMENT | **INCLUDE the machinery** ([`scroliq-topology-uncertainty`](../topology-uncertainty.md), synthetic controls only); **no real result**, verdict open |
| SILSA (latent-shape-prior 3-D generation) | DISMISS | **DISMISS**: plausible topology is not CT-supported topology; arXiv non-exclusive terms only, no software license |
| Lang3DSeg (open-vocabulary LiDAR) | DISMISS | **DISMISS**: different semantic problem, no papyrus or CT evidence |
| Cross-view OCT segmentation | WATCH/DISMISS | **WATCH/DISMISS**: its pseudo-label loop could reinforce neighbouring-sheet mistakes the audit needs independent evidence to detect |

These are the proposer's screening statements, recorded as such; the paper and
repository were not independently re-read in this repository.

Preregistered comparison: pooled and per-fixture-stratum AUROC of ensemble
disagreement vs. raw confidence on cross-roll impostors, drifted surfaces,
phantom predictions in unscanned CT and planted winding errors. Promote only if
disagreement beats confidence by the frozen rule; otherwise dismiss.
