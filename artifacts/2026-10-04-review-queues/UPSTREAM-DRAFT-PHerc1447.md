# DRAFT — not filed

Prepared for the maintainer (Sven) to review, reproduce and file if they agree.
Nothing is opened upstream without explicit approval; the checkbox below is
deliberately **unchecked**.

---

**In one sentence:** The public PHerc1447 segment
`segments/20251105093211-z_dbg_gen_00320` (name suggests a debug output) is
geometrically broken: its TIFXYZ mesh falls apart into 153 disconnected
pieces with 1,335 edge jumps and 386 folded-over (normal-reversed) quad
pairs, but it sits in `segments/` beside the 14 coherent PHerc1447 meshes.

**I was trying to:** Audit every published TIFXYZ segment mesh for local
geometric defects before using them as training or rendering inputs.

**What happened:** `scroliq-mesh` on
`PHerc1447/segments/20251105093211-z_dbg_gen_00320/mesh/20251105093211-on-20250521151220-8.64um.tifxyz`
(rechecked on live bytes 2026-10-04; SHA-256 of `x.tif`
`f7db4456…2736abfb`, identical to the 2026-10-01 audit):

| check | this segment | other 14 PHerc1447 meshes |
|---|---|---|
| valid-vertex components | **153** (152 enclosed islands) | 1 in 13, 2 in one |
| edge jumps > 4× median spacing | **1,335** (707 columns + 628 rows) | 0 |
| severe normal reversals (>120°) | **386** | 0 |
| isometry stretch p95 / max | **5.06 / 80.6** | ≤ 1.026 |

The same directory also ships `intermediate/` OBJs and a rendered
`surface-volumes/…tifs/00.tif`, so it looks like a finished segment to a script
that walks `segments/`.

**What I expected or needed:** Debug/experimental segments kept out of the
public `segments/` prefix, or marked (e.g. in `meta.json`) so they can be
filtered.

**Evidence / reproduction:**

```bash
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
S=PHerc1447/segments/20251105093211-z_dbg_gen_00320/mesh/20251105093211-on-20250521151220-8.64um.tifxyz
mkdir -p seg.tifxyz && for f in meta.json x.tif y.tif z.tif; do curl -fsS -o seg.tifxyz/$f $B/$S/$f; done
pip install "git+https://github.com/Svyable/scrollq"   # not published on PyPI
scroliq-mesh --tifxyz seg.tifxyz --out seg.audit.json
```

Frozen reports: `artifacts/2026-10-01-real-mesh-audit/reports/PHerc1447.20251105093211-z_dbg_gen_00320.json`,
today's recheck `PHerc1447.z_dbg_gen_00320.recheck-2026-10-04.json` (beside
this draft). Independently, the same bytes pass all 8 gates of a different
preflight tool (`artifacts/2026-10-01-preflight-comparison/`), so that tool's
pass is not evidence the mesh is sound.

- [ ] I personally encountered or reproduced this using the version and data stated above.

## Details

- These are local mesh checks only. We did not inspect the segment against CT
  in VC3D; whether it was ever intended for use is unknown.
- PHerc1447 is a Grand Prize target, so a "use every PHerc1447 segment"
  training or rendering run would ingest this mesh.
