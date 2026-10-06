# In-situ detectability and negative ink evidence

A blank prediction is **UNINFORMATIVE** unless its exact surface/window/model
path recovers a frozen reference-strength synthetic stroke family. Passing is
**SUPPORTED_NEGATIVE** only for the tested window, stroke widths and contrast;
it does not prove physical ink absence, character legibility, or Challenge
acceptance of an explanation. All other ink/provenance gates remain necessary.

`scroliq-ink-detectability` is an independent diagnostic implementation inspired
by [Herculaneum Scroll Tools](https://github.com/axiosdevs/herculaneum-scroll-tools)
(MIT). It does not import its experimental orientation chooser. Source review
is pinned in the [research note](research/2026-10-06-ink-detectability.md).
No real scroll/model experiment has been run by ScrolIQ for this integration.

Freeze a JSON spec before inference. Required fields:

| Field | Contract |
| --- | --- |
| `schema_version`, `volume_root`, `region_id` | `1`, exact permitted CT root, exact UV evaluation window identity |
| `stack`, `face_depth`, `surface`, `checkpoint`, `engine`, `config` | Each has `path`, lowercase `sha256`, its own `terms`, `intended_use_permitted: true` |
| `stack` | uint8 NPY, `(depth,y,x)`, before inference normalization; fixed rendered window |
| `face_depth` | Finite NPY `(y,x)`, within window, physically inferred face depth; not a brightness-selected window |
| `orientation_source`, `layer_order` | `geometry` or `organizer_provenance`; frozen `forward` or `reverse` |
| `contrasts`, `widths_px`, `reference_contrast` | Multiple unique positive contrasts and integer widths; reference contrast explicitly tested |
| `threshold`, `min_lift`, `max_off_mask_lift`, `depth_sigma`, `seed` | Frozen probability cutoff, recovery margin, off-stroke response limit, Gaussian depth width in voxels, integer seed |
| `selection_used_ink`, `synthetic_used_for_training`, `uses_prohibited_higher_resolution` | All `false` |

Calibrate the reference contrast with the identical model/rendering conventions
on a sealed known-positive surface. Do not adopt a community threshold as a
universal physical ink strength. A calibration fixture may overlap checkpoint
training; it establishes calibration only, never held-out generalization. Convert physical widths to pixels using the
frozen render scale and include that scale and normalization in `config`.
The `surface` binding must identify the exact window/crop geometry, not merely
the scroll. Face-depth ancestry and asset permissions require independent review.

The hashed Python `engine` adapter accepts positional arguments:
`input.npy output.npy config-path checkpoint-path layer-order`. It must invoke
the unchanged public inference path and return a probability map `(y,x)` in
`[0,1]`. Pin all imported inference dependencies/environment inside the hashed
config; hashing the adapter alone does not prove the transitive code is frozen.
Fix and record training/inference seeds and experiment tracking separately.

```bash
scroliq-ink-detectability --spec frozen-spec.json \
  --spec-sha256 <independently-committed-spec-sha256> --out out/probe
scroliq-ink-detectability --verify out/probe \
  --spec-sha256 <same-spec-sha256>
```

Output directories are create-only. The bundle keeps real probabilities in
`real.npy`, synthetic inputs/predictions in separate `synthetic-*` files, copied
source stack/face arrays, exact spec bytes and an inventory of SHA-256 digests.
The real input is inferred twice before planting, and its probabilities must be
bit-identical; drift/stochastic output blocks negative evidence. `real-repeat.npy`
is included in the hashed inventory and verification checks it again.
Verification regenerates planted inputs and recomputes all recovery rows from
arrays, ignoring producer verdicts. Missing/altered arrays fail closed. No
synthetic output belongs in training, submission imagery, or real ink evidence.

Recovery is the fraction of stroke pixels crossing the frozen threshold after
planting minus the fraction crossing before planting. A fixed letter-like map
cannot pass. Global threshold response is rejected by the off-stroke limit.
**Every width must pass at the exact reference contrast.** Higher contrast need
not produce stronger recovery; retain the full curve and do not cherry-pick a
successful row. A failed row at another contrast is recorded rather than used
to assume a monotonic sensitivity curve.

An ink manifest making an absence claim must include `negative_ink_claims`.
Set `absence_of_ink_claimed: true` when an absence assertion is made; this flag
requires a nonempty claim list. Each item supplies `evaluation_region_id`, `surface_sha256`, `prediction_sha256`
(the exact `real.npy`), `bundle_dir`, `spec_sha256`, and `receipt_sha256` (the
committed `report.json`). `scroliq-ink-audit` recomputes the bundle and requires
the claim's volume/region/checkpoint/surface to match. Missing evidence,
nonblank output, or failed recovery makes the claim inadmissible and blocks the
ink audit; passports carry this state. Ordinary positive evidence remains
backward compatible. This cannot discover undeclared absence claims in prose.

A supplied expected digest establishes byte identity, **not historical ordering**.
Anchor the spec before any probe output using the existing blind-control custody
workflow or an independently timestamped public commitment. Never alter the
surface, normalization, window, polarity, or cutoff after inspecting recovery;
any revision is a new preregistered experiment. With uncertain orientation, run
both independently preregistered orders and retain both results without selecting
according to real or synthetic ink response; no single-order absence conclusion
is warranted until independent orientation evidence resolves it.

`preprocessing_gate` computes paired known-positive IoU and requires no loss
in local synthetic lift or off-mask specificity over the entire matching curve.
The caller must seal truth/negatives, freeze metrics/arms and apply preprocessing
to both fixtures and targets identically before invoking this numerical gate.
The API recomputes verdicts from the entire frozen contrast/width grid, ignores
producer PASS fields, and refuses a changed rule or omitted rows.
Its API alone does not establish custody or permission. Tests include an
adversarial preprocessing fixture whose synthetic recovery improves while known
ink performance degrades. Smoothing, brighter-sheet mesh tightening and
brightest-layer recentering remain adverse controls, never recommended defaults.
The committed transformations are numerical adverse surrogates (blur/shift),
not reproductions of the upstream physical mesh/window experiments.

Dual-energy contrast stays **WATCH / bounded experiment**. Freeze registration
without ink, compare sealed verified ink and matched physical negatives, and
require held-out letter-level spatial agreement. Dense inclusions are not proof
of ink. Review exact target scan eligibility and all source terms before use;
prohibited higher-resolution target scans cannot supply submission derivatives.
