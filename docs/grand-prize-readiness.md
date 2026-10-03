# Grand Prize pre-submission readiness

ScrolIQ separates three questions that are easy to collapse into one:

1. **Does the package satisfy machine-checkable 2027 Grand Prize provenance and eligibility requirements?** Schema-v5 `scroliq-provenance` answers this from the submission manifest, including the hash-pinned ZPA source attestation and model physical-input/preprocessing contract.
2. **What do independent geometry diagnostics actually establish about the submitted meshes?** `scroliq-evidence` records immutable native reports and re-verifies adapter-backed conclusions.
3. **Is every required proof strong enough to authorize a submission-ready verdict?** `scroliq-gp-ready` composes the two fail-closed.

This is a **ScrolIQ policy**, not an official Scroll Prize eligibility decision. A future READY result will still not establish papyrological legibility and will not replace organizer evaluation.

## Verdicts

- **READY** — provenance is eligible and every required independent claim has an authorized, re-verifiable PASS over the full submitted scope.
- **BLOCKED** — provenance fails, a native evidence artifact is inconsistent/tampered, or an authorized and exact-input-bound required diagnostic explicitly fails.
- **UNKNOWN** — provenance passes, but one or more required independent claims are missing, partial, unsupported by the current policy, or do not cover every submitted mesh.

UNKNOWN is deliberately non-zero at the CLI. Missing evidence never becomes a clean result.

## Policy v1: intentionally not all-green yet

Required per submitted mesh:

| claim | v1 PASS authority | interpretation |
|---|---|---|
| `flattening-isometry` | **not yet authorized** | `flatcheck-grid/v1` is ingested as independent evidence, but Flatcheck's native JSON names the mesh path without hashing its input bytes; ScrolIQ refuses to turn a potentially stale report into a package-level PASS |
| `mesh-self-intersection` | **authorized:** `windcheck-check/v1` | windcheck's `windcheck_check/v1` certificate says CLEAN and both triangulations contain zero transverse contacts |
| `render-handedness` | **not yet authorized** | `handcheck` can determine mesh orientation, but the final render transform must also be bound before this can be a package-level PASS |

Required once for the exact eligible volume:

| claim | v1 PASS authority | interpretation |
|---|---|---|
| `spiral-held-out` | **not yet authorized** | `spiralcheck` provides held-out/leakage-audited geometry metrics, but publishes no universal quality threshold; ScrolIQ will not invent one |

Advisory claims are recorded but do not authorize READY: `surface-sheet-identity`, `surface-ct-support`, and `cross-scan-registration`.

Therefore **policy v1 is expected to remain UNKNOWN at full-package level** even when the currently authorized self-intersection check passes. That is deliberate. READY remains unreachable until flattening evidence is exact-byte-bound, handedness is bound through the final render, and a pre-registered spiral acceptance rule exists.

## Native evidence, not copied conclusions

A required geometry verdict—PASS **or FAIL**—must come from an approved adapter. The normalized ledger is not the authority; the native report is. Unapproved or input-unbound diagnostics remain evidence, but they cannot clear or convict the submitted mesh.

For Grand Prize readiness, `--root-dir` is mandatory. ScrolIQ:

1. finds the package-relative native report;
2. checks its SHA-256 against the ledger;
3. parses it with the named adapter;
4. recomputes claim/status/summary;
5. verifies the native diagnostic's own input identity against the submitted mesh when that format supports content identity;
6. fails on any mismatch.

A hand-edited `"status": "pass"` or `"status": "fail"` therefore cannot authorize a required claim.
Mesh-scoped entries also carry the canonical tifxyz tree digest; `scroliq-gp-ready`
compares it to the mesh digest in the provenance manifest, so evidence from a
different mesh cannot be relabeled onto the submitted mesh ID.

This distinction is intentional. A digest recorded by ScrolIQ *after* the fact
proves which mesh is in the package; it does not prove that an older third-party
report consumed those bytes. A tool may authorize PASS only when its native
evidence is itself content-bound and ScrolIQ can independently re-check that
binding.

### Flatcheck

Generate a whole-mesh report; windowed reports are refused as submission-wide evidence:

```bash
flatcheck report column_01.tifxyz --json evidence/column_01-flatcheck.json --strict
```

Normalize it:

```bash
scroliq-evidence-import flatcheck \
  --report evidence/column_01-flatcheck.json \
  --mesh-id mesh:column-01 \
  --artifact-url https://example.org/submission/evidence/column_01-flatcheck.json \
  --mesh-path column_01.tifxyz \
  --producer-commit <40-hex-flatcheck-commit> \
  --command "flatcheck report column_01.tifxyz --json evidence/column_01-flatcheck.json --strict" \
  --out evidence/column_01-flatcheck.entry.json
```

The adapter evaluates the **grid** result because the tifxyz grid is the submitted render canvas. A SLIM/ARAP alternative cannot make a failing submitted grid pass. Flatcheck reports remain useful independent corroboration, but policy v1 deliberately downgrades a declared Flatcheck PASS to unresolved because the native report does not hash the input tifxyz. The clean fix is upstream input-content identity or a verifier-controlled rerun; ScrolIQ does not substitute filename equality for that proof.

### Windcheck

Generate the report-only certificate:

```bash
windcheck check column_01.tifxyz --out evidence/windcheck-column-01
```

Then normalize the emitted `*_check_certificate.json`:

```bash
scroliq-evidence-import windcheck \
  --report evidence/windcheck-column-01/column_01_check_certificate.json \
  --mesh-id mesh:column-01 \
  --artifact-url https://example.org/submission/evidence/column_01_check_certificate.json \
  --mesh-path column_01.tifxyz \
  --producer-commit <40-hex-windcheck-commit> \
  --command "windcheck check column_01.tifxyz --out evidence/windcheck-column-01" \
  --out evidence/column_01-windcheck.entry.json
```

The adapter checks the certificate schema, report-only flag, both transverse-contact counts, crossing-event count, `clean` flag and clean definition. It then independently recomputes the certificate's `windcheck_mesh_manifest/v1` identity against the submitted `x.tif`, `y.tif`, `z.tif`, masks and `meta.json`. A contradictory certificate, malformed manifest, stale report, or byte mismatch is refused rather than interpreted.

For corpus/release evidence, the existing `scroliq-evidence-bind` path remains the preferred way to compose ScrolIQ Mesh IQ with Windcheck's public release index: it already distinguishes coordinate-exact from semantic-exact binding and refuses to launder measurements from a transformed base onto the published original.

## Ledger format

The ledger binds to one exact eligible volume and retains immutable references to native evidence:

```json
{
  "schema_version": 1,
  "diagnostic": "grand-prize-evidence-ledger",
  "volume_id": "20250821151723",
  "entries": [
    {
      "id": "flatcheck:mesh:column-01",
      "claim": "flattening-isometry",
      "status": "pass",
      "tool": "flatcheck",
      "artifact_url": "https://example.org/evidence/column_01-flatcheck.json",
      "path": "evidence/column_01-flatcheck.json",
      "sha256": "<64 hex>",
      "scope": {
        "mesh_ids": ["mesh:column-01"],
        "mesh_sha256": {"mesh:column-01": "<canonical tifxyz tree hash>"}
      },
      "producer": {
        "repository": "https://github.com/abundantjoe/flatcheck",
        "commit": "<40 hex>",
        "command": "flatcheck report column_01.tifxyz --json evidence/column_01-flatcheck.json --strict"
      },
      "normalization": {
        "adapter": "flatcheck-grid/v1",
        "assessment": {}
      }
    }
  ]
}
```

Use the importer rather than constructing adapter-backed entries by hand; the abbreviated `assessment` above is illustrative, not a valid generated entry.

## Commands

Validate a ledger against the package:

```bash
scroliq-evidence \
  --ledger submission/evidence.json \
  --volume-id 20250821151723 \
  --mesh mesh:column-01=column_01.tifxyz \
  --mesh mesh:column-02=column_02.tifxyz \
  --root-dir submission \
  --out submission/evidence.validation.json
```

Compose it with the provenance graph:

```bash
scroliq-gp-ready \
  --manifest submission/provenance.json \
  --evidence submission/evidence.json \
  --root-dir submission \
  --out submission/readiness.json
```

The readiness report retains both graph digests and separates blockers from unresolved claims.

## Next policy work

Do not weaken v1 just to obtain READY. Close the remaining claims with independent semantics:

1. **Flattening:** either upstream a content-identity block into Flatcheck's native report or add a verifier-controlled rerun path; only then promote `flatcheck-grid/v1` to a PASS authority.
2. **Handedness:** ingest `handcheck`'s decision, then bind its required correction to the exact final renderer command/output. Orientation knowledge alone is not proof that the submitted image applied it.
3. **Spiral held-out quality:** use the existing hash-bound `scroliq-geometry-validate` + `scrollq-geometry-probe` foundation for frozen point correspondences, denominator completeness and spatial exclusion; add `spiralcheck --manifest --fit-inputs` as an independent whole-surface/leakage witness. A native fitter exporter, real held-out run and pre-registered acceptance rule are still required before `spiral-held-out` may authorize PASS.
4. **Surface identity:** add `xsec`/physical-CT evidence for sheet jumps as an advisory channel first; promote only after a reproducible automated decision rule exists.
5. **Ink/legibility:** keep separate from geometry readiness. Existing `scroliq-ink-validate` proves deterministic held-out signal evidence and controls, but the Grand Prize's character-level legibility bar still requires its own evidence.

An adapter must never infer a submission verdict from a missing field, parser error, unsupported version, windowed/partial report, stale input, or a metric with no pre-registered acceptance rule.
