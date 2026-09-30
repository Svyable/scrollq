## What

<!-- One finding or feature per PR. -->

## Evidence

<!-- Commands run + artifacts. Every number must trace to something reproducible. -->

## Stability check (scoring changes only)

- [ ] Resampling stability re-run: Spearman ρ = ___, mean |Δ| = ___, top-10 overlap = ___/10
- [ ] Bar: ρ ≥ 0.85

## Docs

- [ ] README / September page updated if behavior changed
- [ ] `tests/` updated; `python -m pytest tests/ -q` green

## Checklist

- [ ] Small, single-purpose PR branched from `main`
- [ ] No readability claims — triage signal only, weights published
- [ ] Follows `.github/CONTRIBUTING.md`
