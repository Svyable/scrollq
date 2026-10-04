# Seam fingerprint authenticator — synthetic software controls (2026-10-04)

Evidence for [`scroliq-seam-fingerprint`](../../docs/papyrus-seam-fingerprint.md).
**Everything here is synthetic.** It shows the implementation honors its stated
verdict rules, including the falsification and low-information controls. It says
nothing about whether real carbonized papyrus carries a recoverable fingerprint;
no real-CT measurement exists. Status: EXPERIMENT FURTHER.

All reports are bound to source digest
`f1091d0c3405a70a7e65a67fd4418fce3d5b36db55359a82062e2a940e6c7903`
(`src/scrollq/seam_fingerprint.py`) and config digest
`bc0cc2c93e4c9693697499f559af5f1ce17cfd737192f782275a1169b626083c`
(the two ablations carry their own config digest). Generated with NumPy 2.4.6;
NumPy does not promise identical `Generator` streams across versions, so a rerun on
another version should reproduce the gate outcome and the qualitative table but
may move individual z values slightly.

## Files

| File | Command | Gate |
|---|---|---|
| `controls-heldout.json` | `scroliq-seam-fingerprint controls --out controls-heldout.json --seed-base 700000 --n 40 --sweep-n 12` | PASS |
| `controls-ablation-feature-gate.json` | same, plus `--ablate feature-gate` | FAIL (expected) |
| `controls-ablation-information-gate.json` | same, plus `--ablate information-gate` | FAIL (expected) |
| `controls-development.json` | `... --seed-base 100000 --n 40 --sweep-n 12` | PASS |
| `controls-heldout-run1-superseded.json` | first held-out run, 19 cases, earlier source | PASS |
| `descriptor-comparison.json` | `python scripts/seam_descriptor_comparison.py --out descriptor-comparison.json` | n/a |

Output files are create-only, so rerun into a fresh path.

- **Held-out** (`700000`) was not run until the constants were final. **Development**
  (`100000`) was looked at while building, so it is not held-out.
- **`controls-heldout-run1-superseded.json`** is kept next to its replacement. It
  predates the `blank_shared_voxel_noise` control, which was added once it was clear
  the earlier blank control passed with or without the information gate. Adding it
  changed the source, so the held-out run was repeated on the same seeds.
- **Ablations** disable one gate on the same seeds to keep the hazard visible:
  without the feature gate, `shared_crack_impostor` is `AUTHENTICATED` in 33 of 40
  runs; without the information gate, `blank_shared_voxel_noise` is
  `AUTHENTICATED` in 40 of 40 and the independent-noise blank controls become
  `CONTRADICTED` in every run.
- **`descriptor-comparison.json`** records a failed prediction: the existing
  magnitude-only `tangent-fiber-spectrum-v1` descriptor is not blind to phase
  randomization (median distance 0.0006 genuine copy, 0.0540 phase-randomized,
  0.0665 block-shuffled, 0.0433 unrelated sheet). The difference between the tools
  is the output, not a failure of the older one.

## Headline (held-out, 40 seeds per control)

- No impostor, misregistered, destroyed-identity or low-information run was
  `AUTHENTICATED`.
- Phase-randomized and block-shuffled controls: median peak z 2.1 % and 2.0 % of the
  matched genuine control's.
- The largest impostor-or-destroyed peak was z 7.49 against the acceptance floor of
  9.0, a margin of about 1.2×. That is thin; real-CT calibration must set it from an
  empirical null.
- Authenticated displacement error: at most 0.37 px in the well-posed genuine
  controls, but up to 0.93 px in the degraded control, hence the separate
  `refinement.usable` gate.

Full tables, the development log and known limits are in the
[protocol](../../docs/papyrus-seam-fingerprint.md).
