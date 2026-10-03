# PHerc0800 community meshes through five independent mesh gates — 2026-10-02

The first real-data run of `scroliq-gp-ready`: all **95** PHerc0800 tifxyz
meshes from
[pscamillo/vesuvius-eligible-meshes](https://github.com/pscamillo/vesuvius-eligible-meshes)
(commit `620769e2e1e70d1e61b588092229cb76d3af4804`, MIT) were checked by four
pinned community tools and `scroliq-mesh`, and the reports were compiled into
one dossier. PHerc0800 is the only scroll on the First Letters frontier in
both resample runs (`artifacts/2026-09-30-first-letters-qualifier-n24-dense/`).

These are fit-window fragments, not column meshes. The dossier uses a
mesh-gates policy (`policy-mesh-gates.json`): the four checks that can be
measured today. Handedness, per-mesh CT support and submission-level checks
are left out here because they have no adapter yet.

## Tools (pinned)

| check | tool | commit |
|---|---|---|
| `mesh.self-intersection` | joe-carr-data/windcheck `check` | `2b0fb2f3d305` |
| `mesh.flatten-distortion` | abundantjoe/flatcheck `report` | `948a19d102ed` |
| `mesh.tifxyz-contract` | aviad12g/tifxyz-doctor `audit` + Nieuwlaar/tifxyz-repair `validate` | `5ca0444fb318`, `4d6c98d95b71` |
| `mesh.scroliq-audit` | `scroliq-mesh` (this repo) | — |

## Results (`dossier.json`, `dossier.md`)

| check | result |
|---|---|
| Self-intersection | **95 / 95 clean** (no transverse self-intersection), hash-verified |
| Flattening distortion | **95 / 95 below flatcheck's default bar** (93.1 % of quads within ±5 % area); median 66.0 %, best 88.4 %, 8 meshes below 50 %. No mesh has fold-overs or a collapsed parametrization, so every failure is the area-distortion bar alone |
| tifxyz contract | **95 / 95 caution**, all the same finding: `metadata-area-schema-divergence` (`meta.json` has `area_vx2`/`area_cm2` but no `area`, which the current Villa Python reader expects) |
| ScrolIQ mesh audit | 50 pass, 45 caution (neighbouring-normal reversals; 11 meshes have a valid-vertex grid in 2 disconnected components) |

Bindings: 190 records hash-verified (windcheck, scroliq-mesh), 285
path-declared (flatcheck, tifxyz-doctor, tifxyz-repair). No mesh is `ready`
under this policy; every blocker is listed per mesh.

## Re-flattening (`reflattening.json`)

flatcheck can also re-flatten each surface (SLIM, ARAP) and score the result
against the same bar. This separates "the stored parametrization is poor"
from "the surface cannot be flattened well".

| parametrization | meshes | pass 93.1 % bar | median % quads within ±5 % | notes |
|---|---|---|---|---|
| stored tifxyz grid | 95 | **0** | 66.0 | no fold-overs |
| SLIM re-flattening | 95 | **21** | 87.5 | no fold-overs, no collapse |
| ARAP re-flattening | 93 | 21 | 87.9 | 1 mesh with fold-overs/collapse; ARAP crashed in libigl on z17072_w040 and z17072_w080 |

Re-flattening raises the share of quads within ±5 % by a median of 17.5
points (range 7.4–65.4) and brings 21 / 95 meshes over the bar; the same 21
pass whichever method is used. The other 74 stay below it even when
re-flattened, which points at the surfaces themselves (curvature or
tracing), not only at how they were stored.

## What this does and does not say

- The surfaces are geometrically clean in the self-intersection sense.
- The **stored parametrizations** do not meet flatcheck's low-distortion bar;
  re-flattening fixes that for 21 of 95.
  The 93.1 % bar is flatcheck's default, not a prize rule; the prize asks for
  a "low-distortion isometric 2D parametrization" without a number.
- The metadata finding is a one-field fix for the publisher.
- None of this says whether a mesh follows the right sheet or carries ink.

## Reproduce

```bash
git clone --filter=blob:none --sparse https://github.com/pscamillo/vesuvius-eligible-meshes elig
git -C elig checkout 620769e2e1e70d1e61b588092229cb76d3af4804
git -C elig sparse-checkout set meshes/PHerc0800 data
# install the four tools at the commits above into $TOOLS (windcheck also
# needs its engines/selfcross.cpp compiled; see the windcheck README)
TOOLS=… ./run_gates.sh            # writes gates800/<mesh>/{flatcheck,…}.json
# scroliq-mesh per mesh:
#   scroliq-mesh --tifxyz elig/meshes/PHerc0800/<mesh> \
#     --volume-root PHerc0800/volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr \
#     --out gates800/<mesh>/scroliq-mesh.json
scroliq-gp-ready --manifest manifest.json --policy policy-mesh-gates.json \
  --out dossier.json --markdown dossier.md
```

Or check the committed reports directly: `tar -xzf reports.tar.gz` restores
`gates800/`, and every record in `dossier.json` carries the SHA-256 of the
report it came from. Local absolute paths in the reports were replaced with
`<work>`/`<home>` before hashing; adapters do not read those fields.
