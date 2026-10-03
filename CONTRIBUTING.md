# Contributing to ScrolIQ

Thank you for helping make Vesuvius Challenge evidence, virtual-unwrapping diagnostics, and 2027 Grand Prize submission tooling more reproducible.

The detailed contribution policy lives in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). Read that file and [`AGENTS.md`](AGENTS.md) before changing scoring semantics, prize manifests, provenance gates, generated artifacts, or release workflows.

## Quick setup

```bash
git clone https://github.com/Svyable/scrollq.git
cd scrollq
python -m venv .venv
. .venv/bin/activate
python -m pip install -r reqs.txt
python -m pytest tests/ -q
```

Python 3.11 or newer is required. `pyproject.toml` is authoritative for runtime package metadata; `requirements-ci.txt` pins the verified companion revision used in CI; `reqs.txt` is the one-command contributor setup.

## Evidence-first contribution standard

ScrolIQ is intentionally conservative. A contribution should make it easier to reproduce a result, falsify a claim, or trace an output back to its source. Missing or unverifiable evidence stays `unknown`; a scan-health score is not a readability score; a proxy is not a Grand Prize qualification claim.

For work that may feed a Vesuvius Challenge / Scroll Prize submission, preserve the exact prize-eligible CT identity, mesh/render provenance, deterministic seeds, training/prediction non-overlap, public model/data licenses, experiment tracking, held-out validation, and the reviewer-visible chain from source CT to TIFXYZ to rendered image. The current official requirements are published at https://scrollprize.org/prizes.

Do not silently replace a prize-listed scan with a higher-resolution scan of the same scroll. Do not rewrite frozen dated artifacts in place. New measurements belong in new dated artifacts with the exact command and inputs recorded.

## Pull requests

Branch from `main`, keep changes narrowly scoped, and run the relevant test and evidence checks before proposing a merge. Follow `.github/CONTRIBUTING.md` for the required PR evidence and Grand Prize / frozen-data checklist.

## Credit and licensing

Please add material upstream projects, datasets, models, or community work you rely on to [`CREDITS.md`](CREDITS.md) when appropriate. The goal is to make provenance and intellectual debt explicit, not to absorb community work into this repository.

By contributing, you agree that your contribution is made available under the repository's [MIT License](LICENSE). Third-party code, models, datasets, and documentation remain subject to their own licenses and terms.
