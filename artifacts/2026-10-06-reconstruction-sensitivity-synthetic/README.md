# Reconstruction-sensitivity audit: synthetic controls (2026-10-06)

**Synthetic only. No reconstruction was run, no projection, volume or scroll is
measured here, and neither CIL nor ASTRA was executed or imported.** The panels
are built by `_control_arrays()` and `_control_spec()` in
`src/scrollq/reconstruction_sensitivity.py`; what follows is a property of the
control construction, not a detection limit on real papyrus.

- Base commit: `9250a7617ea24f687fbde61a443ba7a191f56cb2` (this change adds the
  module on top of it)
- Constants fixed in the module before any output was read: control seed
  `20261007`, 80 x 80 grid, ink threshold 0.5, minimum component 12 cells,
  match IoU 0.5, geometry tolerances 1 voxel / 1 voxel / 10 degrees / 1 voxel.
- Defects found while building and fixed before this artifact was generated:
  `_control_spec()` aliased the shared control constants, so mutating one built
  spec leaked into later ones (a second `self_test()` in one process would have
  failed); and a populated arm was read for a `status` key it did not yet
  carry, which would have crashed `assess()`. Neither changed a threshold or a
  decision rule.
- `self-test.json` SHA-256:
  `73bdf4869563b6fa1a38cb46ad2abfa88e4a095ceb6191c1da3438979b00c68a`

## Reproduce

```bash
scroliq-reconstruction-sensitivity self-test > self-test.json
```

About one second on one CPU. `tests/test_reconstruction_sensitivity.py` re-runs
it and compares the committed file.

## The planted family

Six variants share one frozen projection, preprocessing and pipeline
fingerprint: the official reference; plain LSQR; LSQR with weak and with strong
Tikhonov regularisation; and two centre-of-rotation perturbations (+/-0.5 px,
inside a +/-1 px preregistered bound) of the LSQR baseline. Six reference ink
components are then planted:

| component | planted fate | expected class | recovered because |
|---|---|---|---|
| `G`, `H` | present in every variant, surface undisturbed | `reconstruction_stable` | matched in every variant of both arms, every geometry channel inside tolerance |
| `B` | vanishes under strong regularisation | `reconstruction_sensitive` | `absent-in:tik_strong` |
| `C` | moves 12 cells under plain LSQR | `reconstruction_sensitive` | `absent-in:lsqr` (and reappears as a variant-only component) |
| `E` | ink unchanged, surface displaced 2 voxels under weak regularisation | `reconstruction_sensitive` | `normal_displacement-exceeds-tolerance-in:tik_weak` |
| `A` | stable across reconstruction variants, vanishes under +0.5 px centre of rotation | `reconstruction_sensitive` | `calibration:absent-in:cor_plus`, reached through the matched baseline component |

Strong regularisation also manufactures a component inside the known-negative
region (`variant_only` 2 in total: this one and the shifted `C`).

Three further controls must hold, or `evaluate` withholds every verdict:

- a **null family** (variants differ only by noise below the ink threshold):
  all 6 components stable and 0 variant-only;
- a **no-op family** (every variant is a bitwise copy of the reference with the
  reference's volume hash): 0 stable, because a variation that did not vary the
  volume proves nothing;
- spec refusals: a variant selected using ink, and a calibration perturbation
  outside its preregistered plausible bound, are both refused; a
  GPL-3.0 backend in the declared dependency manifest is flagged
  (`copyleft_present`) rather than folded into the framework's licence.

## What this does not show

That any real ink component is, or is not, reconstruction-sensitive; that LSQR
or Tikhonov regularisation reproduces or improves the official reconstruction;
or that Vesuvius raw projections exist for any scroll in usable form. Real
evidence needs the experiment in
[`docs/reconstruction-sensitivity.md`](../../docs/reconstruction-sensitivity.md).
