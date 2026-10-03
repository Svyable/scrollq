# Reproducibility

ScrolIQ's core claim is not that every diagnostic is novel. It is that evidence
across virtual-unwrapping stages can be made reproducible, exact-volume-bound,
and fail-closed. This document defines the clean-room reproduction baseline.

## Supported environment

- Python 3.11 or newer.
- CI currently exercises Python 3.11 and 3.12.
- The Grand Prize reviewer container uses a digest-pinned Python base and an
  exact runtime constraint set.
- Public-data commands may require network access; unit tests do not.

## Clean checkout

```bash
git clone https://github.com/Svyable/scrollq.git
cd scrollq
git checkout <40-hex-commit>

python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-ci.txt
python -m pip install -e .

python -m pytest tests/ -q
```

`requirements-ci.txt` pins the verified zarr-pyramid-audit companion.
`pyproject.toml` is authoritative for package metadata. Submission-grade
reproduction should prefer the digest-pinned container described in
`docs/grand-prize-container.md`.

## Reproduce a result, not a branch

A durable artifact must identify:

- the exact ScrolIQ Git commit;
- the exact zarr-pyramid-audit commit;
- exact source CT volume identity and voxel size;
- input artifact hashes;
- command line / manifest;
- stochastic seeds;
- model checkpoint hashes;
- public dataset and experiment-run identifiers when ML is involved;
- output hashes;
- UTC execution date;
- documented manual-input time where relevant.

Do not cite `main` as the reproducibility anchor.

## Clean-room reviewer test

A submission-grade proof should be reproducible by a person or CI runner that
has only:

1. the public repository and pinned commit;
2. the digest-pinned container or documented system requirements;
3. the submitted provenance manifest;
4. public inputs, datasets, checkpoints, and experiment records allowed by the
   Challenge;
5. the exact commands in the methodology.

No shell history, cached private files, or undocumented manual edits should be
necessary.

## Frozen evidence

Directories under `artifacts/<date>-*/` are evidence records. Do not rewrite
a dated campaign to make a later result look cleaner. A changed method,
dependency, target, threshold, or input belongs in a new dated campaign.

## Models and pseudo-labeling

Use `scroliq-model-release` and `models/release.schema.json` to validate the
public release chain before a model is eligible for a final Grand Prize
provenance graph. Datasets, checkpoints, run URLs, seeds, lineage, and hashes
should be captured when the experiment is performed, not reconstructed later.

Use `scroliq-eval` for held-out evaluation and `scroliq-ink-validate` for
deterministic ink/falsification evidence.

## Exact-volume discipline

Prize evidence must use the exact eligible CT volume. Another scan of the same
scroll is a different input, even when it is visually or scientifically
preferable. `scroliq-manifest`, `scroliq-provenance`, and the ZPA source
attestation exist to make that substitution mechanically visible.

## Output-preserving performance changes

Runtime is part of practical reproducibility: an automated unrolling stage that
takes hours on common tangled growths can prevent seed search and full-scroll
coverage even when its algorithm is otherwise correct. Optimize such stages,
but separate speed evidence from correctness evidence.

For a claimed output-preserving acceleration:

- run baseline and candidate on independent fresh copies of the same inputs;
- keep deterministic result ordering even when computation is parallelized;
- compare the complete downstream output trees, not only headline meshes;
- use `scroliq-hash` to bind each tree and retain per-file comparison evidence
  when a digest differs;
- record timing methodology, machine load, thread count, and all completed runs;
- keep crash guards distinct from fixes for corrupt or stale inputs.

The bad-patch case study and `scroliq-growth-preflight` are documented in
[`docs/badpatch-growth-preflight.md`](docs/badpatch-growth-preflight.md).

## Embargoed discoveries

Generic code, required public model/data releases, and non-discovery-specific
validation can remain public. Final unread-scroll renders, deciphered text, and
the reviewer package should follow `EMBARGO.md` and must not be committed to
GitHub Pages or public artifact directories merely for convenience.

## Final-package reproduction

The final path is:

```text
eligible CT
  -> ZPA integrity/source attestation
  -> full recto surface / TIFXYZ columns
  -> VC3D execution receipts
  -> programmatic reviewer renders
  -> ink inference + held-out/falsification evidence
  -> scale proofs + numbered banner
  -> provenance + legibility validation
  -> deterministic scroliq-package archive
```

The package SHA-256, container digest, and provenance graph SHA-256 should be
recorded in the submission methodology so an independent reviewer can verify
that they reproduced the same object.
