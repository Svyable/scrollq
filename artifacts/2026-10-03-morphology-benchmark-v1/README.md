# Profilometry morphology source benchmark v1

**Status:** preregistered and executable; no real-data result committed yet.

This directory freezes the decision rule for the first source-only morphology
benchmark. It is intentionally separate from
`artifacts/2026-10-03-morphology-control/`, whose earlier control manifest is
already frozen and is bound here by SHA-256.

Run against a complete local mirror of
`scrollprize/profilometer@a806bead2f3b9100c20e19de37814fb285cfeefd`:

```bash
scroliq-morphology-benchmark \
  --spec artifacts/2026-10-03-morphology-benchmark-v1/spec.json \
  --control-manifest artifacts/2026-10-03-morphology-control/source-benchmark-manifest.json \
  --dataset-manifest /data/profilometer/manifest.csv \
  --data-root /data/profilometer \
  --out out/profilometer-lopo-descriptors-v1.json
```

The runner requires all 14 samples, validates declared pixel counts and raw
X/Y raster ordering, hashes every consumed height/label/raw source, and keeps
the unresolved public physical-sampling discrepancy visible. A descriptor may
be retained only as a **source-only** physical-control candidate; this
experiment cannot authorize transfer to a Grand Prize CT volume.
