# Grand Prize pre-submission readiness

ScrolIQ separates three questions that are easy to collapse into one:

1. **Does the package satisfy machine-checkable 2027 Grand Prize provenance and eligibility requirements?** `scroliq-provenance` answers this from the submission manifest.
2. **What do independent geometry diagnostics actually establish about the submitted meshes?** `scroliq-evidence` records immutable native reports and re-verifies adapter-backed conclusions.
3. **Is every required proof strong enough to authorize a submission-ready verdict?** `scroliq-gp-ready` composes the two fail-closed.

This is a **ScrolIQ policy**, not an official Scroll Prize eligibility decision. A future READY result will still not establish papyrological legibility and will not replace organizer evaluation.

## Verdicts

- **READY** — provenance is eligible and every required independent claim has an authorized, re-verifiable PASS over the full submitted scope.
- **BLOCKED** — provenance fails, a native evidence artifact is inconsistent/tampered, or a required independent diagnostic explicitly fails.
- **UNKNOWN** — provenance passes, but one or more required independent claims are missing, partial, unsupported by the current policy, or do not cover every submitted mesh.

UNKNOWN is deliberately non-zero at the CLI. Missing evidence never becomes a clean result.

## Policy v1: intentionally not all-green yet

Required per submitted mesh:

| claim | v1 PASS authority | interpretation |
|---|---|---|
| `flattening-isometry` | **authorized:** `flatcheck-grid/v1` | whole submitted tifxyz grid clears flatcheck's declared bar, has no collapse and zero foldovers |
| `mesh-self-intersection` | **authorized:** `windcheck-check/v1` | windcheck's `windcheck_check/v1` certificate says CLEAN and both triangulations contain zero transverse contacts |
| `render-handedness` | **not yet authorized** | `handcheck` can determine mesh orientation, but the final render transform must also be bound before this can be a package-level PASS |

Required once for the exact eligible volume:

| claim | v1 PASS authority | interpretation |
|---|---|---|
| `spiral-held-out` | **not yet authorized** | `spiralcheck` provides held-out/leakage-audited geometry metrics, but publishes no universal quality threshold; ScrolIQ will not invent one |

Advisory claims are recorded but do not authorize READY: `surface-sheet-identity`, `surface-ct-support`, and `cross-scan-registration`.

Therefore **policy v1 is expected to remain UNKNOWN at full-package level** even after the two currently objective geometry checks pass. That is deliberate. The next policy revisions must close handedness and calibrate a pre-registered spiral acceptance rule before READY can become reachable.

## Native evidence, not copied conclusions

A required PASS must come from an approved adapter. The normalized ledger is not the authority; the native report is.

For Grand Prize readiness, `--root-dir` is mandatory. ScrolIQ:

1. finds the package-relative native report;
2. checks its SHA-256 against the ledger;
3. parses it with the named adapter;
4. recomputes claim/status/summary;
5. fails on any mismatch.

A hand-edited `"status": "pass"` therefore cannot authorize a required claim.
Mesh-scoped entries also carry the canonical tifxyz tree digest; `scroliq-gp-ready`
compares it to the mesh digest in the provenance manifest, so evidence from a
different mesh cannot be relabeled onto the submitted mesh ID.

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

The adapter evaluates the **grid** result because the tifxyz grid is the submitted render canvas. A SLIM/ARAP alternative cannot make a failing submitted grid pass.

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

The adapter checks the certificate schema, report-only flag, both transverse-contact counts, crossing-event count, `clean` flag and clean definition. A contradictory certificate is refused rather than interpreted.

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
  --mesh-id mesh:column-01 \
  --mesh-id mesh:column-02 \
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

1. **Handedness:** ingest `handcheck`'s decision, then bind its required correction to the exact final renderer command/output. Orientation knowledge alone is not proof that the submitted image applied it.
2. **Spiral held-out quality:** ingest `spiralcheck` with `--manifest --fit-inputs`, require a non-empty unseen aggregate and clean hash/leakage audit, then calibrate and pre-register an acceptance rule on public reference surfaces before it may authorize PASS.
3. **Surface identity:** add `xsec`/physical-CT evidence for sheet jumps as an advisory channel first; promote only after a reproducible automated decision rule exists.
4. **Ink/legibility:** keep separate from geometry readiness. Existing `scroliq-ink-validate` proves deterministic held-out signal evidence and controls, but the Grand Prize's character-level legibility bar still requires its own evidence.

An adapter must never infer PASS from a missing field, parser error, unsupported version, windowed/partial report, or a metric with no pre-registered acceptance rule.
