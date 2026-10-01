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
verdict. `scrollq-grand-prize` applies the scores to the 13 Grand Prize
volumes as a weight-free Pareto frontier (triage, not a readability claim).

## Layout

- `src/scrollq/` — the package; each module with a `main()` is a console
  script declared in `pyproject.toml`
  - `score.py` — scoring core: `score_volume(base_url, root, samples, rotate)`,
    weights, shard sampling → `scrollq-score` (via `cli.py`)
  - `metrics.py` — per-chunk metrics from a decoded uint8 chunk
  - `health.py` — unified health report (imports `zpa.*` from the companion)
    → `scrollq-health`
  - `leaderboard.py` → `scrollq-leaderboard` (renders `docs/index.html`)
  - `coverage.py` → `scrollq-coverage` (join scores with ink-label roots)
  - `grand_prize.py` → `scrollq-grand-prize`: dated target manifest
    (`DEFAULT_MANIFEST`, `as_of`), Pareto frontier, optional surface-support
    import
- `tests/` — pytest suite; keep it green
- `artifacts/` — dated campaign outputs, the evidence behind every published
  number: `2026-09-30-scrollq/` (volumes.json, volumes_rot9.json,
  coverage.json) and `2026-09-30-grand-prize-qualifier/` (targets, probe plan,
  imported surface-support evidence with source SHAs)
- `docs/` — GitHub Pages: leaderboard (`index.html`), September writeup,
  `grand-prize-probe-protocol.md`
- `volumes.txt` — 64 dl.ash2txt.org volcomp volume roots
- `requirements-ci.txt` — pins the companion to an immutable commit, plus
  `pytest` and `build`

## Commands

Use `.venv/bin/<tool>` or an activated venv. Setup:
`pip install -r requirements-ci.txt && pip install -e .`

```bash
scrollq-score --volumes volumes.txt --samples 4 --workers 4 [--rotate N] --out-dir out/
scrollq-leaderboard --in out/volumes.json [--coverage out/coverage.json] --out out/index.html
scrollq-coverage --s3-roots <roots.jsonl> --volumes out/volumes.json --out out/coverage.json
scrollq-health --root <dl volume root>
scrollq-grand-prize --volumes artifacts/2026-09-30-scrollq/volumes.json \
  [--surface-support artifacts/2026-09-30-grand-prize-qualifier/surface_support_external.json] \
  --out out/grand-prize-targets.json
python -m pytest tests/ -q
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
   Current: ρ = 0.876, mean |Δ| = 3.07, overlap 8/10, computed between
   `artifacts/2026-09-30-scrollq/volumes.json` and `volumes_rot9.json`
   (re-derivable offline from those two files). A second sample is
   `scrollq-score --rotate N`. Those September artifacts predate the
   `sampling` provenance field, so they do not record their rotation or
   budget — new runs do; commit the full output.
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
8. **Dated data is frozen data.** The Grand Prize manifest and artifacts are
   as-of 2026-09-30. Updating them means a new `as_of`, a new dated artifact
   directory, and updated README/docs numbers — not an in-place edit of the
   old artifacts.

## Working rules

- Branch from `main`; never force-push to `main`.
- New scoring behavior needs a deterministic test in `tests/`.
- Every number in docs/PRs must trace to a command + artifact in this repo.
  Published numbers are repeated in `README.md`, `docs/`, and
  `artifacts/*/README.md` — change them together or not at all.
- Do not claim readability prediction. Triage signal only.
- Opening PRs/issues upstream or publishing to PyPI needs the maintainer's
  explicit approval — prepare the branch, don't ship it.
- For the tested development setup, install `requirements-ci.txt`, then
  `pip install -e .`. CI pins the companion to a verified immutable commit
  (update it deliberately, never to a branch). The public package keeps its
  `zarr-pyramid-audit>=0.3.0` requirement.
- Do not commit environments, caches, egg-info or build archives.
- PRs follow `.github/pull_request_template.md`: What / Evidence / Stability
  check / Grand Prize + frozen data / Docs.
