# Grand Prize pre-submission readiness

ScrolIQ separates two questions that are easy to accidentally collapse:

1. **Does the package satisfy machine-checkable 2027 Grand Prize provenance and eligibility requirements?** `scroliq-provenance` answers this from the submission manifest.
2. **Do independent diagnostics support the geometry choices we are about to submit?** `scroliq-evidence` records those proofs without pretending third-party tools share one native JSON schema.

`scroliq-gp-ready` composes the two into a fail-closed pre-submission verdict.

This is a **ScrolIQ policy**, not an official Scroll Prize eligibility decision. A READY result does not establish papyrological legibility and does not replace organizer evaluation.

## Verdicts

- **READY** — the provenance manifest is eligible and every required independent-evidence claim passes over the full submitted scope.
- **BLOCKED** — the provenance validator fails, the evidence ledger is structurally invalid, or an independent required claim explicitly fails.
- **UNKNOWN** — provenance passes, but one or more required independent claims are missing, partial, or do not cover every submitted mesh.

UNKNOWN is deliberately non-zero at the CLI. Missing evidence never becomes a clean result.

## Evidence policy v1

Required per submitted mesh:

| claim | intended independent witness |
|---|---|
| `flattening-isometry` | e.g. `flatcheck` or an equivalent distortion/fold-over evaluator |
| `mesh-self-intersection` | e.g. `windcheck`, VC3D transverse-intersection evidence, or equivalent |
| `render-handedness` | e.g. `handcheck` or an equivalent chirality/frame check |

Required once for the exact eligible volume:

| claim | intended independent witness |
|---|---|
| `spiral-held-out` | e.g. `spiralcheck` or an equivalent held-out spiral-fit evaluation |

Advisory claims are recorded but do not currently authorize READY: `surface-sheet-identity`, `surface-ct-support`, and `cross-scan-registration`.

The policy is intentionally small. New claims should be promoted to required only after there is a reproducible evaluator and a clear interpretation of PASS/FAIL on real scroll data.

## Ledger format

Each ledger binds to one exact eligible volume and contains immutable references to diagnostic artifacts:

```json
{
  "schema_version": 1,
  "diagnostic": "grand-prize-evidence-ledger",
  "volume_id": "20250821151723",
  "entries": [
    {
      "id": "flatcheck:column-01",
      "claim": "flattening-isometry",
      "status": "pass",
      "tool": "flatcheck",
      "artifact_url": "https://example.org/reports/column-01-flatcheck.json",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "scope": {"mesh_ids": ["mesh:column-01"]},
      "producer": {
        "repository": "https://github.com/example/flatcheck",
        "commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "command": "flatcheck report column_01.tifxyz --json report.json"
      }
    }
  ]
}
```

The URL is provenance; the digest is identity. If `path` is also supplied and `--root-dir` is used, ScrolIQ hashes the local artifact and fails on a mismatch.

## Commands

Validate the ledger alone:

```bash
scroliq-evidence \
  --ledger submission/evidence.json \
  --volume-id 20250821151723 \
  --mesh-id mesh:column-01 \
  --mesh-id mesh:column-02 \
  --out submission/evidence.validation.json
```

Compose it with the existing provenance graph:

```bash
scroliq-gp-ready \
  --manifest submission/provenance.json \
  --evidence submission/evidence.json \
  --root-dir submission \
  --out submission/readiness.json
```

The readiness report retains the provenance and evidence graph digests, exposes blockers separately from unknowns, and is designed to be used as a CI gate before generating the final submission email/package.

## Adapter roadmap

Do not hand-copy numerical results into the ledger when a source tool exposes machine-readable output. Add small adapters that translate a pinned native report into one normalized entry while retaining the original artifact SHA and producer commit.

Initial targets, in order:

1. `flatcheck` → `flattening-isometry`
2. `handcheck` → `render-handedness`
3. `windcheck` / VC3D self-intersection output → `mesh-self-intersection`
4. `spiralcheck` → `spiral-held-out`
5. `xsec` and CT-support diagnostics → advisory surface evidence

An adapter must never infer PASS from a missing field, a parser error, or an unsupported version. Unknown stays unknown.
