# Upstream preflight vs. scroliq-mesh on published segments — 2026-10-01

**Question.** The Challenge's own `vesuvius.surface_preflight` already checks
TIFXYZ surfaces before expensive work. Does it separate the published meshes
that `scroliq-mesh` flags in [`../2026-10-01-real-mesh-audit/`](../2026-10-01-real-mesh-audit/)?

**Answer.** No, and by design. Run on the same 21 published TIFXYZ meshes
(PHerc1447: 15, PHerc0800: 6), upstream structure-only preflight passes all
21 on all 8 of its gates, including the PHerc1447 segment
`20251105093211-z_dbg_gen_00320`. On those same bytes, `scroliq-mesh` reports
153 disconnected components, 1,335 edge jumps, 386 severe normal reversals
and p95 local stretch 5.07. The two tools check different things, and they
are complementary rather than competing.

## Reproduce

```bash
pip install imagecodecs   # the published x/y/z.tif files are LZW-compressed
PATH=.venv/bin:$PATH artifacts/2026-10-01-preflight-comparison/run.sh
```

`run.sh` downloads the upstream module from `ScrollPrize/villa` at commit
`078e9eb3410f93f965951334bebca107cbe8dffb`
(`vesuvius/src/vesuvius/surface_preflight.py`, SHA-256
`862e4f1f…3bce46`, checked before use). It reuses the 84 objects in
`../2026-10-01-real-mesh-audit/keys.txt` and downloads them to `out/s3/`
(untracked). It runs the module unmodified on each mesh, without
`--volume`, writing to `preflight/`. `compare.py` then hashes every mesh file
and checks it against the SHA-256 recorded in the frozen `scroliq-mesh`
report, so both tools are shown to have judged the same bytes, and writes
`comparison.json`.

Run with numpy 2.4.6, tifffile 2026.3.3 and imagecodecs 2026.3.6. A rerun
with exactly these versions on 2026-10-03 reproduced all 21 preflight reports
and `comparison.json` byte-for-byte.

`compare.py` fails closed. Without `imagecodecs`, upstream preflight cannot read
the tifs and reports FAIL (`input_readable`) on every mesh, which would read as
the opposite finding. `compare.py` then exits 1 and leaves `comparison.json`
untouched. It also refuses if no reports are present or any mesh hash differs
(negative control run 2026-10-03).

## Results

| | upstream preflight (structure-only) | `scroliq-mesh` |
|---|---|---|
| PHerc0800 (6) | PASS, 8/8 gates each | `pass`, no findings |
| PHerc1447, 14 meshes | PASS, 8/8 gates each | `partial`: enclosed-hole review flags (one also has 2 components) |
| PHerc1447 `20251105093211-z_dbg_gen_00320` | PASS, 8/8 gates | `partial`: connectivity, hole, edge-jump, normal-reversal and isometry-distortion findings |

`comparison.json` has `all_same_bytes: true` for all 21 rows.

## What this does and does not show

- Upstream's own documentation describes `surface_preflight` as an
  input-pairing preflight that "does not replace geometric diagnostics such as
  self-intersection or local orientation analysis". This result is consistent
  with that scope. It is not a defect in upstream.
- Preflight ran **without a CT volume**, so its CT-bounds and signal-support
  gates were not run. With `--volume` the broken segment might fail signal
  support; that was not measured here.
- `vc_tifxyz_selfcross` (VC3D's nonlocal self-intersection census) was not run.
- `scroliq-mesh` separates the broken segment **by finding, not by status**.
  All five of its findings are review-severity, so its status is `partial`,
  the same as the 14 hole-flagged meshes, and the command exits 0. Status
  `fail` (exit 2) is reserved for structural errors. A pipeline that gates on
  exit codes alone would not stop this segment.
- `scroliq-mesh` can consume a preflight report directly
  (`--surface-preflight-report`) and fails closed if it is stale or for a
  different surface/volume. So the intended use is both tools together.
