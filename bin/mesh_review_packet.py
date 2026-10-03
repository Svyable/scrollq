"""Build a deterministic, key-free O1 reviewer ZIP from the frozen sample."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "artifacts/2026-10-01-mesh-review-sample"


def build(output: Path, sample: Path = SAMPLE) -> None:
    sheet = (sample / "review-sheet.csv").read_bytes()
    manifest = json.loads((sample / "manifest.json").read_text())
    if hashlib.sha256(sheet).hexdigest() != manifest["files_sha256"]["review-sheet.csv"]:
        raise ValueError("frozen review sheet checksum mismatch")
    # Deliberate allowlist: no key, finding kinds, strata or source reports.
    files = {"review-sheet.csv": sheet,
             "REVIEW.md": (ROOT / "docs/mesh-review-handoff.md").read_bytes()}
    with ZipFile(output, "x", compression=ZIP_STORED) as archive:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(2026, 10, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    build(Path(args.out))


if __name__ == "__main__":
    main()
