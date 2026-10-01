# scrollq-health live verdicts, fail-closed integrity — 2026-10-01

Source commit: `433d90a763812afb1c05ef52ccfa74a49c826073` (workflow `health-verdicts.yml`).
Integrity now comes from `zpa.report.audit_root`; UNKNOWN integrity
(unreadable level, absent root, audit error) is DO NOT TRAIN, per the
companion contract's RECOMMENDED_CONSUMER_VERDICT. Every finding code
is recorded, including informational ones the 2026-09-30 reports dropped.

| report | verdict | integrity | finding codes | reason |
|---|---|---|---|---|
| `absent-root.json` | DO NOT TRAIN | UNKNOWN | ROOT_ABSENT | integrity UNKNOWN: missing evidence (NOT_FOUND) |
| `caution-dev-mesh.json` | CAUTION | PASS | CHUNK_EXCEEDS_SHAPE | quality unscorable: zarr.json unreadable: 404 Not Found: https://dl.ash2txt.org/other/dev/meshes/20231022170900-ome.zarr/0/zarr.json |
| `do-not-train-pherc0814.json` | DO NOT TRAIN | FAIL | LEVEL_NO_CHUNKS | 6 high-severity integrity finding(s) |
| `train-pherc0813.json` | TRAIN | PASS | CHUNK_EXCEEDS_SHAPE | integrity PASS, quality 76.2 |

Commands: see the workflow. Compare with `../2026-09-30-health-verdicts/`.
