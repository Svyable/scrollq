# scrollq-health end-to-end verdicts — 2026-09-30

Fresh runs of the unified command against live data, both verdict paths:

```bash
# DO NOT TRAIN — defective S3 pyramid (villa #1892)
scrollq-health \
  --root "PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr" \
  --base s3://vesuvius-challenge-open-data \
  --out artifacts/2026-09-30-health-verdicts/do-not-train-pherc0814.json
# => verdict: DO NOT TRAIN (6 high-severity integrity finding(s))
#    integrity: FAIL (6 levels, 6 findings)

# TRAIN — healthy dl volcomp volume
scrollq-health \
  --root "community-uploads/forrest/volcomp/PHerc0813/volumes/20250821151723-9.362um-1.2m-113keV-masked.zarr" \
  --base https://dl.ash2txt.org \
  --out artifacts/2026-09-30-health-verdicts/train-pherc0813.json
# => verdict: TRAIN (integrity PASS, quality 77.4)
#    integrity: PASS (6 levels, 1 informational finding only)
#    quality: 77.4/100 (signal 40.0, texture 22.8, dynamic 14.6)
```

The defective pyramid's quality score is honestly *unscorable* (no decodable
chunks to score) rather than invented — the verdict comes from the integrity
audit alone. Each run's full log is kept alongside the JSON.
