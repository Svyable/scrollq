# Grand Prize letter-by-letter legibility ledger

`scroliq-legibility` is a conservative audit of **recorded reviewer
evidence** for the 2027 Grand Prize legibility criterion. It does not OCR the
scroll, infer missing letters, or decide whether a papyrological reading is
correct.

Its job is narrower: bind a letter-by-letter ledger to the exact submitted
mesh/render hashes and make the arithmetic impossible to hand-wave.

## What counts

For a preserved character to count as recorded legible, the ledger must supply:

- a stable character ID;
- a finite pixel bounding box `[x0, y0, x1, y1]` on the submitted render;
- exactly one visible-character reading (a base character plus combining marks
  is allowed); and
- `"interpolated": false`.

A preserved character that cannot be identified letter-by-letter is recorded
as `"status": "illegible"`. It stays in the denominator.

A physically lost character can be recorded as `"status": "lost"` only with
a short `loss_evidence` note. Lost characters are reported but do not enter
the preserved-character denominator.

The audit applies the 70% threshold **per counted column**. A high weighted
average cannot rescue a weak column.

## Ledger format

The ledger covers every submitted render column. Each row binds the exact
render and TIFXYZ mesh by ID and SHA-256:

```json
{
  "schema_version": 1,
  "scroll_id": "PHerc0813",
  "columns": [
    {
      "column": 1,
      "render_id": "render:column-01",
      "mesh_id": "mesh:column-01",
      "render_sha256": "<64 hex>",
      "mesh_sha256": "<64 hex>",
      "counted": true,
      "lines": [
        {
          "line": 1,
          "characters": [
            {
              "id": "c01-l01-001",
              "status": "legible",
              "reading": "α",
              "interpolated": false,
              "bbox_xyxy": [118, 74, 136, 101]
            },
            {
              "id": "c01-l01-002",
              "status": "illegible",
              "bbox_xyxy": [139, 74, 157, 101]
            },
            {
              "id": "c01-l01-003",
              "status": "lost",
              "loss_evidence": "Papyrus missing at this character position"
            }
          ]
        }
      ]
    }
  ]
}
```

A column omitted from counting is not silently ignored. It must still have a
ledger row with `"counted": false` and a documented acknowledgement:

```json
{
  "counted": false,
  "exclusion": {
    "reason": "No ink is preserved in this column",
    "challenge_acknowledged": true,
    "reference": "email-2027-05-01"
  }
}
```

The `reference` is an audit trail identifier or link supplied by the
submission team. ScrolIQ does not independently verify that acknowledgement.

## Run

```bash
scroliq-legibility \
  --manifest submission/provenance.json \
  --ledger submission/legibility.json \
  --out submission/legibility-report.json
```

Exit code is 0 only when the ledger is structurally valid, every submitted
render column is covered, all mesh/render hashes match, every counted column
has at least one preserved character, every counted column reaches 70%, and
all exclusions carry the required acknowledgement record.

The report also records:

- submitted, counted, and excluded column counts;
- preserved and recorded-legible character counts;
- the per-column recorded legibility fraction;
- lines containing at least one identified character;
- lines whose preserved characters are all identified; and
- lines reaching at least 70% recorded legibility.

The last three are descriptive evidence. They are **not** a claim about how
the Challenge will count legible lines for ranking.

## Scope

A passing ledger means the supplied evidence is internally consistent and
meets the recorded arithmetic threshold. It does not prove that the readings
are correct, that bounding boxes correspond to real ink, or that the Grand
Prize judges will accept the characters as legible.

That distinction is intentional. The tool is designed to make reviewer work
traceable without turning a software check into a papyrological authority.
