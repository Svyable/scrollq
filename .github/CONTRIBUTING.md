# Contributing to ScrollQ

Thanks for stopping by. ScrollQ exists so nobody trains a scroll-reading
model on the worst data in the corpus by accident. Contributions that make
the triage signal sharper — or the evidence behind it more honest — are
welcome.

## Ways to contribute

- **Code**: better scoring features, faster decoding, new commands.
- **Findings**: a volume you think is mis-scored, a dead slice we missed, a
  label-coverage gap. Use the *data finding* issue template — evidence
  required (see below).
- **Docs**: the README, the September writeup, the leaderboard copy.

## Setup

```bash
git clone https://github.com/Svyable/scrollq.git
cd scrollq
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"   # or: pip install -e .
```

## Running the tools

```bash
# score volumes (one dl.ash2txt.org root per line in volumes.txt)
scrollq-score --volumes volumes.txt --samples 4 --workers 4 --out-dir out/

# rebuild the leaderboard site
scrollq-leaderboard --in out/volumes.json --out docs/index.html

# unified health verdict for one volume
scrollq-health --root community-uploads/forrest/volcomp/PHerc0009B/volumes/....zarr
```

## Tests

```bash
python -m pytest tests/ -q
```

All tests must pass before a PR is merged. New scoring logic needs a test
that pins its behavior on a fixed input (determinism is a feature here).

## The accuracy policy (read this)

ScrollQ's whole value is trust. Every claim in a PR, issue, or doc change
must be backed by something a reviewer can re-run:

- Numbers come from a command in this repo, with the artifact committed
  (or linked) so the run is reproducible.
- "Missing" means absent from the shard index — masked background is
  *legitimately* unstored, not a defect. Do not report missing chunks as
  empty chunks.
- Score changes: report the resampling-stability numbers (Spearman ρ,
  mean |Δ|, top-10 overlap) before and after, using
  `artifacts/`-style deterministic rotation. The current bar: ρ ≥ 0.85.
- Do not claim ScrollQ predicts readability. It is a triage signal; the
  weights are published so people can audit them, not worship the ranking.

## Pull requests

1. Branch from `main`: `git checkout -b <what>-<why>`.
2. Keep PRs small and evidence-backed. One finding or feature per PR.
3. Update docs (README / September page) if behavior changes.
4. CI runs the test suite; green is required.

## Reporting a data finding

Open an issue with the *data finding* template and include:

- the volume root and level,
- the command you ran (exact flags),
- what you expected vs. what you observed,
- the artifact (JSON/CSV) or a link to it.

Findings without a reproducible command will be asked for one.

## License

By contributing, you agree your work is released under the MIT License.
