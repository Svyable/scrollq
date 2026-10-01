"""Derive prize target manifests from official eligibility data + bucket index.

``grand_prize.DEFAULT_MANIFEST`` was copied by hand from the data browser. This
module builds the same structure from two pinned machine-readable sources:

* the Challenge's own eligibility list (``prizeEligibility.json`` in the villa
  monorepo's website data), and
* the open-data bucket's ``metadata.min.json`` index (voxel size, energy,
  released surface/lasagna predictions, public segments).

The result feeds :func:`scrollq.grand_prize.qualify` unchanged, and
:func:`compare_targets` reports drift between a hand-copied manifest and a
derived one. Nothing here scores or ranks anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bucket import load_json_maybe_gz

SCHEMA_VERSION = 1

PRIZES = {
    "grand-prize-2027": {
        "label": "2027 Grand Prize",
        # Spiral fitting needs both released predictions as bootstrap assets.
        "required_assets": ["surface_prediction", "lasagna_prediction"],
        "higher_res_key": "excluded_same_scroll_higher_res",
        "higher_res_reason": (
            "The 2027 Grand Prize fixes this scroll to the listed volume. The "
            "prize rules prohibit using data derived from a higher-resolution "
            "scan of the submitted scroll volume."),
    },
    "first-letters-2027": {
        "label": "2027 First Letters",
        # The official workflow starts from a grown segment on the recto
        # surface prediction; lasagna is not required to begin.
        "required_assets": ["surface_prediction"],
        "higher_res_key": "same_scroll_higher_res_scans",
        "higher_res_reason": (
            "A higher-resolution scan of the same scroll exists in the open "
            "bucket. The prizes page does not state a prohibition for First "
            "Letters as of the pinned source; confirm with the organizers "
            "before using data derived from it."),
    },
}


def _model_ids(volume: dict, type_: str, path_contains: str | None) -> list[str]:
    ids = set()
    for item in volume.get("data", []):
        if item.get("type") != type_:
            continue
        path = (item.get("origins") or [{}])[0].get("path", "")
        if path_contains and path_contains not in path:
            continue
        mid = (item.get("parameters") or {}).get("model_id")
        if mid is not None:
            ids.add(str(mid))
    return sorted(ids)


def derive_manifest(prize_id: str, eligibility: dict, index: dict, *,
                    as_of: str, eligibility_source: str,
                    eligibility_sha256: str, index_sha256: str) -> dict:
    """Build a ``qualify``-compatible manifest; problems are listed, not hidden."""
    if prize_id not in PRIZES:
        raise ValueError(f"unknown prize {prize_id!r}; "
                         f"choose from {sorted(PRIZES)}")
    cfg = PRIZES[prize_id]
    rows = eligibility.get(prize_id)
    if not isinstance(rows, list):
        raise ValueError(f"eligibility data has no list for {prize_id!r}")
    samples = index.get("samples", {})
    targets, problems = [], []
    for e in rows:
        scroll, vid = e["scroll"], e["volume"]
        rec = samples.get(scroll)
        vol = (rec or {}).get("volumes", {}).get(vid)
        if vol is None:
            problems.append({"scroll": scroll, "volume_id": vid,
                             "problem": "eligible volume not in bucket index"})
            continue
        px = vol["properties"].get("pixel_size_um")
        surf = _model_ids(vol, "surface-prediction-zarr", None)
        las = _model_ids(vol, "lasagna", "predictions/lasagna/")
        higher = [
            {"volume_id": wid, "voxel_size_um": w["properties"]["pixel_size_um"],
             "energy_kev": w["properties"].get("energy_keV"),
             "reason": cfg["higher_res_reason"]}
            for wid, w in sorted(rec["volumes"].items())
            if wid != vid and px is not None
            and w["properties"].get("pixel_size_um", 1e9) < px * 0.999]
        t = {
            "scroll": scroll, "volume_id": vid, "voxel_size_um": px,
            "energy_kev": vol["properties"].get("energy_keV"),
            "segments": len(rec.get("segments", {})),
            "surface_prediction": surf[-1] if surf else None,
            "lasagna_prediction": las[-1] if las else None,
            "all_surface_predictions": surf,
            "all_lasagna_predictions": las,
            "source_url": f"https://scrollprize.org/data_browser/{scroll}",
        }
        if higher:
            t[cfg["higher_res_key"]] = higher
        targets.append(t)
    return {
        "schema_version": SCHEMA_VERSION,
        "prize_id": prize_id, "prize_label": cfg["label"],
        "as_of": as_of, "prize_url": "https://scrollprize.org/prizes",
        "required_assets": list(cfg["required_assets"]),
        "provenance": {
            "eligibility_source": eligibility_source,
            "eligibility_sha256": eligibility_sha256,
            "index_sha256": index_sha256,
        },
        "problems": problems,
        "targets": targets,
    }


_COMPARED = ("volume_id", "voxel_size_um", "energy_kev", "segments")


def _higher_res_ids(target: dict) -> set:
    return {h["volume_id"]
            for key in ("excluded_same_scroll_higher_res",
                        "same_scroll_higher_res_scans")
            for h in target.get(key, [])}


def compare_targets(reference: dict, derived: dict) -> list[str]:
    """Differences between a hand-copied manifest and a derived one.

    Empty list means no drift. The reference's single prediction ids must be
    among the derived ones (a newer prediction is not drift by itself).
    """
    out: list[str] = []
    ref = {t["scroll"]: t for t in reference["targets"]}
    der = {t["scroll"]: t for t in derived["targets"]}
    for scroll in sorted(set(ref) - set(der)):
        out.append(f"{scroll}: in reference manifest but not eligible/derived")
    for scroll in sorted(set(der) - set(ref)):
        out.append(f"{scroll}: eligible/derived but missing from reference")
    for scroll in sorted(set(ref) & set(der)):
        r, d = ref[scroll], der[scroll]
        for k in _COMPARED:
            rv, dv = r.get(k), d.get(k)
            same = (abs(rv - dv) < 1e-6 if isinstance(rv, (int, float))
                    and isinstance(dv, (int, float)) else rv == dv)
            if not same:
                out.append(f"{scroll}: {k} {rv!r} != {dv!r}")
        for k, pool in (("surface_prediction", "all_surface_predictions"),
                        ("lasagna_prediction", "all_lasagna_predictions")):
            if r.get(k) and r[k] not in d.get(pool, []):
                out.append(f"{scroll}: {k} {r[k]!r} not among {d.get(pool)}")
        # The same set of known higher-resolution scans must be recorded,
        # whether a manifest files them as prohibited (Grand Prize) or as
        # informational (First Letters, whose rules do not prohibit them).
        rh = _higher_res_ids(r)
        dh = _higher_res_ids(d)
        if rh != dh:
            out.append(f"{scroll}: higher-resolution exclusions "
                       f"{sorted(rh)} != {sorted(dh)}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="scroliq-manifest",
        description="Derive a prize target manifest from official eligibility "
                    "data and the open-bucket index; optionally check the "
                    "hand-copied Grand Prize manifest for drift.")
    ap.add_argument("--eligibility", required=True,
                    help="prizeEligibility.json (path or URL)")
    ap.add_argument("--eligibility-source", default=None,
                    help="provenance string, e.g. "
                         "'ScrollPrize/villa@<sha>:scrollprize.org/src/data/"
                         "prizeEligibility.json'")
    ap.add_argument("--index", required=True,
                    help="bucket metadata.min.json (path or URL; .gz ok)")
    ap.add_argument("--prize", required=True, choices=sorted(PRIZES))
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare-builtin", action="store_true",
                    help="grand-prize-2027 only: exit 1 if the built-in "
                         "manifest drifts from the derived one")
    args = ap.parse_args(argv)

    elig, elig_sha = load_json_maybe_gz(args.eligibility)
    index, index_sha = load_json_maybe_gz(args.index)
    manifest = derive_manifest(
        args.prize, elig, index, as_of=args.as_of,
        eligibility_source=args.eligibility_source or args.eligibility,
        eligibility_sha256=elig_sha, index_sha256=index_sha)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{args.prize}: {len(manifest['targets'])} targets derived, "
          f"{len(manifest['problems'])} problems", file=sys.stderr)
    for p in manifest["problems"]:
        print(f"  problem: {p}", file=sys.stderr)
    if args.compare_builtin:
        if args.prize != "grand-prize-2027":
            print("--compare-builtin applies to grand-prize-2027 only",
                  file=sys.stderr)
            return 2
        from .grand_prize import DEFAULT_MANIFEST
        drift = compare_targets(DEFAULT_MANIFEST, manifest)
        for line in drift:
            print(f"  drift: {line}", file=sys.stderr)
        print("built-in manifest matches derived manifest" if not drift
              else f"{len(drift)} drift finding(s)", file=sys.stderr)
        return 1 if drift else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
