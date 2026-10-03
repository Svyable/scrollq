# Exact-volume target integrity plan — 2026-10-03

This artifact closes the first shared blocker from the
[`target-freeze baseline`](../2026-10-03-target-freeze-baseline/) without
changing the cohort or ranking candidates.

## What is already known

ZPA's frozen
[`2026-10-02-grand-prize-ct-preflight`](https://github.com/Svyable/zarr-pyramid-audit/tree/main/artifacts/2026-10-02-grand-prize-ct-preflight)
cross-cut found all 13 exact Grand Prize CT roots in the 2026-09-29 S3 audit.
For every root it recorded all 6 declared levels present, no chunkless level,
no unknown chunk-presence evidence, no read/metadata error, and zero header
findings.

That is useful **dated structural context**, not enough for the current
ScrolIQ target gate. The missing evidence is a current, versioned, per-root ZPA
gate report carrying:

- `integrity: PASS`;
- exact-root identity;
- the opt-in eligible voxel-size fence;
- `source_attestation.state: PRESENT`;
- a metadata-semantics SHA-256 and exact ZYX axis contract.

## Pinned implementation

The run is pinned to ZPA
`3edfd4bc50b4dab888ca7bc6e339f87b3e524a6a`. Its Git tree
`34246b42a413884d3d0830b9e16d4ece0f3b8887` is identical to PR #35's
CI-tested head `c066b2f4ab67da541962685c761aa0d424259c2e`.

The tested head completed both ZPA CI and the live `audit-smoke` workflow
successfully. ScrolIQ's public package metadata and CI requirements are pinned
to the canonical squash commit together.

## Run

From a clean ScrolIQ checkout with `requirements-ci.txt` installed:

```bash
bash artifacts/2026-10-03-target-integrity-plan/run-integrity.sh out/target-integrity
python artifacts/2026-10-03-target-integrity-plan/verify.py \
  --plan artifacts/2026-10-03-target-integrity-plan/integrity-plan.json \
  --reports-dir out/target-integrity \
  --out out/target-integrity/integrity-evidence.json
```

The shell runner refuses to write into a non-empty output directory. The
verifier refuses to overwrite its result and uses ZPA's own report validator
before applying the prize-specific identity, voxel-size and attestation checks.

A successful verification is **promotable evidence for `input_integrity`
only**. Copy the reports plus verifier output into a new dated artifact before
changing a target-gate input from `unknown` to `pass`.

## Why this stage is first

All three frozen candidates currently share this unknown. The blind-probe
protocol says downstream geometry or ink results are not interpretable until
the exact consumed input passes provenance/integrity checks. Closing this gate
therefore improves the evidence state symmetrically without using any held-out
outcome to influence target selection.

## Claim boundary

A source-attested ZPA PASS establishes that the exact declared CT input satisfies
the implemented structural/integrity contract. It does not prove semantic voxel
correctness, correct papyrus sheet identity, flattening quality, ink,
legibility, or Grand Prize success.
