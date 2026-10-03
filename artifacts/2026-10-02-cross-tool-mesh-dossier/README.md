# Cross-tool mesh evidence dossier — 2026-10-02

This artifact composes **ScrolIQ Mesh IQ** and **Windcheck** evidence for one
public TIFXYZ surface only after proving that both sources refer to the same
published coordinate geometry.

It is the first real-data example of `scroliq-evidence-bind`.

## Surface

- scroll: **PHerc0139**
- segment: `20260306000001-w051_2026030600`
- exact volume: `20250728140407` (9.362 µm)
- grid: **379 × 480**
- valid vertices: **164,096**

## Identity proof

The frozen ScrolIQ mesh audit and the pinned Windcheck release record agree on
the full SHA-256 of all three coordinate planes:

| channel | SHA-256 |
|---|---|
| x.tif | `dff240d4c984da3223020562a83ee96d34da9f02787b3b2409adc0b3a5d12215` |
| y.tif | `a73d4c247505e123a9dfe923c6f7fe53ee9ca7ab9ce7bddecb5405f1014c5c6c` |
| z.tif | `233bc07b57ed6447e19482785905ebdf41031bf979ca859390de79a2f569237e` |

Neither source declares a mask. Grid shape and valid-vertex count also agree.

The dossier therefore classifies the binding as **coordinate-exact**. It does
**not** call it semantic-exact because the Windcheck release-index projection
does not expose the original `meta.json` SHA-256. ScrolIQ's own audit does
retain that metadata hash.

## Complementary evidence on the same published original

ScrolIQ's frozen local Mesh IQ report records:

- **15** local edge jumps over 4× the directional median;
- **173** severe neighbouring-normal reversals;
- one connected valid-vertex component;
- no enclosed invalid component.

Windcheck's pinned release record says `base_kind=original`, and its
`input_hashes` are the coordinate hashes above. Its nonlocal census therefore
applies to this same published coordinate geometry and reports:

- **3,333 transverse contacts** on the input;
- a transformed reference with **0** transverse contacts on recensus;
- clean under both canonical triangulations after transformation;
- **0.9975269266** represented-surface retention;
- core-fragmentation gate passed.

These measurements are complementary. Mesh IQ's local edge/normal findings are
not a proxy for Windcheck's triangle-intersection census, and Windcheck's
transverse contacts do not establish which papyrus branch is physically wrong.

## Pinned external source

The Windcheck record is copied without mutation from:

- repository: `joe-carr-data/windcheck`
- commit: `2b0fb2f3d305d3727dcb24a8eaa73c3c8ce5c3ce`
- path: `out/release/index.json`
- Git blob: `74d989952b55744a059cbcdeff435beb1cbcbdce`
- source-tree digest recorded by Windcheck:
  `e85c2f0df3b9a27d43e4ed62d0c324bfd58c524c1bd292b3ca045d6cf84d4abf`

The projection is stored in `windcheck-record.json`; its own SHA-256 and the
ScrolIQ report SHA-256 are carried in `summary.json`.

## Reproduce offline

From the repository root:

```bash
python -m pip install .
python artifacts/2026-10-02-cross-tool-mesh-dossier/derive.py
git diff --exit-code artifacts/2026-10-02-cross-tool-mesh-dossier/summary.json
```

The GitHub workflow `.github/workflows/cross-tool-dossier.yml` runs the same
derivation and rejects drift from the frozen dossier.

## Claim boundary

- Coordinate-exact is weaker than semantic-exact: the external index projection
  does not bind `meta.json`.
- The Windcheck transformed reference is **not** silently substituted for the
  original published surface.
- Local geometry cues plus transverse-intersection evidence still do not prove
  correct physical sheet identity, recto completeness, or readable ink.
- This case demonstrates interoperable evidence composition; it is not a
  population estimate for other surfaces.
