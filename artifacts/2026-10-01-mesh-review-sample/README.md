# O1 mesh review sample — 2026-10-01

Blinded, stratified sample of segments from
[`../2026-10-01-corpus-mesh-audit/`](../2026-10-01-corpus-mesh-audit/) for a
person to review in VC3D. Protocol and decision rule:
[`docs/mesh-review-protocol.md`](../../docs/mesh-review-protocol.md).

**Status: awaiting review.** No labels yet, so no precision exists.

| file | what |
|---|---|
| `review-sheet.csv` | what the reviewer sees and fills in: id, scroll, segment, mesh URL, CT root, `label`, `defect_type`, `notes` |
| `key.json` | stratum, tier and finding kinds per id. **Reviewers: do not open before labelling.** |
| `manifest.json` | seed, stratum sizes, SHA-256 of the sheet, key and source summary |

Sample: 30 flagged (F), 4 debug controls (D), 20 clean (C); seed `20261001`.

```bash
python bin/mesh_review_sample.py artifacts/2026-10-01-mesh-review-sample   # regenerates identically
python bin/mesh_review_score.py artifacts/2026-10-01-mesh-review-sample    # after labelling
```

## Deviation log

(none)
