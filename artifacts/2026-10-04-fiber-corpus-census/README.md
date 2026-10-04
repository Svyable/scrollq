# PHercParis4 public fiber corpus census — 2026-10-04 (October goal O4, part 1)

Every VC3D fiber annotation in the public PHercParis4 spiral-input `fibers/`
directory, audited with ScrolIQ Fiber IQ. This extends the eight-file
`2026-10-01-public-fiber-audit/` cross-section to the full listed corpus.

Produced by `scripts/fiber_corpus_campaign.py` in GitHub Actions
(`.github/workflows/fiber-corpus.yml`, run
[37166840464](https://github.com/Svyable/scrollq/actions/runs/37166840464),
commit `b2e1477`), because the data hosts are not reachable from every
development environment. `summary.json` is the run's full output, copied
verbatim from the job log.

## Result

Verdict **complete**: listing source `huggingface-api` (paginated by `Link`
header), positive control **passed**.

| quantity | value |
|---|---|
| fibers listed / audited | **136 / 136** (0 download, hash or audit errors) |
| annotator prefixes | kb 68 · lt 31 · sm 17 · dj 14 · et 5 · sj 1 |
| timestamps | 2026-06-30 → 2026-08-26 |
| file format | VC3D fiber version 3 in all 136 |
| bytes / line points / control points | 67,489,613 / 671,984 / 5,639 |
| control-point spans | 5,503 (5,001 native trace, **502 fallback = 9.1 %**) |
| status | 29 pass · 107 caution · 0 fail |
| gap candidates | **388** in 54 fibers |
| sharp-turn candidates | **519** in 100 fibers |
| control-line offsets / control-order inversions | **0 / 0** |
| manifest SHA-256 (`file\tsha256\n`, sorted) | `a28f3a95…de196d35` |

**Positive control.** The listing had to contain all eight objects pinned by
the 2026-10-01 campaign and their bytes had to match the pinned SHA-256. They
did, and their per-file results (hash, line points, gaps, sharp turns) are
identical to the frozen 2026-10-01 rows.

**Descriptive observation, not a causal claim.** All 388 gap candidates sit in
the 79 fibers that contain at least one fallback-interpolated span; the 57
fibers traced entirely natively (236,430 line points, 1,719 spans) have **zero**
gaps and 99 of the 519 sharp turns. The 2026-10-01 sample hinted at this with
one fiber; the census shows it corpus-wide. A plausible mechanism (fallback
spans are rendered with sparser line points, so a step-length rule fires) is a
hypothesis to test at span level, not a finding.

## Reproduce

```bash
python -m pip install .
python scripts/fiber_corpus_campaign.py --out out/fiber-corpus/summary.json
```

The script exits non-zero with verdict `unverified` if no source lists the
fibers or the positive control fails, and `incomplete` if any object fails to
download, hash-match or audit. Fibers uploaded after 2026-10-04 will change
`listed` and the manifest hash; the eight pinned controls must not change.

## Evidence boundary

- Census of the directory as listed on 2026-10-04, not of every fiber ever traced.
- No exact CT volume binding is asserted; these are not passport evidence.
- Gaps and sharp turns are review candidates, not proof of a sheet switch or a wrong fiber.
- O4 part 2 — CT-conditioned support with a shifted-fiber positive control — is **not** measured here.
