#!/bin/bash
# Role 3 (CPU VM): download public inputs straight into GCP, pack resident pools,
# run the hard preflight. The L4 is not attached while any of this happens.
# shellcheck source=common.sh disable=SC2034
source "$(dirname "$0")/common.sh"
init_role
require_state stage-env
require_state gpu-gate
floor before_tracks

gate assemble_small_files
mkdir -p "$ROOT/data"
( cd "$ROOT/data" && python3 "$ASM/make_eligible_spiral_dataset.py" \
    --scroll "$(mf experiment_contract.scroll)" --outward-sense "$(mf staging_sources.outward_sense)" \
    --out ds0826 ) | tee "$EV/assembler-pass1.txt"
echo "$(mf staging_sources.spiral_scroll_json.sha256)  $DS/spiral-scroll.json" | sha256sum -c -
echo "$(mf staging_sources.umbilicus.sha256)  $DS/umbilicus.json" | sha256sum -c -

gate tracks_download
BASE=$(mf staging_sources.tracks.base_url)
DBM=$(mf staging_sources.tracks.dbm.name)
NPZ=$(mf staging_sources.tracks.crossings.name)
fetch_resume() {  # resume a partial download; a complete file is left alone (no 416)
  local url=$1 dest=$2 remote
  remote=$(curl -fsSIL "$url" | tr -d '\r' | awk 'tolower($1)=="content-length:" {n=$2} END {print n}')
  [ -n "$remote" ]
  if [ -f "$dest" ] && [ "$(stat -c%s "$dest")" = "$remote" ]; then return 0; fi
  curl -fL --retry 10 --retry-all-errors -C - -o "$dest" "$url"
  [ "$(stat -c%s "$dest")" = "$remote" ]
}
for name in "$DBM" "$NPZ"; do
  fetch_resume "$BASE/$name" "$DS/tracks/$name"
done
[ "$(stat -c%s "$DS/tracks/$DBM")" = "$(mf staging_sources.tracks.dbm.size)" ]

gate crossings_mtime_repair   # assembler restores the producer's nanosecond mtime
( cd "$ROOT/data" && python3 "$ASM/make_eligible_spiral_dataset.py" \
    --scroll "$(mf experiment_contract.scroll)" --outward-sense "$(mf staging_sources.outward_sense)" \
    --out ds0826 ) | tee "$EV/assembler-pass2.txt"
echo "$(mf staging_sources.spiral_scroll_json.sha256)  $DS/spiral-scroll.json" | sha256sum -c -
( cd "$DS/tracks" && sha256sum "$DBM" "$NPZ" ) | tee "$EV/tracks.sha256"

floor before_lasagna
gate lasagna_fetch
BUNDLE_FILES=("$EV/lasagna-fetch.json")
"$CLOUD" fetch-lasagna --manifest "$SCROLIQ_MANIFEST" --dataset "$DS" \
  --evidence-dir "$EV/lasagna" --out "$EV/lasagna-fetch.json" >/dev/null

floor before_pack
gate pack_resident_pools
( cd "$VILLA/spiral-fitting" && "$VILLA_PY" pack_resident_pools.py "$DS/lasagna_inputs" \
    --what normals,grad_mag --normal-group "$(mf staging_sources.lasagna.group)" --verify 2000 ) \
  | tee "$EV/pack-resident-pools.txt"
villa_clean
"$CLOUD" pool-size --dataset "$DS" --group "$(mf staging_sources.lasagna.group)" \
  --out "$EV/pool-size.json" >/dev/null

gate preflight
BUNDLE_FILES=("$EV/preflight.json")
"$SQBIN/scroliq-spiral-preflight" --dataset "$DS" --recipe "$RECIPE" --out "$EV/preflight.json" >/dev/null
cp "$EV/preflight.json" "$STATE/stage-data.preflight.json"

floor before_fit

gate record
python3 - "$EV" <<'PY'
import hashlib, json, sys, pathlib
ev = pathlib.Path(sys.argv[1])
sha = lambda p: hashlib.sha256((ev / p).read_bytes()).hexdigest()
pools = json.loads((ev / "pool-size.json").read_text())
json.dump({"preflight_sha256": sha("preflight.json"), "lasagna_fetch_sha256": sha("lasagna-fetch.json"),
           "tracks_sha256_file": (ev / "tracks.sha256").read_text(),
           "resident_pools": {"total_bytes": pools["total_bytes"], "sidecars": pools["sidecars"]}},
          open(ev / "state-extra.json", "w"), indent=2, sort_keys=True)
PY
write_state "$EV/state-extra.json"
status pass
halt_vm
