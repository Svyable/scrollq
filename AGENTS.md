# AGENTS.md — ScrollQ

Instructions for AI coding agents working in this repo. Humans: the
contributing guide lives at `.github/CONTRIBUTING.md`.

## What this is

ScrollQ scores Vesuvius scroll volumes 0–100 on *data quality* (signal
presence, texture/gradient energy, dynamic range, saturation penalty,
dead-slice scan) by decoding sampled 128³ volcomp chunks over HTTP.
Companion: [zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit)
("don't train on lies" — corruption detection). This is "train on the best
first." `scrollq-health` unifies both into one TRAIN / CAUTION / DO NOT TRAIN
verdict.

## Layout

- `src/scrollq/` — the package
  - `score.py` — scoring core: `score_volume(base_url, root)`, weights
  - `health.py` — unified health report (imports `zpa.*` from the companion)
  - `cli.py` — `scrollq-score`; `leaderboard.py`, `coverage.py`
- `tests/` — pytest suite; keep it green
- `artifacts/` — dated campaign outputs (volumes.json, reports); the evidence
  behind every published number
- `docs/` — GitHub Pages: leaderboard + September writeup
- `volumes.txt` — 64 dl.ash2txt.org volcomp volume roots

## Commands

```bash
.venv/bin/scrollq-score --volumes volumes.txt --samples 4 --workers 4 --out-dir out/
.venv/bin/scrollq-health --root <dl volume root>
python -m pytest tests/ -q
```

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
   Current: ρ = 0.876, mean |Δ| = 3.07, overlap 8/10.
5. **Weights are a judgment call, published with every score.** Changing them
   is fine; hiding them is not. Update the September page when they change.

## Working rules

- Branch from `main`; never force-push to `main`.
- New scoring behavior needs a deterministic test in `tests/`.
- Every number in docs/PRs must trace to a command + artifact in this repo.
- Do not claim readability prediction. Triage signal only.
- Opening PRs/issues upstream or publishing to PyPI needs the maintainer's
  explicit approval — prepare the branch, don't ship it.
- Install with `pip install -e .`; the companion dependency
  `zarr-pyramid-audit>=0.3.0` comes from PyPI.
