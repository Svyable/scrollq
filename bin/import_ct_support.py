"""Import external ct_support surveys for a prize manifest, pinned to a commit.

Usage: python bin/import_ct_support.py <prize> <out.json>

Fetches ``ct_support/survey_<scroll>.json`` from
axiosdevs/herculaneum-scroll-tools at COMMIT through the GitHub contents API,
records each file's blob SHA, and normalizes it with
``scrollq.support.normalize_external`` (fail-closed on any scan other than the
exact eligible one).
"""
import base64
import json
import sys

import requests

sys.path.insert(0, "src")
from scrollq.grand_prize import MANIFESTS
from scrollq.support import normalize_external

REPO = "axiosdevs/herculaneum-scroll-tools"
COMMIT = "63a09d4fd8a46ac758ff475a8b6389a2c8152cb7"


def main() -> None:
    prize, out = sys.argv[1], sys.argv[2]
    rows = []
    for t in MANIFESTS[prize]["targets"]:
        path = f"ct_support/survey_{t['scroll']}.json"
        r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{path}",
                         params={"ref": COMMIT}, timeout=60)
        if r.status_code == 404:
            rows.append({"scroll": t["scroll"],
                         "eligible_volume_id": t["volume_id"],
                         "usable_for_qualification": False,
                         "exclusion_reason": f"no {path} at {COMMIT[:12]}"})
            continue
        r.raise_for_status()
        meta = r.json()
        survey = json.loads(base64.b64decode(meta["content"]))
        row = normalize_external(t, survey, path, meta["sha"])
        rows.append(row)
        print(f"{t['scroll']:11} {row['volume_match']:10} "
              f"{row.get('sampled_support_frac')}")
    doc = {
        "schema_version": 1,
        "source": {
            "repository": REPO,
            "commit": COMMIT,
            "definition": (
                "sampled_support_frac = 1 - sampled_phantom_frac; a phantom "
                "voxel is a surface-prediction voxel above threshold where the "
                "aligned masked CT voxel is exactly zero."
            ),
            "note": ("Imported external evidence. ScrolIQ does not claim "
                     "authorship and does not treat it as ink evidence."),
        },
        "rows": rows,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
