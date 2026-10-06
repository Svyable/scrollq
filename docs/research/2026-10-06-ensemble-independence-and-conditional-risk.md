# Ensemble independence, conditional risk control and three geometry releases — 2026-10-06

**Status:** one methodology INCLUDED as executable audit machinery
(`scroliq-ensemble-independence`, synthetic controls only); one method held at
WATCH with a clean-room falsification protocol written but **not** implemented;
two geometry releases DISMISSED; one WATCH. No scoring behaviour, training
path, frozen artifact or Grand Prize execution order changes.

## What was read here and what was relayed

Claims about external work come from the 2026-10-06 maintainer briefing unless
a line says it was read here. Read here, via one web search each (titles,
abstracts and repository locations only; no repository contents and no license
text were opened):

- *Lost in the Folds: When Cross-Validation Is Not a Deep Ensemble for
  Uncertainty Estimation*, [arXiv:2605.18329](https://arxiv.org/pdf/2605.18329).
  Abstract: a 5-fold CV ensemble is compared with a 5-member deep ensemble
  (fixed training set, different seeds) on three multi-rater segmentation
  datasets; deep ensembles matched accuracy while improving calibration and
  failure detection, and CV ensembles *sometimes correlated more strongly with
  inter-rater variability*. Code location (not opened):
  `github.com/Kirscher/LostInFolds`.
- *Enhancing Image-Conditional Coverage in Segmentation: Adaptive Thresholding
  via Differentiable Miscoverage Loss* (Luo et al., ICLR 2026;
  [proceedings page](https://proceedings.iclr.cc/paper_files/paper/2026/hash/76ec4dc30e9faaf0e4b6093eaa377218-Abstract-Conference.html)),
  the paper behind COAT. A search summary describes a soft true-positive-rate
  loss for image-specific thresholds. Code location (not opened):
  `github.com/bjbbbb/Conditional-Optimization-for-Adaptive-Thresholding`.

Not verified here: every license; the briefing's metric inventory for the first
repository (ACE, BA-ECE, SPACE, NCC, GED, AURC, tests, CLI); the false-positive-
and dual-control claims for COAT (the summary read here mentions the TPR loss
only); and everything about T3lescope, SILSA and L2L-Flow. Third-party
repositories are outside this session's GitHub scope, so none was opened.

## 1. Lost in the Folds — ensemble independence

**Decision: INCLUDE the methodology as an audit; do not vendor, import or adapt
any of the paper's code.** The repository has a LICENSE file according to the
briefing, but its terms were not read here, so code reuse stays blocked until
the exact license is recorded with evidence. The audit is an independent
implementation of the idea, written from the abstract and the problem
statement.

**What was built:** [`scroliq-ensemble-independence`](../ensemble-independence.md).

- *Ancestry.* Every member declares its complete training inventory,
  calibration data, seeds, lineage and architecture; pairwise supervision overlap
  and a regime (`identical_full_set`, `disjoint_subsets`, `cv_partition`,
  `partial_overlap`) are computed from the inventories. A "five-model ensemble"
  reports its **certified independent witness count**, the exact maximum set of
  pairwise-independent members. A 5-fold CV partition reports 1.
- *Failure ranking.* On a frozen scroll-disjoint set with independently
  established truth, block-bootstrap AUROC and risk-coverage of mutual
  information and of predictive entropy against failure, for a CV ensemble and
  a same-size ensemble, with a built-in planted-signal and shuffled-null
  control that must fire first.

**Two refinements of the briefing.**

- *A same-data deep ensemble is not "more independent" in the data axis.* It
  shares 100% of its supervision, so for the question "are these independent
  witnesses of the papyrus" it is also one witness. Its advantage is independent
  optimization noise on identical data. The gate therefore keeps two verdicts
  (`deep_ensemble_uncertainty`, `independent_witnesses`) instead of one
  "independent" bit.
- *The direction is open.* The abstract reports CV disagreement sometimes tracks
  rater ambiguity better. The comparison is symmetric (`a_exceeds_b` and
  `b_exceeds_a` are both reachable) and a CV ensemble that ranks failures well
  is reported as such, without changing its witness count.

**Not implemented.** Calibration metrics (ACE, BA-ECE, SPACE) and ambiguity
metrics (NCC, GED) from the paper's setting need multi-rater pixel
distributions that no ScrolIQ evaluation set has. Only mutual information,
predictive entropy, AUROC and AURC are computed.

**State of evidence.** No real ensemble has been audited. The repository holds
no completed multi-checkpoint ink run: the zero-training `ink9um` control is
registered but "experiment not yet run". It is the first natural subject, and
by construction its soup parents and z-window views share lineage or checkpoint
identity ([how](../ensemble-independence.md#applying-it-to-the-ink-control-arms)).
Synthetic controls only:
[`artifacts/2026-10-06-ensemble-independence-synthetic/`](../../artifacts/2026-10-06-ensemble-independence-synthetic/README.md).

**Smallest real experiment and promotion gate.** Take one ink experiment with
real fold or checkpoint predictions and complete training inventories; build a
CV ensemble and a same-size, same-architecture seed ensemble (full training
set) or independent subsets, depending on the question; freeze the spec, the
manifests and a scroll-disjoint evaluation set containing physical-negative
papyrus, independently supported ink, an OOD acquisition region and a
deliberately displaced-surface stratum; run `evaluate`. The proof question is
"does disagreement rank real Vesuvius failures, or merely reflect fold
membership?". A pass strengthens the *ensemble-independence / uncertainty-
validity* gate by showing that a particular disagreement signal is informative
on that set. It never turns agreement into evidence of ink, and a correlated
ensemble relaxes none of the physical requirements (entire recto surface,
low-distortion meshes, letter-by-letter legibility, no overlap with training).

**Self-evaluation:** applicability to the Grand Prize high; expected raw ink
gain low-medium, audit value high; integration difficulty low (stdlib, NumPy
and SciPy only, no new dependency); compute tiny for the audit, medium if
independent models must be trained; training leakage is exactly what the gate
measures; prediction leakage zero on a sealed scroll. The failure modes are the
declared-versus-true ancestry gap and unit-ID overlap that misses geometric
overlap; both are listed in the report's `limits`.

## 2. COAT — conditional risk control

**Decision: WATCH. Incorporate no code.** The briefing reports no LICENSE file
in the repository listing; that was not checked here, and none of the
repository was read.

**The idea survives without the code.** A threshold calibrated across easy and
hard papyrus can give an acceptable aggregate false-positive rate while
individual windows are catastrophic. That is testable with no learned
threshold:

1. Freeze the production threshold and a set of sealed physical-negative
   windows and independently supported positive windows.
2. Compute the FPR on each negative window separately and the FNR on each
   positive window separately.
3. Compare the distributions with the aggregate FPR/FNR: report quantiles, the
   worst window, and the fraction of windows exceeding a budget frozen before
   inspection, with a physical-block bootstrap for all of them.
4. Only if the tails are catastrophic while the aggregate looks safe, test an
   adaptive threshold, clean-room, against that same frozen baseline.

**Gate it strengthens:** local false-positive risk / conditional calibration.

**Rules carried over from the ensemble gate.**

- Calibration data is training data. A threshold predictor can overfit scroll
  identity or acquisition characteristics, so every calibration set needs the
  same ancestry record as a model (`calibration_units` in the ancestry
  manifest already causes `evaluate` to refuse overlap).
- Adaptive thresholds must never be optimized on regions later reported as
  discoveries.
- Leave-one-scroll-out evaluation; abstention is reported, never filled.

**Status:** step 1-3 protocol only. Not implemented, not preregistered, no data
read. A separate change would add it as its own tool.

**Self-evaluation:** applicability very high; impact medium-high; integration
difficulty low for the audit, medium for learned thresholds; compute tiny;
leakage risk medium (threshold predictors overfit identity); hallucinated-ink
risk potentially lower, but higher if thresholds are tuned on reported regions.

## 3. October geometry releases

All three are relayed from the briefing and were not read here.

| Release | Decision | Reason |
|---|---|---|
| T3lescope (2026-10-02), coarse-to-fine generative mesh reconstruction | **DISMISS** for geometry | Its strength is learned completion of sparsely observed surfaces. Plausibly completing an unobserved sheet is the wrong inductive behaviour here: geometry needs CT support, not a prior able to invent structure. No permissive, papyrus-relevant implementation evidence. |
| SILSA (2026-10-01), topology-preserving generative representation | **DISMISS** | The available material carries only the arXiv nonexclusive-distribution license, not a reusable implementation license. Topology preserved inside a generated prior is not preservation of independently measured papyrus topology. |
| L2L-Flow (MICCAI 2026), latent-to-latent stochastic volumetric segmentation | **WATCH** | Sampling several plausible sheet segmentations and asking where winding or sheet identity changes could expose surface ambiguity, with reported efficiency gains. No permissive license is exposed, and medical-domain performance is not evidence for compressed papyrus. |

These extend the generative-meshing DISMISS recorded on 2026-10-05
([automesh note](2026-10-05-automesh-harvest-qc.md)) and the structure-aware
conformal surface-uncertainty entry
([note](structure-aware-conformal-surface-uncertainty.md)), where multi-sample
ambiguity would enter.

## Process note

License review came before technical enthusiasm again, and two decisions rest
on a license nobody here has read. The audit exists because the methodology is
implementable without the code, not because the code was cleared.
