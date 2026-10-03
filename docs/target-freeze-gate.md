# Grand Prize target-freeze gate

`scroliq-target-gate` turns the proof campaign's target-selection prerequisites
into a machine-readable, fail-closed decision record.

It is deliberately **not a ranking tool**. A target is either backed by the
minimum evidence needed to freeze a proof campaign, blocked by a failed check,
or still provisional because evidence is missing.

## What the gate checks

Exact-volume identity is verified directly against ScrolIQ's frozen
`2027 Grand Prize` manifest. The input must name the official eligible
`scroll`, `volume_id`, and a `volume_root` containing that exact
`/<scroll>/volumes/<volume_id>` path. A same-scroll higher-resolution scan
does not pass.

Five additional prerequisites must then be declared:

1. `input_integrity` — the exact inputs consumed have non-UNKNOWN integrity
   evidence, normally including a ZPA report;
2. `surface_foothold` — at least one exact-volume surface/mesh region is
   renderable and has CT/geometry provenance;
3. `heldout_geometry` — fit evidence can be withheld and evaluated without
   leakage;
4. `ink_validation` — train/prediction separation, checkpoint/seed binding,
   evaluated-array hashes, and falsification controls exist;
5. `vc3d_handoff` — the same surface/review evidence can be opened in the
   production VC3D workflow without coordinate ambiguity.

Every declared `pass` must carry at least one evidence artifact. Each artifact
must have a SHA-256, the exact candidate `volume_id`, a type, a location, and a
plain-language claim. A cross-volume artifact or a `pass` with no artifact
becomes a failure. A missing prerequisite stays `unknown`; it is never inferred
from scan quality or another stage.

## Input

```json
{
  "schema_version": 1,
  "as_of": "2026-10-03",
  "candidate": {
    "scroll": "PHerc0800",
    "volume_id": "20250521135224",
    "volume_root": "community-uploads/forrest/volcomp/PHerc0800/volumes/20250521135224-masked.zarr"
  },
  "prerequisites": {
    "input_integrity": {
      "state": "pass",
      "rationale": "Exact CT and geometry inputs passed the frozen integrity gate.",
      "artifacts": [
        {
          "kind": "zpa-report",
          "uri": "artifacts/2026-10-03-target/zpa.json",
          "sha256": "<64 lowercase hex>",
          "volume_id": "20250521135224",
          "claim": "Integrity PASS for the exact CT input consumed by the proof."
        }
      ]
    },
    "surface_foothold": {
      "state": "unknown",
      "rationale": "Exact-volume renderable surface proof not frozen yet.",
      "artifacts": []
    }
  }
}
```

Prerequisites omitted from the document are treated as `unknown`.

Run:

```bash
scroliq-target-gate \
  --in campaign/target.json \
  --out campaign/target-gate.json
```

Exit codes:

- `0` — `ready-to-freeze`: exact-volume identity and every prerequisite pass;
- `1` — `blocked` or `provisional`;
- `2` — malformed input, unreadable input, or an existing output path.

The output is create-only, includes canonical `input_sha256`, `manifest_sha256`, and per-target `manifest_target_sha256` bindings, preserves failed
and unknown checks, and always sets `ranking: null`.

## Status semantics

`ready-to-freeze` means the **evidence contract** is complete enough to start a
pre-registered proof campaign. It does not mean the scientific claims inside
third-party artifacts are true, the scroll is readable, the surface is
whole-scroll correct, or the target is more promising than another target.

`blocked` means at least one prerequisite failed, including invalid or
cross-volume evidence.

`provisional` means no prerequisite has failed but one or more are still
unknown.

This separation is intentional: ScrolIQ can verify identity, traceability, and
declared gate completeness without laundering those facts into a readability or
Grand Prize-success claim.

## Campaign use

Freeze a comparison cohort **before looking at held-out outcomes**. Run this
gate for every candidate in the cohort, using the same evidence requirements.
Only candidates at `ready-to-freeze` enter the blind probe. If none qualify,
publish the blocked/provisional records and start a new dated campaign rather
than changing the old gate after seeing results.
