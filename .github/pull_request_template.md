## What

<!-- One finding or feature per PR. -->

## Evidence

<!-- Commands run + artifacts. Every number must trace to something reproducible. -->

## Stability check (scoring changes only)

- [ ] Resampling stability re-run: Spearman ρ = ___, mean |Δ| = ___, top-10 overlap = ___/10
- [ ] Bar: ρ ≥ 0.85

## Grand Prize / frozen data (if touched)

- [ ] Exact prize-listed volume IDs only; no same-scroll substitution
- [ ] New `as_of` + new dated `artifacts/` directory (old artifacts untouched)

## Docs

- [ ] README / September page / artifact READMEs updated if behavior or numbers changed
- [ ] `tests/` updated; `python -m pytest tests/ -q` green

## Checklist

- [ ] Small, single-purpose PR branched from `main`
- [ ] No readability claims — triage signal only, weights published
- [ ] Follows `.github/CONTRIBUTING.md`
