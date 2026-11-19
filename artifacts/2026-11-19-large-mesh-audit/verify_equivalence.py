"""Prove the row-block audit reports exactly what the unblocked code reported.

For every mesh in equivalence_sample.txt: download its four files into
out/eq/ (untracked), check them against the SHA-256s recorded in the
2026-10-01 report (fail closed on changed bytes), then audit it twice with the
same arguments:

  baseline  scrollq.tifxyz_audit as of BASELINE_REF (whole-grid evaluation),
            loaded straight from git
  current   the installed scrollq.tifxyz_audit (row blocks), default blocks
            and 1-row blocks

The reports, minus the local path, must be byte-identical. The script also
records how the current finding kinds compare with the frozen 2026-10-01
report, whose code predates later audit changes. Writes equivalence.json and
exits non-zero on any difference.

    python artifacts/2026-11-19-large-mesh-audit/verify_equivalence.py
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from scrollq import tifxyz_audit as current

BASELINE_REF = "9807b0c"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "..", "2026-10-01-corpus-mesh-audit")
WORK = os.path.join(REPO, "out", "eq")


def load_baseline():
    code = subprocess.run(["git", "-C", REPO, "show", f"{BASELINE_REF}:src/scrollq/tifxyz_audit.py"],
                          check=True, capture_output=True, text=True).stdout
    path = os.path.join(tempfile.mkdtemp(), "tifxyz_audit_baseline.py")
    with open(path, "w") as fh:
        fh.write(code)
    spec = importlib.util.spec_from_file_location("tifxyz_audit_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(mesh, provenance):
    root = os.path.join(WORK, os.path.basename(mesh))
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    for name, pin in provenance.items():
        dest = os.path.join(root, name)
        for attempt in range(4):
            try:
                urllib.request.urlretrieve(f"{BUCKET}/{mesh}/{name}", dest)
                break
            except OSError:
                if attempt == 3:
                    raise
        if sha256(dest) != pin["sha256"]:
            raise SystemExit(f"{mesh}/{name}: bytes differ from the 2026-10-01 pin")
    return root


def canon(report):
    report = dict(report)
    report.pop("tifxyz_path", None)
    return json.dumps(report, sort_keys=True)


def main():
    baseline = load_baseline()
    rows, differences = [], 0
    for line in open(os.path.join(HERE, "equivalence_sample.txt")):
        rel = line.strip()
        if not rel:
            continue
        frozen = json.load(open(os.path.join(SRC, rel)))
        scroll, segment, name = os.path.basename(rel)[:-5].split(".", 2)
        mesh = f"{scroll}/segments/{segment}/mesh/{name}.tifxyz"
        root = fetch(mesh, frozen["provenance"])
        kw = {"volume_root": frozen["volume_root"]}
        want = canon(baseline.audit_tifxyz(root, **kw))
        got = canon(current.audit_tifxyz(root, **kw))
        got_1 = canon(current.audit_tifxyz(root, block_rows=1, **kw))
        same = want == got == got_1
        differences += not same
        kinds_now = sorted({f["kind"] for f in json.loads(got)["findings"]})
        kinds_then = sorted({f["kind"] for f in frozen["findings"]})
        rows.append({
            "mesh": mesh,
            "z_tif_bytes": frozen["provenance"]["z.tif"]["bytes"],
            "vertices": json.loads(got)["grid"]["vertices"],
            "identical_to_baseline": same,
            "finding_kinds_current": kinds_now,
            "finding_kinds_2026_10_01": kinds_then,
            "same_kinds_as_2026_10_01": kinds_now == kinds_then,
        })
        print(("OK  " if same else "DIFF"), mesh, flush=True)
        shutil.rmtree(root)
    out = {
        "baseline_ref": BASELINE_REF,
        "meshes": len(rows),
        "identical": sum(r["identical_to_baseline"] for r in rows),
        "same_kinds_as_2026_10_01": sum(r["same_kinds_as_2026_10_01"] for r in rows),
        "rows": rows,
    }
    with open(os.path.join(HERE, "equivalence.json"), "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))
    if differences or not rows:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
