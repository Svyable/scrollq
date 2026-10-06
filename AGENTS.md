# AGENTS.md — ScrolIQ

Instructions for AI coding agents working in this repo. Humans: the
contributing guide lives at `.github/CONTRIBUTING.md`.

## What this is

ScrolIQ is a Challenge-aligned diagnostic layer for Vesuvius scroll data and
virtual unwrapping. The Python package and existing CLI names remain `scrollq`
for compatibility.

The current implemented core still scores sampled real level-0 voxels 0–100 on
*scan health* (signal presence, texture/gradient energy, dynamic range,
saturation penalty, dead-slice scan). That number is deliberately narrow: it
must never be presented as readability, surface quality, ink quality, or Grand
Prize readiness.

`scroliq-passport` organizes current evidence around the Vesuvius Challenge
2026 Open Problems and leaves unmeasured stages explicitly `unknown`.
Companion: [zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit)
("don't train on lies" — corruption detection). `scrollq-health` unifies
integrity and scan quality into TRAIN / CAUTION / DO NOT TRAIN.
`scrollq-grand-prize` applies the scores to the 13 Grand Prize volumes as a
weight-free Pareto frontier (triage, not a readability claim).

## Layout

- `src/scrollq/` — the package; each module with a `main()` is a console
  script declared in `pyproject.toml`
  - `score.py` — scoring core: `score_volume(base_url, root, samples, rotate,
    spread, exclude)`, weights, shard sampling → `scrollq-score` (via `cli.py`)
  - `metrics.py` — per-chunk metrics from a decoded uint8 chunk
  - `health.py` — unified health report (imports `zpa.*` from the companion)
    → `scrollq-health`
  - `leaderboard.py` → `scrollq-leaderboard` (renders `docs/index.html`)
  - `coverage.py` → `scrollq-coverage` (join scores with ink-label roots)
  - `grand_prize.py` → `scrollq-grand-prize`: dated target manifests
    (`DEFAULT_MANIFEST`, `FIRST_LETTERS_MANIFEST` via `--prize`, `as_of`,
    per-prize `required_assets`), Pareto frontier, `--run` for stability
    reports, optional surface-support sensitivity axis
  - `support.py` → `scroliq-support`: exact-scan surface-prediction CT support
    (phantom = prediction > 127 on masked CT == 0) with bootstrap 95% CI
  - `model_eval.py` → `scroliq-eval`: task-neutral model registry/evaluation envelope; fail-closed provenance, held-out overlap checks, deterministic bootstrap CIs, and region failure accounting. Contracts live in `models/` and `docs/model-evaluation.md`
  - `segmentation_validation.py` → `scroliq-segmentation-validate`: trusted blind TIFXYZ surface scorer using preregistered bidirectional coverage, salted hidden-truth commitments, exact vertex distances, topology gates, and common `scroliq-eval` region results
  - `segmentation_uncertainty.py` → `scroliq-segmentation-uq`: finite-sample split-conformal audit that keeps boundary error separate from complete disconnected-component omission and rejects vacuous bounds
  - `sheetness_campaign.py` → `scroliq-sheetness-campaign`: freezes dispersed per-probe CT boxes, exact Hessian-engine bytes/config, and one campaign-level decision rule before inference; seals one provenance-bound v3 spec per cutout and aggregates all frozen groups without dropping failures
  - `blind_control.py` → `scroliq-blind-control`: benchmark manifests with `development_truth` / `sealed_truth` / `training_eligible`, a create-only seal → prediction-commitment → anchor → reveal → report chain, and the ordering verdict the passport carries as its `blind_control` stage; ordering and custody only, never a score. `docs/blind-control.md`; the registered NIST benchmark is unpinned, so it refuses to commit until its pins exist
  - evidence layers, each its own `scroliq-*` script: `passport.py`,
    `scan_map.py`, `provenance.py`, `recto_coverage.py`, `tifxyz_audit.py`
    (`scroliq-mesh`), `ink_audit.py`, `ink_validation.py`, `normal_response.py`,
    `winding_audit.py`; `normal_response.py` → `scroliq-normal-response` for the
    frozen held-out surface-normal falsification sweep, including fixed-support
    predicted-component depth profiles and optional VC3D review coordinates;
    `geometry_probe.py` → `scrollq-geometry-probe`; `fiber_audit.py` →
    `scroliq-fiber`; `fiber_frame.py` → `scroliq-fiber-frame` for the
    experimental ink-blind cross-ply CT continuity diagnostic
  - `vc3d_run_guard.py` → `scroliq-vc3d-run-guard`: create-only external-command receipt; an exit-zero run is `PRODUCER_SEMANTIC_FAILURE` unless the new TIFXYZ also passes vertex/quad/recomputed-area, voxel-spacing (vs a hashed `--volume-meta`), extent/bbox-consistency and output-differs-from-input (decoded-geometry digest) gates; unexercised gates are listed, not passed; optional exact-volume CT preflight binding
  - `prediction_support.py` → `scroliq-prediction-support`: per-voxel preflight before any tracer; pred_positive ∩ ct_supported vs ∩ ct_zero, distance to CT support, supported/halo/beyond/unresolved prediction-chunk classes, blend-margin enrichment, seed gate and source filter; built-in positive control, no positives is `unverified`. `docs/prediction-support.md`
  - `harvest_qc_benchmark.py` → `scroliq-harvest-qc`: frozen manifest of verified-good + invalid (wrong-wrap/cross-roll/drift/…) surfaces, seed/evaluation region separation, spec-bound decisions with `influenced_tracing: false`; PROMOTE only a metric that closes a ScrollQ blind spot with zero false rejects outside its calibration scrolls. Evaluation only. `docs/harvest-qc-benchmark.md`
  - `spiral_cloud.py` → `scroliq-spiral-cloud`: execution guard rails for the frozen PHerc0826 Spiral run on one L4 — `check` (frozen manifest in `artifacts/2026-10-05-spiral-cloud-plan/` vs recipe contract, storage floors, script hashes), `plan` (gcloud argv only, executes nothing), on-VM `disk-floor`, `gpu-gate`, `fetch-lasagna`, `smoke-recipe`/`smoke-verdict`, `compare-preflight`, `bundle`. VM scripts live in `cloud/spiral-gcp/` and are hash-pinned by the manifest — edit a script, update its hash. Smoke receipts are `promotional: false` and refused by reproduction-check/export. `docs/spiral-cloud-execution.md`
  - `winding_sync.py` → `scroliq-winding-sync`: reconciles trusted pairwise winding observations (d = w_i − w_j) by BFS propagation vs integer L1 synchronization (TU LP, integrality checked, never rounded) vs rounded L2; `campaign` plants frozen ±k errors into uniform/bridge/BFS-tree edges of a hash-bound graph and PROMOTEs L1 only if it reproduces the clean solution, gains materially and is never worse beyond tolerance. Refuses ink fields. Synthetic calibration only (`artifacts/2026-10-06-winding-sync-synthetic/`: dense PROMOTE, sparse NO_MATERIAL_GAIN). `docs/winding-sync.md`
  - `constraint_gauge.py` → `scroliq-constraint-gauge`: producer-neutral external scoring of winding constraints against sealed human-verified pairs (coverage, exact/within-1, residuals, per-bin confidence calibration); internal metrics are recorded as not evidence
  - `render_noise.py` → `scroliq-render-noise`: passport `measurement_noise` block; a rendered small-effect claim must exceed k × the repeat-render noise floor of the unchanged surface, with the determinism mode declared. `docs/render-noise.md`
  - `crop_invariance.py` → `scroliq-crop-invariance`: frozen dense-embedding fixture of the same voxels under shifted crop frames; held-out crop-position R², same-voxel cosine, NN-identity stability and sheet/ink separation before vs after a calibration-fitted position-debiasing transform. PROMOTE only if dependence falls with no loss of discrimination; missing embeddings are `unavailable_input`, not failed. Synthetic controls only, no real Dinovol result. `docs/crop-invariance.md`
  - `bbox_census.py` → `scroliq-bbox-census`: recomputes bounds over a TIFXYZ patch pack, compares with declared `meta.json` bboxes, counts vertices a declared-bbox filter would lose; positive control built in, empty census is `unverified`
  - `objective_audit.py` → `scroliq-objective-audit`: configured-vs-effective objective passport audit (+ `ObjectiveTracker`); fails closed on never-evaluated/always-zero/non-finite/ungradiented claimed terms and on ablation arms that were not ablated
  - `geometry_strata.py` → `scroliq-geometry-strata`: preregistered geometry-stratified, label-coverage-conditioned surface evaluation gate (`measure` derives curvature/tilt; `evaluate` applies the frozen rule). Machinery only; no real-data result yet
  - `persistence.py` / `persistence_audit.py` / `persistence_controls.py` → `scroliq-persistence`: threshold-persistence audit of frozen ink predictions. `persistence.py` is a leaf engine (exact H0/H1 persistence on the rank-parameterised superlevel filtration; features are functions of integer levels only, so they are bitwise invariant to injective monotone remaps); `persistence_audit.py` has `measure` (hash-bound manifest with a selection contract) / `evaluate` (frozen leave-one-domain-out rule over the `all` and `within_region` scopes) / `controls`; the spec is pinned as a literal `FROZEN_SPEC_SHA256`. Synthetic controls only, no real-data result. `docs/threshold-persistence.md`
  - `winding_conservation.py` → `scroliq-winding-conservation`: layer-count, pitch and
    identity-continuity invariants of a stitched winding solution on (θ, z) cells;
    `calibrate` plants delete/duplicate/merge/switch defects over an extent ladder
    with a same-footprint null; `measure` runs a built-in positive control
    (`unverified` if it does not fire). Synthetic calibration only so far
    (`artifacts/2026-10-05-winding-conservation-synthetic/`)
  - `ink_passport.py` → `scroliq-ink-passport`: one record per ink component / reviewer
    letter region binding UV extent, mesh-mapped level-0 CT coordinates, prediction +
    surface + checkpoint hashes, point-by-point training-region exclusion (provenance
    box format), raw score and optional independent relief support; missing evidence
    stays `unknown`/`not-measured`. Evidence only, never an ink verdict
  - `shortcut_audit.py` → `scroliq-shortcut-audit`: frozen-embedding, balanced linear nuisance probes and create-only shortcut passports; declared physical-group separation and held-out training-domain exclusions. Diagnostic only, no real checkpoint result; absolute xyz unmeasured. `docs/shortcut-audit.md`
  - `ensemble_independence.py` → `scroliq-ensemble-independence`: declared training-ancestry audit (pairwise supervision overlap, lineage/seed sharing, detected CV-partition vs same-data vs disjoint regime, exact certified independent-witness count; unknown is never independent) and a scroll-disjoint failure-ranking comparison (block-bootstrap AUROC/AURC of mutual information vs entropy) gated by a built-in planted-signal/null control whose seed is a code constant. Evidence only; no real-ensemble result yet. `docs/ensemble-independence.md`
  - `reconstruction_sensitivity.py` → `scroliq-reconstruction-sensitivity`: audit of which ink and geometry claims survive a preregistered family of reconstructions (official + classical inverse variants) and bounded calibration perturbations over one ROI with projections, geometry and pipeline held fixed; per reference ink component persistence, surface displacement along the normal, neighbouring-sheet separation, fibre orientation, ink position along the normal, known-negative detections. Fails closed on ink in variant selection, mismatched family fingerprints, out-of-bound or unbounded perturbations, undeclared/incomplete dependency licence manifests (copyleft backends such as ASTRA are classified, never inferred from the framework); failed variants are listed, no-op variants cannot be stable; a built-in planted/null/no-op control gates every verdict. Reads frozen arrays only, imports no tomography package; synthetic controls only, no reconstruction run. `docs/reconstruction-sensitivity.md`
  - `topology_uncertainty.py` → `scroliq-topology-uncertainty`: post-hoc audit of frozen ensemble surface predictions — does member disagreement (MI) rank cross-roll/drift/unscanned-CT/winding-error fixtures better than predictive-entropy confidence? Block-bootstrap AUROC, frozen PROMOTE/DISMISS/UNVERIFIED rule, built-in planted/confident-error/null control with code-constant seed; reuses `ensemble_independence` ancestry and `persistent_topology`. No TUNE++ code (unlicensed), no retraining, synthetic controls only. `docs/topology-uncertainty.md`
  - `persistent_topology.py` → `scroliq-topology`: H0/H1 superlevel persistence of a
    per-vertex support field on a TIFXYZ grid (own union-find, scipy distances),
    W1/bottleneck diagram distances, experimental bridge witnesses; `benchmark`
    plants faults in a synthetic sheet stack. Synthetic result: no fault missed by
    paired mesh metrics; witness localizes bridges but fires on faint bands too
    (`artifacts/2026-10-06-persistent-topology-synthetic/`)
  - `bucket.py` — leaf helpers for the open bucket's metadata (constants, gz-aware
    JSON load, stable seeds); imports nothing else from `scrollq`
  - `omezarr.py` — strict, dependency-light reader for the open S3 bucket's
    OME-Zarr **v2** volumes (the scorer itself reads volcomp v3 from
    dl.ash2txt.org); `registration.py` — `transform.json` direction/axis-order
    inference from landmark residuals
  - `protocol_pairs.py` — `scroliq-pairs`: pre-registered test of whether scan
    metrics recover the documented protocol ordering on registered rescans
  - `prize_manifest.py` — `scroliq-manifest`: Grand Prize / First Letters
    manifests derived from pinned official eligibility + bucket index; checks
    the built-in manifests for drift
  - `chunk_audit.py` — `scroliq-chunk-audit`: declared-vs-stored chunk sizes
- `scripts/` fiber campaigns (run in Actions; data hosts may be unreachable
  locally): `fiber_corpus_campaign.py` / `fiber_scroll_census.py` (fail-closed
  censuses with positive controls), `fiber_span_test.py`, `fiber_gap_rule_eval.py`,
  `paris4_fiber_binding.py`, `paris4_fiber_ct_support.py`, `paris4_fiber_ct_direction.py`.
  Pre-registered runners execute only specs listed in their `FROZEN_SPECS`
  hash table; CI results are committed create-only by `scripts/ci_commit_result.sh`
- `tests/` — pytest suite; keep it green. `test_surface_independence.py` guards the
  import graph: the October surfaces (bucket helpers, OME-Zarr reader +
  registration, chunk audit, prize manifests, protocol pairs) must stay
  independently revertable
- `artifacts/` — dated campaign outputs, the evidence behind every published
  number. The published campaign is `2026-09-30-scrollq-n24-dense/` (stability:
  `2026-09-30-resampling-stability/`, Grand Prize:
  `2026-09-30-grand-prize-qualifier-n24-dense/`); the 4- and 12-sample
  directories are superseded but kept frozen
- `docs/` — GitHub Pages: leaderboard (`index.html`), September writeup,
  Grand Prize protocol/provenance specs, `ink-validation.md`
- `volumes.txt` — 64 dl.ash2txt.org volcomp volume roots
- `requirements-ci.txt` — pins the companion to an immutable commit, plus
  `pytest` and `build`

## Commands

Use `.venv/bin/<tool>` or an activated venv. Setup:
`pip install -r requirements-ci.txt && pip install -e .`

```bash
scrollq-score --volumes volumes.txt --samples 24 --spread 5 --workers 8 [--rotate N] --out-dir out/
scrollq-leaderboard --in out/volumes.json [--coverage out/coverage.json] [--rank-bands artifacts/2026-10-stability-v2/stability-v2.json] --out out/index.html
scrollq-coverage --s3-roots <roots.jsonl> --volumes out/volumes.json --out out/coverage.json
scrollq-health --root <dl volume root>
scrollq-grand-prize --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  [--surface-support artifacts/2026-09-30-grand-prize-qualifier/surface_support_external.json] \
  --out out/grand-prize-targets.json
python -m pytest tests/ -q
scroliq-pairs --list --out out/discovery.json          # registered rescan pairs
scroliq-manifest --help                                # derive prize manifests
scroliq-chunk-audit --index <metadata.min.json[.gz]> --out out/audit.json
scroliq-segmentation-uq --help                      # structural boundary/component UQ gate
scroliq-blind-control --help                          # sealed-truth timing for blind physical controls
scroliq-vc3d-run-guard --help                       # exit code + semantic TIFXYZ postconditions
scroliq-bbox-census --help                          # declared vs recomputed bbox over a patch pack
scroliq-objective-audit --help                      # configured vs effective objective
scroliq-geometry-strata --help                      # geometry-stratified evaluation gate
scroliq-prediction-support --self-test              # CT-support preflight before a prediction seeds geometry
scroliq-harvest-qc self-test                        # independent harvest-QC benchmark vs ScrollQ gates
scroliq-persistence --help                          # threshold-persistence audit (measure / evaluate / controls)
scroliq-reconstruction-sensitivity self-test        # reconstruction-family / calibration sensitivity controls
scroliq-winding-conservation --help                 # layer-count / pitch / continuity QC
scroliq-winding-sync self-test                      # L1 vs BFS winding reconciliation under planted errors
scroliq-constraint-gauge self-test                  # external calibration of winding-constraint producers
scroliq-render-noise --self-test                    # flatten/render noise floor for small-effect claims
scroliq-crop-invariance --self-test                 # crop-coordinate invariance of dense embeddings
scroliq-ink-passport --help                         # per-component ink evidence passport
scroliq-topology --help                             # persistent topology + bridge witnesses
scroliq-topology-uncertainty self-test              # disagreement vs confidence on structural failures
```

`scrollq-score` and `scrollq-health` hit the network (dl.ash2txt.org); tests
do not. Write scratch output to `out/` (untracked) or a temp dir, never over
files in `artifacts/`.

CI (`.github/workflows/ci.yml`, Python 3.11 + 3.12) builds the sdist and wheel,
installs the *wheel*, runs `pip check`, the tests, then `--help` on every
console script. A new entry point must therefore be declared in
`pyproject.toml` and answer `--help` without network access or required args.

## Hard-won lessons (do not re-learn)

1. **Shard sampling must spread per-dimension.** Flat-index spread of shard
   coordinates degenerates to an edge line on non-cubic grids and samples
   masked cells. `score.py` already does per-dimension candidate spread —
   keep it that way.
2. **The dead-slice detector is strict for a reason.** The rule: a densely
   populated chunk containing a zero plane whose *both neighbors* are densely
   populated. A naive "any zero plane" rule false-positives on legitimate mask
   geometry. Verified result on the corpus: zero dead slices. Do not loosen it.
3. **Missing ≠ empty.** Unstored masked-background chunks are absent from the
   shard index — that is legitimate, not a defect. Never report them as empty.
4. **Scores are sample-dependent by design.** Resampling stability is the
   quality gate: Spearman ρ ≥ 0.85, mean |Δ| small, top-10 overlap high.
   Current published measurement 2026-09-30 (`artifacts/2026-09-30-resampling-stability/stability-n24-dense-prov.json`,
   `bin/stability.py`, 24 samples, 5×5×5 grid, rotate=0 vs 13 = disjoint *candidate order*):
   ρ = 0.7944, mean |Δ| = 4.195, overlap 7/10 — **below the gate**, and an
   upper bound (only 2/64 volumes read disjoint chunks). The earlier n=4 run
   gave ρ = 0.76, mean |Δ| = 7.4, overlap 6/10. Present rankings as bands,
   not precise orders. (A rotate=1 resample gives ρ = 0.99 — it re-uses 3 of 4 shards,
   so it measures the resample, not the score. Don't cite it.)
   **Disjoint candidate order ≠ disjoint chunks read**: the sampling loop
   scans all candidates until N chunks decode, so on sparse volumes both
   rotations re-read the same present shards. `score_volume()` now records
   per-chunk provenance (`sample_provenance` with stable
   `shard_key#inner_flat` identities) and `bin/stability.py` reports the
   actual decoded-identity overlap per volume.
   Earlier published numbers (ρ = 0.876, |Δ| = 3.07, 8/10) *recompute exactly*
   from `artifacts/2026-09-30-scrollq/volumes.json` vs `volumes_rot9.json`
   (re-checked 2026-10-01), but those files predate the `sampling` provenance
   field: how the second sample was produced and how disjoint it was are
   unrecorded. They were replaced 2026-09-30 as unverifiable, not as
   irreproducible. Don't cite them as a stability measurement.
   A second deterministic sample is `scrollq-score --rotate N`; commit the
   full output, including its `sampling` provenance.
   **Truly-disjoint measurement 2026-10-01**
   (`artifacts/2026-10-01-truly-disjoint/`, two-phase exclusion protocol):
   64/64 volumes with zero chunk overlap (mean Jaccard 0.0), ρ = **0.63**,
   mean |Δ| = 7.95, top-10 4/10 — **below the gate**. This is the honest
   number: 24-chunk means from heterogeneous volumes are noisy, and the
   leaderboard is a triage band, not a precise 1-to-64 ranking. Largest
   mover: PHerc0841, 31.4 → 75.1 (Δ=43.7). 13 sparse volumes could not
   supply 24 fresh chunks in phase 2 (visible via `excluded_chunks`).
   (The claim that the frontier PHerc0813 + PHerc1447 was robust to this noise
   did not survive the v2 design; see below.)
   **Stability v2, 2026-10-01** (pre-registered: `docs/stability-v2-protocol.md`,
   `artifacts/2026-10-stability-v2/`): the default x-major candidate order lets a
   24-chunk sample sit in one or two x-slabs. With a balanced, interleaved order
   (`score_volume(order="balanced", part=(2, i))`, spread 7, 48 chunks per run),
   the B − A shift vanishes and noise drops to the iid level, but Spearman
   ρ = 0.750 on 48 eligible volumes — **FAIL**, so the leaderboard shows rank
   bands (`scrollq-leaderboard --rank-bands`). Pearson is 0.911: scores are
   reliable, ranks among close volumes are not. September scores differ from the
   v2 pooled score by 6.9 points on average (PHerc0813 −6.0). Re-derived from the
   v2 scores on 2026-10-04 (`artifacts/2026-10-04-prize-frontier-v2/`,
   `bin/prize_frontier_v2.py`): **PHerc0813 is off both frontiers** in every v2
   view. The only robust members (on pooled, run A and run B frontiers) are
   **PHerc1447** (Grand Prize) and **PHerc0800** (First Letters), both held there
   by segment count. The "best segment-free volume" slot is a band within noise,
   not a pick. PHerc1545 has an incomplete v2 sample and stays off.
5. **Weights are a judgment call, published with every score.** Changing them
   is fine; hiding them is not. Update the September page when they change.
6. **Sampling provenance travels with the score.** Every result carries
   `sampling` (requested/decoded/complete, missing vs. failed shards). A
   partial sample must stay marked incomplete — never present it as a full one.
7. **Grand Prize matching is exact-volume, fail-closed.** Match only the
   prize-listed volume ID. Never substitute another scan of the same scroll
   (PHerc1203's 2.403 µm scan is *not* its eligible 9.362 µm volume). Missing
   quality is never put on the frontier, and surface-support evidence is
   rejected unless its CT URL contains the exact volume ID. The frontier is
   deliberately weight-free — do not add a blended "best scroll" score.
   First Letters uses the same rule. A support survey run on another scan is
   not evidence for the eligible one: PHerc1203's 2.403 µm survey reads 0.698,
   its eligible scan 0.454 (`artifacts/2026-09-30-first-letters-support/`).
8. **Dated data is frozen data.** The Grand Prize manifest and artifacts are
   as-of 2026-09-30. Updating them means a new `as_of`, a new dated artifact
   directory, and updated README/docs numbers — not an in-place edit of the
   old artifacts.

9. **A clean audit that checked nothing is a vacuous audit.** The first draft
   of the bucket chunk audit parsed S3 listings with a regex, matched zero
   objects, and reported "0 mismatches over 390 levels". It was caught only
   because it missed a mismatch measured by hand. Every checker needs a positive
   control, must report `unverified` (not `ok`) when it inspected nothing, and
   must parse structured formats with a real parser.
10. **Pre-register, then log every deviation.** `docs/protocol-pairs-protocol.md`
   froze hypothesis, constants and decision rule before any real metric was
   read; the verdict is computed by `decide()`. A control that cannot detect
   its own artifact (the half-step null missed aligned-vs-rotated lattice
   interpolation) is added as a *logged post-hoc arm*, never by rewriting the
   rule. Keep earlier runs next to later ones.
11. **The open bucket is Zarr v2, uncompressed uint8, 128^3 chunks; the dl.ash2txt
   volcomp stores are Zarr v3 sharded.** Do not assume one reader for both.
   Some registered scans live on `data.aws.ash2txt.org`, not the bucket; a
   pair whose fixed scan is unreachable is reported `run failed`, never dropped.
12. **Derive facts, don't copy them.** Voxel size, energy, released
   predictions, segment counts and prohibited higher-resolution scans come from
   the pinned eligibility list + bucket index (`scroliq-manifest`); the
   hand-copied Grand Prize and First Letters manifests are checked against them
   (`--compare-builtin`, regression-tested on the pinned snapshots).

13. **Exit status, declared metadata and configured weights are claims, not
   evidence.** A producer that exits 0 may have written nothing
   (`scroliq-vc3d-run-guard`); a `meta.json` bbox may not contain its own
   vertices (`recompute_bbox`/`compare_bbox`: never filter on a declared box
   alone); a nonzero loss weight may never have contributed a gradient
   (`scroliq-objective-audit`). Recompute from the artifact, compare, and list
   any gate whose independent evidence was not supplied instead of passing it.
   External reports behind these (VC3D exit-0 deletion, stale PHercParis4
   bboxes, Lasagna silent-zero losses) come from the maintainers' research note
   and are not reproduced here; say so when citing them.

14. **Persistence is rank-invariant only for injective remaps, and a cross-region
   gain can be region texture.** A float offset (`5*v + 2`) merged two distinct
   scores and changed ranks; saturation and uint8 quantisation do the same.
   `scroliq-persistence` checks injectivity and reports `not_injective` rather
   than a pass. Separately, negatives from other regions confound texture with
   class, so a gain must also hold *within* verified-ink regions
   (`within_region` scope). A control that never produced the effect it claims
   to block (the first confound scenario) proves nothing: the suite now requires
   the cross-region scope to pass alone before crediting the within-region gate.

15. **Internal consistency is not external correctness.** A winding-constraint
   generator can raise its own cycle consistency while recovering the wrong
   number of windings; score every producer against sealed human-verified
   pairs (`scroliq-constraint-gauge`) and let declared confidence carry weight
   only if it is externally calibrated. A reconciler (`scroliq-winding-sync`)
   cannot fix bad measurements or errors on bridges; report redundancy with
   every result. The external figures behind this rule (constraint-gauge vs
   winding-sync) are not reproduced here.

## Working rules

- Branch from `main`; never force-push to `main`.
- New scoring behavior needs a deterministic test in `tests/`.
- Every number in docs/PRs must trace to a command + artifact in this repo.
  Published numbers are repeated in `README.md`, `docs/`, and
  `artifacts/*/README.md` — change them together or not at all.
- Do not claim readability prediction. The 0–100 score is scan-health triage only.
- Do not infer surface, mesh, spiral, fiber, label-localization, or ink state from the scan score; missing evidence stays `unknown`.
- Any contributor or coding agent may open and update PRs/issues in this
  repository or upstream without prior maintainer approval. PR creation is a
  normal delivery step once the branch is coherent and the evidence is
  documented; do not stop at "prepare the branch" merely to wait for permission.
  Merging changes into repositories outside the Svyable organization,
  publishing packages/releases, or making other irreversible external releases
  still requires explicit maintainer approval.
- For the tested development setup, install `requirements-ci.txt`, then
  `pip install -e .`. Both CI requirements and public package metadata pin
  the companion to the same verified immutable commit. Update both pins
  together only after the companion commit passes its own CI. PyPI publication
  is intentionally deprioritized — never assume the companion is installable
  from PyPI.
- Do not commit environments, caches, egg-info or build archives.
- PRs follow `.github/pull_request_template.md`: What / Evidence / Stability
  check / Grand Prize + frozen data / Docs.
