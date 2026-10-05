#!/bin/bash
# Role 4 (L4 VM): re-gate, smoke, then the untouched frozen 30k fit, reproduction
# check and official export. Evidence leaves the VM before it deletes itself.
# shellcheck source=common.sh disable=SC2034
source "$(dirname "$0")/common.sh"
init_role
require_state stage-env
require_state gpu-gate
require_state stage-data
FIT_MARKER=/run/scroliq-fit-started
arm_watchdog "$(mf watchdog.gpu_prep_window_minutes)" "$FIT_MARKER"
start_sync_loop

gate driver_ready
for _ in $(seq 60); do nvidia-smi >/dev/null 2>&1 && break; sleep 10; done

gate gpu_gate
"$CLOUD" gpu-gate --python "$VILLA_PY" --villa-root "$VILLA" --manifest "$SCROLIQ_MANIFEST" \
  --out "$EV/gpu-gate.json" >/dev/null
villa_clean

gate preflight_before_smoke
"$SQBIN/scroliq-spiral-preflight" --dataset "$DS" --recipe "$RECIPE" --out "$EV/preflight-before-smoke.json" >/dev/null
"$CLOUD" compare-preflight "$STATE/stage-data.preflight.json" "$EV/preflight-before-smoke.json" \
  --out "$EV/compare-stage-vs-before-smoke.json" >/dev/null
floor before_fit

vram_sampler() { nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 5 > "$1" & echo $!; }

gate smoke
SMOKE_RUN=$ROOT/runs/smoke-$ATTEMPT
SMOKE_CACHE=$ROOT/cache/smoke-$ATTEMPT
"$CLOUD" smoke-recipe --recipe "$RECIPE" --manifest "$SCROLIQ_MANIFEST" --out "$EV/smoke-recipe.json"
BUNDLE_FILES=("$SMOKE_RUN/spiral-run.stdout.log" "$SMOKE_RUN/spiral-run.stderr.log" "$SMOKE_RUN/spiral-run.receipt.json" "$EV/smoke-vram.csv")
VPID=$(vram_sampler "$EV/smoke-vram.csv")
smoke_rc=0
timeout "$(mf smoke.max_wall_minutes)m" "$SQBIN/scroliq-spiral-run" --dataset "$DS" --recipe "$EV/smoke-recipe.json" \
  --villa-root "$VILLA" --run-dir "$SMOKE_RUN" --cache-dir "$SMOKE_CACHE" --python "$VILLA_PY" || smoke_rc=$?
kill "$VPID" 2>/dev/null || true
mkdir -p "$EV/smoke"
cp "$SMOKE_RUN"/spiral-run.* "$EV/smoke/" 2>/dev/null || true
[ "$smoke_rc" = 0 ] || { echo "smoke run exited $smoke_rc"; false; }

gate smoke_verdict
"$CLOUD" smoke-verdict --manifest "$SCROLIQ_MANIFEST" --run-dir "$SMOKE_RUN" \
  --elapsed-vm-seconds "$(cut -d' ' -f1 /proc/uptime)" --vram-csv "$EV/smoke-vram.csv" \
  --out "$EV/smoke-verdict.json" >/dev/null

gate smoke_cleanup   # smoke output never sits next to the real run
rm -rf "$SMOKE_RUN" "$SMOKE_CACHE"
"$SQBIN/scroliq-spiral-preflight" --dataset "$DS" --recipe "$RECIPE" --out "$EV/preflight-after-smoke.json" >/dev/null
"$CLOUD" compare-preflight "$STATE/stage-data.preflight.json" "$EV/preflight-after-smoke.json" \
  --out "$EV/compare-stage-vs-after-smoke.json" >/dev/null
villa_clean
sync_evidence

gate fit
RUN=$ROOT/runs/pherc0826-bounded-01-$ATTEMPT
BUNDLE_FILES=("$RUN/spiral-run.stdout.log" "$RUN/spiral-run.stderr.log" "$RUN/spiral-run.receipt.json" "$EV/fit-vram.csv")
touch "$FIT_MARKER"   # preparation window closed: the frozen fit has begun
VPID=$(vram_sampler "$EV/fit-vram.csv")
fit_rc=0
"$SQBIN/scroliq-spiral-run" --dataset "$DS" --recipe "$RECIPE" --villa-root "$VILLA" \
  --run-dir "$RUN" --cache-dir "$ROOT/cache/full" --python "$VILLA_PY" || fit_rc=$?
kill "$VPID" 2>/dev/null || true
mkdir -p "$EV/fit"
find "$RUN" -maxdepth 1 -type f \( -name '*.json' -o -name '*.log' \) -exec cp {} "$EV/fit/" \;
if [ -f "$RUN/checkpoint_fitted.ckpt" ]; then
  sha256sum "$RUN/checkpoint_fitted.ckpt" | tee "$EV/fit/checkpoint_fitted.ckpt.sha256"
  [ "$(mf evidence_retention.checkpoint)" != upload ] \
    || gcloud storage cp "$RUN/checkpoint_fitted.ckpt" "$EV_URI/fit/checkpoint_fitted.ckpt" --quiet
fi
sync_evidence
[ "$fit_rc" = 0 ] || { echo "frozen fit receipt failed (rc $fit_rc)"; false; }

gate reproduction_check
BUNDLE_FILES=("$EV/fit/spiral-run.receipt.json")
"$SQBIN/scroliq-spiral-reproduction-check" --run-dir "$RUN" --out "$EV/reproduction-check.json"
sync_evidence

floor before_export
gate export
"$SQBIN/scroliq-spiral-export" --run-dir "$RUN" --dataset "$DS" --villa-root "$VILLA" \
  --reproduction-check "$EV/reproduction-check.json" --output "$RUN.tifxyz" \
  --evidence-dir "$EV/export" --python "$VILLA_PY"
[ "$(mf evidence_retention.tifxyz)" != upload ] \
  || gcloud storage rsync --recursive "$RUN.tifxyz" "$EV_URI/export/tifxyz" --quiet

gate finished
status pass
halt_vm
