# Frozen-checkpoint provenance probes

`scroliq-shortcut-audit` fits disposable ridge-linear nuisance probes to exported
penultimate embeddings. It writes a create-only shortcut passport. No probe is
used for ink inference; no checkpoint or pixels are modified. This is R&D
machinery with **no real-checkpoint result yet** and no automatic promotion rule.

The probes cover fragment, scroll, acquisition, reconstruction variant, depth
convention and VC3D segment identities. Absolute xyz regression is explicitly
`not_measured` in v1. Missing labels or insufficient balanced cells are
`unverified`, never a passing audit.

```bash
scroliq-shortcut-audit --embeddings embeddings.npy --manifest samples.json \
  --checkpoint frozen-checkpoint.pt --seed 0 --ridge 1 --out out/shortcut.json
python -m pytest tests/test_shortcut_audit.py -q
```

`embeddings.npy` is a finite, nonempty N×D matrix saved without pickle. Rows must
align exactly with `samples.json`:

```json
{
  "embedding_layer": "encoder.penultimate",
  "label_evidence": "path/to/independently-verified-label-manifest.json#sha256",
  "training_domains": {
    "fragment_id": ["training-fragment"],
    "scroll_id": ["training-scroll"],
    "acquisition_id": ["training-acquisition"]
  },
  "samples": [{
    "sample_id": "patch-0001",
    "group_id": "physical-block-001",
    "probe_split": "train",
    "ink_label": 1,
    "ink_probability": 0.8,
    "fragment_id": "evaluation-fragment",
    "scroll_id": "evaluation-scroll",
    "acquisition_id": "evaluation-acquisition",
    "reconstruction_variant": "reconstruction-a",
    "depth_convention": "recto-positive",
    "segment_id": "segment-a"
  }]
}
```

This illustrative single row cannot support a probe. Each probe requires two
or more categories with at least two independently verified ink and two blank
rows per category in **each** split. Freeze the split, label evidence, ridge,
seed, layer and full extraction recipe before viewing probe results. Extract
with the frozen model in eval mode; bind normalization, input patches, model
code and label bytes using the existing provenance machinery. The CLI hashes
the exact embeddings, manifest and checkpoint bytes, but cannot establish that
the supplied embeddings actually came from that checkpoint or authenticate
labels from their reference alone.

Group IDs must combine overlapping patches, adjacent correlated patches and
repeated renders of the same physical material into indivisible physical
blocks. Train and test groups may not overlap; duplicate embedding vectors
across splits are refused. These checks cannot independently establish spatial
separation. Supply a geometric overlap audit upstream. Category IDs must be
consistent across splits; groups must be smaller than fragment/scroll for an
identity probe to have known categories on both sides. This probe split is
distinct from the ink model's training/evaluation split.

Within each split, deterministic subsampling takes the same count from every
nuisance × ink-label cell. The linear fit uses only training normalization.
The passport records selected sample IDs, balanced accuracy and the uniform
balanced chance reference. This removes the direct binary ink-prevalence
shortcut; it does not match morphology, preservation or all other confounders.
No significance threshold or permutation p-value is claimed. Patch counts are
not independent specimen counts; freeze block-level uncertainty analysis before
using a result for a model decision.

Ink error rates use a fixed probability threshold of 0.5 on all probe-test
rows in domains absent from the **declared complete** checkpoint training
inventory. The confidence/error association uses balanced probe-test rows and
the true-category linear margin, separately on held-out fragments and scrolls.
Pearson correlation is descriptive only. Constant errors or margins yield
`unverified`; empty held-out sets are `unverified`. Training inventories must
include pseudo-labeling, pretraining and iterative training exposure. A single
frozen checkpoint evaluated on excluded domains is not leave-one-domain-out
cross-validation; use one separately pinned checkpoint/passport per fold for
that claim. Region overlap checks remain mandatory even for excluded IDs.

High probe accuracy demonstrates decodable provenance in the representation.
It does **not** demonstrate that the ink head uses that information, that it
is harmful, or that the apparent ink is hallucinated. Low probe accuracy does
not establish invariance: a nonlinear shortcut can evade a linear probe.
`causal_shortcut_demonstrated` and `promotional` always remain false.

Next evidence needed: independently verified ink/blank blocks from multiple
physical and acquisition domains, their training-exclusion receipts, frozen
embeddings, and a preregistered blocked uncertainty/null protocol. Conservative
counterfactual acquisitions require separately measured preservation of ink
evidence before they can support a causal conclusion.
