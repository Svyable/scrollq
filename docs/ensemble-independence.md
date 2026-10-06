# Ensemble-independence gate

`scroliq-ensemble-independence` answers two questions that a bare "five models
agree" cannot:

1. **Ancestry.** How much supervision, initialization lineage and data order do
   the members share, and how many of them can therefore be counted as
   independent witnesses?
2. **Failure ranking.** On a frozen, scroll-disjoint set, does ensemble
   disagreement rank real failures better than chance and better than ordinary
   confidence, for a cross-validation (CV) ensemble and a same-size ensemble
   built another way?

It is evidence machinery only. It never ranks readability, never selects a
checkpoint, and every report carries `promotional: false`. **There is no
real-checkpoint result yet**: the only committed numbers are the synthetic
controls in
[`artifacts/2026-10-06-ensemble-independence-synthetic/`](../artifacts/2026-10-06-ensemble-independence-synthetic/README.md).

## Why

CV members are trained on overlapping subsets of one pool. Their disagreement
mixes seed-driven variability with data-exposure effects, and their agreement
overstates independence. In a 5-fold partition each member sees 80% of the pool
and any two members share 60% of it, i.e. **75% of each member's own
supervision**; the audit counts that ensemble as **one** certified witness, not
five (`scroliq-ensemble-independence self-test`). A same-data deep ensemble
(different seeds, identical full training set) is also one witness for the
physical truth, because it shares all supervision; what it buys is independent
optimization noise. Which property matters depends on the question, so the gate
reports both rather than collapsing them.

The method follows the public description of *Lost in the Folds: When
Cross-Validation Is Not a Deep Ensemble for Uncertainty Estimation*
([arXiv:2605.18329](https://arxiv.org/pdf/2605.18329)). Its abstract reports
that deep ensembles improved calibration and failure detection while CV
ensembles *sometimes correlated more strongly with inter-rater variability*, so
neither construction is assumed better here: the comparison is symmetric and can
come out either way. **No code from the paper's repository is used, vendored or
adapted**; its license is unverified (see the
[research note](research/2026-10-06-ensemble-independence-and-conditional-risk.md)).

## Ancestry

```bash
scroliq-ensemble-independence ancestry --manifest ancestry.json --out out/ancestry.json \
  [--fail-unless-independent]
```

```json
{
  "schema": "scroliq-ensemble-ancestry-v1",
  "ensemble_id": "cv-5fold",
  "declared_kind": "cv_fold",
  "purpose": "independent_witnesses",
  "max_overlap": 0.0,
  "unit_weights": {"block-000": 1.0},
  "members": [{
    "member_id": "fold-0",
    "checkpoint_sha256": "<64 lowercase hex>",
    "training_units": ["block-001", "block-002"],
    "training_scroll_ids": ["PHerc0139"],
    "init_seed": 7,
    "data_order_seed": 7,
    "parents": [],
    "config_sha256": "<64 lowercase hex>",
    "calibration_units": ["block-900"]
  }]
}
```

`declared_kind` is `cv_fold`, `deep_ensemble`, `independent_subsets` or `other`.
`purpose` is the claim being made: `independent_witnesses` or
`deep_ensemble_uncertainty`. `max_overlap` is frozen in the manifest (default
0, strictly "no shared supervision"); `unit_weights` (for example area or voxel
counts) is optional but must cover every training unit if present.
`init_seed`, `data_order_seed`, `parents` and `config_sha256` must be present;
`null` means **unknown**, and unknown is never read as independent.
`parents` is a list of checkpoint hashes the member was initialized, distilled
or pseudo-labelled from (`[]` means trained from scratch). `calibration_units`
records any threshold/calibration data, which needs ancestry exactly like
training data.

`training_units` must be the **complete** inventory, including pretraining,
pseudo-labelling and iterative exposure, as indivisible physical blocks
(the same rule as the [shortcut audit](shortcut-audit.md)). Overlap is computed
on declared IDs; geometric overlap between differently named units is not
detected, so run the geometric overlap audit (`scroliq-provenance`) upstream.
Ancestry is declared, not extracted from checkpoint bytes.

### What the report says

- **`detected_regime`**, computed from the inventories and never from the label:
  `identical_full_set`, `disjoint_subsets`, `cv_partition` (every member
  excludes a non-empty slice and the excluded slices are mutually disjoint) or
  `partial_overlap`. Two disjoint halves are `disjoint_subsets` (2-fold CV is
  genuinely independent data). A `declared_kind` that contradicts the regime is
  flagged and can never end `independent`.
- **Pairs.** Per member pair: supervision (`shared_units`, `overlap_coefficient`
  = shared / smaller inventory, `jaccard`), `lineage` (shared declared ancestors
  and member checkpoints, transitively), `init_seed`, `data_order_seed` and
  `identical_checkpoint`. Equal seeds across different `config_sha256` count as
  distinct initializations.
- **`independent_witnesses`.** A pair is independent only if overlap is
  `<= max_overlap` and lineage, initialization and order are all measured
  distinct. `certified_count` is the exact maximum set of mutually independent
  members; `upper_bound_count` also admits pairs that are merely unverified. Five
  agreeing members with 75% shared supervision report `certified_count = 1`.
- **`deep_ensemble_uncertainty`.** Requires the same full training set
  (`identical_full_set`), one architecture, and independent lineage,
  initialization and order. A CV partition is `dependent` with reason
  `cross-validation-folds-share-supervision`. Shared pretrained parents count
  as shared lineage.
- **`status`** is the verdict for the declared `purpose`: `independent`,
  `dependent` or `unverified`. Fewer than two members is `unverified`.

## Failure ranking

```bash
scroliq-ensemble-independence evaluate --spec spec.json --out out/evaluation.json
```

The spec is the pre-registration. Freeze it, both ancestry manifests and the
unit list before any prediction is read. Paths are relative to the spec's
directory.

```json
{
  "schema": "scroliq-ensemble-evaluation-spec-v1",
  "predictions": "predictions.npz",
  "strata": ["negative_papyrus_fp", "supported_ink_miss", "ood_acquisition", "corrupted_surface"],
  "decision_threshold": 0.5,
  "alpha": 0.05,
  "min_class_count": 10,
  "bootstrap": {"seed": 0, "replicates": 2000},
  "ensembles": {
    "a": {"label": "cv_folds", "ancestry": "ancestry-a.json", "expected_regime": "cv_partition"},
    "b": {"label": "independent_seeds", "ancestry": "ancestry-b.json", "expected_regime": "identical_full_set"}
  },
  "units": [{"unit_id": "w-0001", "group_id": "block-evalA", "scroll_id": "PHercEval",
             "stratum": "negative_papyrus_fp", "truth": 0}]
}
```

`predictions.npz` (no pickle) holds `unit_ids`, and for each ensemble `a`/`b` a
`(members, units)` array of ink probabilities plus `a_members`/`b_members`
(member IDs). Rows and columns are aligned **by identifier**, not by position,
and the identifiers must match the spec and the ancestry manifests exactly. A
unit is a component or window; the adapter reduces pixels to one probability per
unit and that reduction must be frozen with the spec.

`truth` is 0 for independently established physical negatives and 1 for
independently supported ink. A unit **fails** for an ensemble when its mean
probability is on the wrong side of `decision_threshold` for its `truth`
(a false-positive component on papyrus known to be blank, a miss of
independently supported ink). Strata name the condition (the four above are the
suggested set: physical-negative false positives, missed supported ink, OOD
acquisition regions, deliberately corrupted surface placement); a corrupted
surface placement is a `truth: 0` stratum because no supported ink can exist at
the displaced location.

The run **refuses** (exit 2) if any evaluation unit, group or scroll appears in
any member's training or calibration ancestry, if the two ensembles differ in
size, if `expected_regime` is not what the inventories show, or if any input is
malformed. A frozen design that is not what you ran is not reported as a result.

### Reported per ensemble and stratum (plus `pooled`)

AUROC of mutual information and of predictive entropy against failure, their
paired difference (`auroc_mi_minus_entropy`, the incremental value over ordinary
confidence), and the area under the risk-coverage curve for both. Intervals come
from a **physical-block bootstrap** (resampling `group_id`, 1 − `alpha`
percentile). `decision` is `ranks_failures` only if the lower interval bound of
the MI AUROC exceeds 0.5; `inverted` if the upper bound is below 0.5;
otherwise `not_distinguished_from_chance`. `incremental_over_confidence` is true
only if the paired difference's lower bound exceeds 0. Strata with fewer than
`min_class_count` units in either class are `unverified` with no numbers.
`comparison_a_minus_b` gives the paired AUROC difference between the ensembles.

`pair_agreement_vs_overlap` reports the Spearman correlation between a member
pair's supervision overlap and its mean absolute prediction difference. It is
descriptive and is `unverified` when overlap is constant across pairs, which is
always the case for a symmetric CV partition; it needs a panel with unequal
overlaps.

### Reading the result

- Failure sets differ between ensembles because each ensemble's own mean
  prediction defines its failures; the paired difference compares ranking
  quality on each ensemble's own failures, not one shared label set.
- In a stratum whose units all share one `truth`, failure is a deterministic
  function of the ensemble's mean probability, so MI and entropy are tied to
  where the mean sits. Read `auroc_mi_minus_entropy` there, not the MI AUROC
  alone.
- A CV ensemble ranking failures is a finding about **disagreement as a ranking
  signal on this set**. It does not make its members independent witnesses;
  the ancestry verdict is unaffected, and the reverse also holds.
- Patches or windows are not independent specimens. Interval width reflects the
  number of `group_id` blocks, not the number of units.

### Controls

Before any verdict, `evaluate` runs a built-in control on a synthetic panel in
which one ensemble disagrees where it errs and the other errs in agreement. The
planted ranking must be detected, the agreeing errors must not be ranked, and
permuting units must produce false detections at a rate of at most 0.2 over 16
trials. If the control does not fire the report is `unverified` and carries no
ensemble results. The control's seed and replicate count are constants in the
code, not spec fields, so it cannot be shopped for a passing draw. `self-test`
runs the control plus the ancestry checks and exits 1 on any failure.

## Applying it to the ink-control arms

The [external ink-control process](external-ink-control-process.md) asks for
"an independent checkpoint/control arm". Before an ensemble, checkpoint soup or
multi-window arm is presented as independent evidence, supply an ancestry
manifest for it. Checkpoints from one training trajectory share seed, data
order and supervision by construction, and z-window predictions of one
checkpoint share its hash: declare them as members and the audit reports
`identical_checkpoint` and counts them once. Use the weight-free
`independent_witnesses.certified_count`, not the member count, whenever an
agreement count is quoted.

## Limits

- Ancestry is declared and unverified against checkpoint bytes or training logs.
- Unit-ID overlap does not detect differently named but overlapping geometry.
- The failure-ranking evaluation is only as good as the independence of the
  `truth` labels; labels derived from any member's output invalidate it.
- No real ensemble has been audited here. Next evidence needed: a CV ensemble
  and a same-size seed ensemble over the same architecture and pool with
  complete training inventories, a frozen scroll-disjoint set with
  independently supported positives and physical negatives, and the committed
  spec and manifests.

```bash
python -m pytest tests/test_ensemble_independence.py -q
```
