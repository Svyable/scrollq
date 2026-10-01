# Pinned open-bucket metadata index (2026-10-01)

`metadata.min.json.gz` is the open-data bucket's own index, fetched on
2026-10-01 and committed unmodified so that tools which read it
(`scroliq-chunk-audit`, `scroliq-manifest`, `scroliq-pairs`) are reproducible
offline and independent of each other.

| | |
|---|---|
| Source | `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/metadata.min.json` (served gzip-encoded) |
| SHA-256 of the file as committed (gzip bytes) | `127be6e7468e8b2a2c48aaf033293bb305a736c25cead856e59876e0fe75065c` |
| SHA-256 of the decoded JSON (what the tools record as `index_sha256`) | `15848845907fe640e63c16d0de200715fe74ed4f256623c94ef603cc84831b22` |

The bucket's index changes over time; pass `--index <url>` to any of the tools
to use the live version, and compare `index_sha256` in their reports.
