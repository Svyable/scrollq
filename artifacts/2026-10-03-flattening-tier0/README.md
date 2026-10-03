# Flattening Tier-0 public papyrus fixtures

This directory freezes a **non-promoting** smoke corpus for developing an
independent permissively licensed flattening implementation for issue #114.

The actual OBJ meshes are **not** stored in ScrollQ. \`manifest.json\` records
their exact public Vesuvius Challenge S3 keys, byte sizes and SHA-256 hashes.
\`verify.py\` downloads those exact bytes on demand and re-runs the existing
\`scroliq-obj\` audit to confirm the geometry still reproduces the already
published 2026-10-01 corpus-audit facts.

## Why Tier-0 exists

A numerical parameterization implementation can fail in ways that synthetic
unit tests do not reveal:

- boundary loops/holes can be collapsed or bridged;
- UVs can flip or become degenerate;
- the implementation can silently mutate the 3-D surface;
- a solver can look good on an easy sheet but fail on already-distorted
  papyrus geometry.

These fixtures are selected to catch those implementation failures cheaply.
They are **not** the sealed column-sized promotion corpus.

## Frozen cases

| id | role | OBJ bytes | triangles | boundary loops | baseline p95 stretch |
|---|---|---:|---:|---:|---:|
| \`pherc0139-w035-ordinary\` | ordinary curved control | 7,107,314 | 69,772 | 1 | 1.771754 |
| \`pherc1447-hole-stress\` | tear/hole stress | 1,645,481 | 16,986 | 17 | 1.023463 |
| \`phercmanbp-w6-distortion\` | high-distortion stress | 17,939,310 | 172,218 | 1 | 2.160199 |

The set was selected from the pre-existing
\`artifacts/2026-10-01-corpus-mesh-audit/\` results before any independent
Beltrami prototype result existed.

The larger Paris4 aggregate meshes remain useful later stress cases, but they
are unnecessary for the first implementation-debug loop: the PHercMANBp case
already gives a >2 p95 distortion fixture at a small fraction of the download
size.

## Reproduce

From a ScrollQ checkout:

\`\`\`bash
python artifacts/2026-10-03-flattening-tier0/verify.py
\`\`\`

This downloads about 27 MB total into \`out/flattening-tier0/\`, verifies the
declared byte count and SHA-256 for every OBJ, re-runs \`scroliq-obj\`, and
writes:

\`\`\`text
out/flattening-tier0/verification.json
\`\`\`

To verify one case:

\`\`\`bash
python artifacts/2026-10-03-flattening-tier0/verify.py \\
  --case pherc1447-hole-stress
\`\`\`

To prohibit network access and verify already-downloaded files:

\`\`\`bash
python artifacts/2026-10-03-flattening-tier0/verify.py --no-download
\`\`\`

## Data-license boundary

The downloaded Vesuvius Challenge mesh data remain under **CC BY-NC 4.0**.
Only the manifest metadata, hashes and verifier are stored in this MIT-licensed
repository. Do not copy downloaded OBJ bytes into the repository or represent
them as MIT-licensed ScrollQ code/data.

## Promotion boundary

A candidate flattening implementation **cannot receive production promotion
from Tier-0**, even if it improves every fixture.

Tier-0 may establish only that the implementation can process selected real
papyrus meshes without obvious numerical/topological failure. The production
decision requires the separate Tier-1 experiment from issue #114:

1. a geometry-only selected, column-sized papyrus corpus;
2. one committed \`scroliq-flatten-plan seal\` spec per mesh **before** candidate
   evaluation;
3. exact 3-D geometry preservation;
4. permissive implementation licensing;
5. zero UV foldovers/degeneracies and the frozen distortion thresholds;
6. downstream VC3D/TIFXYZ, physical-scale, provenance and submission gates.

This distinction is deliberate. Small convenient fixtures are excellent for
engineering but must not become evidence for a full-column Grand Prize claim.


## Real-data expected-HOLD control

`.github/workflows/flattening-tier0-control.yml` is a narrowly scoped public-data
negative-control workflow. It runs when the Tier-0 artifact or the comparator
changes, and can also be dispatched manually.

The workflow:

1. downloads and hash-verifies the three pinned public OBJ fixtures;
2. replays their frozen `scroliq-obj` audit facts;
3. canonical-round-trips each OBJ without changing geometry or UV mappings;
4. runs `scroliq-flatten-compare`;
5. requires the verdict to be exactly `HOLD` with zero p95 improvement and all
   required safety gates passing.

A `PROMOTE` verdict from this control is a test failure, not a success. It
would mean the evidence path is incorrectly manufacturing an improvement from
an unchanged parameterization.

The workflow uploads only `verification.json` and `*.compare.json` evidence.
Source and round-tripped OBJ bytes are deliberately excluded from Actions
artifacts so the CC BY-NC 4.0 mesh data are not republished by this repository.
