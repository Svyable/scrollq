#!/bin/bash
# Role 1 (CPU VM): tools, pinned clones, villa environment, CPU import gate.
# No large data is touched; a broken environment costs CPU minutes, not L4 hours.
# shellcheck source=common.sh disable=SC2034
source "$(dirname "$0")/common.sh"
init_role

gate tools_uv
UV_VERSION=$(mf software.uv.version)
UV_SHA=$(mf software.uv.linux_x86_64_tarball_sha256)
mkdir -p "$ROOT/tools/uv" "$ROOT/tmp"
curl -fsSL --retry 5 -o "$ROOT/tmp/uv.tar.gz" \
  "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
echo "$UV_SHA  $ROOT/tmp/uv.tar.gz" | sha256sum -c -
tar -xzf "$ROOT/tmp/uv.tar.gz" -C "$ROOT/tools/uv" --strip-components=1
uv --version | tee "$EV/uv-version.txt"

gate build_toolchain
command -v cmake && command -v g++ || { apt-get update -qq && apt-get install -y -qq build-essential cmake; }
{ g++ --version | head -1; cmake --version | head -1; } | tee "$EV/toolchain.txt"

gate clone_villa
git clone --quiet --filter=blob:none --no-checkout --sparse "$(mf software.villa.repository)" "$VILLA"
mapfile -t SPARSE < <(mf software.villa.sparse_paths | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)))')
git -C "$VILLA" sparse-checkout set "${SPARSE[@]}"
git -C "$VILLA" -c advice.detachedHead=false checkout --quiet "$(mf software.villa.commit)"
villa_clean

gate clone_assembler
git clone --quiet "$(mf software.assembler.repository)" "$ASM"
git -C "$ASM" -c advice.detachedHead=false checkout --quiet "$(mf software.assembler.commit)"
[ "$(git -C "$ASM" rev-parse HEAD)" = "$(mf software.assembler.commit)" ]
[ -z "$(git -C "$ASM" status --porcelain --untracked-files=all)" ]

gate scrollq_env
rm -rf "$ROOT/tmp/scrollq-src" && mkdir -p "$ROOT/tmp/scrollq-src"
git -C "$SQ" archive "$SCROLIQ_COMMIT" | tar -x -C "$ROOT/tmp/scrollq-src"   # build outside the checkout
uv venv --quiet --python "$(mf software.scrollq_python)" "$ROOT/env/scrollq"
uv pip install --quiet --python "$ROOT/env/scrollq/bin/python" "$ROOT/tmp/scrollq-src"
"$CLOUD" --help >/dev/null

floor before_villa_env

gate villa_env
uv python install "$(mf software.villa_python)"
UV_PROJECT_ENVIRONMENT=$ROOT/env/villa uv sync --locked --project "$VILLA/spiral-fitting"
uv pip freeze --python "$VILLA_PY" > "$EV/villa-freeze.txt"
"$VILLA_PY" --version | tee "$EV/villa-python.txt"
villa_clean

gate cpu_import_gate
"$CLOUD" gpu-gate --cpu-only --python "$VILLA_PY" --villa-root "$VILLA" \
  --manifest "$SCROLIQ_MANIFEST" --out "$EV/cpu-import-gate.json" >/dev/null
villa_clean

gate uv_cache_clean
uv cache clean
rm -rf "$ROOT/tmp"

gate record
python3 - "$EV/state-extra.json" "$EV" <<'PY'
import hashlib, json, sys, pathlib
ev = pathlib.Path(sys.argv[2])
sha = lambda p: hashlib.sha256((ev / p).read_bytes()).hexdigest()
json.dump({"villa_freeze_sha256": sha("villa-freeze.txt"), "uv_version": (ev / "uv-version.txt").read_text().strip(),
           "villa_python": (ev / "villa-python.txt").read_text().strip(),
           "cpu_import_gate_sha256": sha("cpu-import-gate.json")}, open(sys.argv[1], "w"), indent=2)
PY
write_state "$EV/state-extra.json"
status pass
halt_vm
