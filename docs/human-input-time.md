# Human-input time receipts

The 2027 Grand Prize permits only a limited amount of documented human
annotation/input in the automated unrolling pipeline. `scroliq-package`
already refuses a human-input ledger whose total exceeds eight hours or differs
from `submission.human_input_hours`. `scroliq-human-time` makes that ledger
measured rather than reconstructed after the fact.

The emitted JSON remains schema version 1 and is directly compatible with the
existing package builder: every entry still has the required `description`
and `hours` fields. Additional receipt fields are ignored by the packager but
remain available to reviewers.

## Start a ledger

```bash
scroliq-human-time init --ledger submission-private/human-input.json
```

## Add a measured session

```bash
scroliq-human-time add \
  --ledger submission-private/human-input.json \
  --description "VC3D review of column 07 winding transition" \
  --stage vc3d-review \
  --operator reviewer-1 \
  --start-utc 2026-10-03T15:00:00Z \
  --end-utc 2026-10-03T15:24:30Z \
  --artifact column_07.tif \
  --root submission-private
```

The tool computes hours from UTC timestamps and refuses a new entry that would
push the ledger over eight hours. When `--artifact` is supplied, the receipt
also records the deterministic ScrolIQ SHA-256 for the inspected file or
directory-format artifact.

For work where a measured start/end interval is genuinely unavailable, an
explicit `--hours` value is supported:

```bash
scroliq-human-time add \
  --ledger submission-private/human-input.json \
  --description "Initial annotation import cleanup" \
  --stage annotation \
  --hours 0.20
```

Measured sessions are preferable because their duration is independently
recomputed whenever the ledger is summarized.

## Review the remaining budget

```bash
scroliq-human-time summary --ledger submission-private/human-input.json
```

The output reports entry count, total hours, remaining hours, and whether the
ledger is inside the eight-hour cap.

## Submission binding

Before building the final package, set
`submission.human_input_hours` in the provenance manifest to the exact ledger
total and pass the same ledger to:

```bash
scroliq-package build ... --human-input-log submission-private/human-input.json
```

The packager hashes the ledger and requires its total to match the provenance
declaration. The timer therefore strengthens the existing package contract
without changing its schema.
